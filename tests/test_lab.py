"""The Quality Lab: runs and their problems, and the test set's scoring."""
from sqlalchemy import select

from stickyminutes import db, evals, summarize
from stickyminutes.llm import FakeClaude, LLMError
from stickyminutes.models import EvalRun, Workspace

from .conftest import post, text, words
from .samples import GOOD, with_action
from .test_summarize import add_meeting, latest, run_summary, use_claude


def test_the_runs_page_counts_tries_problems_and_cost(app, owner):
    client, _ = owner
    use_claude(app, with_action(owner="Carlos"), GOOD)  # one repair, then good
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    page = words(client.get("/lab"))
    assert "1 Summaries run" in page and "0% Right the first time" in page and "2.0 Tries on average" in page
    assert "1 Problems caught" in page and "100% Fixed by a repair turn" in page
    assert "Launch planning" in page and "claude-opus-5-5" in page


def test_one_runs_page_shows_each_try(app, owner):
    client, _ = owner
    use_claude(app, '{"title": "broken', with_action(owner="Carlos"), GOOD)
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    run = latest(app, meeting_id)
    page = words(client.get(f"/lab/runs/{run.id}"))
    assert "Try 1" in page and "Shape (the API's layer)" in page and "not valid JSON" in page
    assert "Try 2" in page and "Grounding (the transcript)" in page and "action_items.0.owner" in page
    assert "Try 3" in page and "Passed every check." in page
    assert page.count("Fixed later") == 2
    assert "Claude's Last Answer" in page and '"title": "New blend launch"' in text(client.get(f"/lab/runs/{run.id}"))


def test_the_problems_page_groups_the_same_mistake(app, owner):
    client, _ = owner
    use_claude(app, with_action(owner="Carlos"), GOOD, with_action(owner="Carlos"), GOOD)
    for _ in range(2):
        run_summary(client, add_meeting(client))
    page = words(client.get("/lab/problems"))
    assert "action_items.#.owner Latest: “Carlos” isn't a speaker" in page and "nobody took it on 2 100%" in page
    assert page.count("None caught yet.") == 2  # shape and rules had nothing


def test_another_workspaces_run_is_not_found(app, owner, demo):
    client, _ = owner
    use_claude(app, GOOD)
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    stranger, _ = demo
    assert stranger.get(f"/lab/runs/{latest(app, meeting_id).id}").status_code == 404
    assert "Launch planning" not in words(stranger.get("/lab"))  # only the demo's own sample runs


# ---------- The test set ----------

def perfect_answer(messages):
    """An answer that finds everything the case expects, quoting the real lines."""
    from stickyminutes.llm import transcript_lines
    lines = transcript_lines(messages)
    text_of = {n: text for n, _, text in lines}
    case = next(c for c in evals.CASES if c.transcript.splitlines()[0].split(": ", 1)[1] == text_of[1])
    evidence = [{"line": 1, "quote": " ".join(text_of[1].split()[:4])}]
    return {"title": case.title, "overview": "A test meeting.", "key_points": [],
            "decisions": [{"text": " ".join(keys), "rationale": None, "evidence": evidence} for keys in case.decisions],
            "action_items": [{"task": " ".join(keys), "owner": owner, "due_phrase": None, "due_date": None,
                              "priority": "medium", "evidence": evidence} for keys, owner in case.actions],
            "open_questions": []}


def test_a_perfect_answer_scores_full_marks(app, owner):
    client, _ = owner
    app.extensions["claude"] = FakeClaude(script=[perfect_answer], practice=False)
    response = post(client, "/lab/tests", {"prompt_version": "v1", "model": "claude-opus-5-5"})
    assert response.status_code == 302
    with app.app_context():
        run = db.session().scalar(select(EvalRun))
        assert run.status == "done" and len(run.results) == 6
        assert run.summary["recall"] == 1.0 and run.summary["owners"] == 1.0 and run.summary["grounding"] == 1.0
        assert run.summary["first_try"] == 1.0 and run.summary["made_up"] == 0 and run.cost_micros > 0
    page = words(client.get(response.headers["Location"]))
    assert "Office subscription idea" in page and "Average 100% 100% 100%" in page


def test_made_up_items_and_misses_are_counted():
    case = next(c for c in evals.CASES if c.key == "idea")
    notes = summarize.schema.MeetingNotes.model_validate({
        "title": "Idea", "overview": "Talk.", "key_points": [], "open_questions": [],
        "decisions": [{"text": "Launch an office plan", "rationale": None, "evidence": [{"line": 1, "quote": "a coffee subscription"}]}],
        "action_items": []})
    result = evals.score(case, summarize.Outcome(notes, [], {("decisions", 0, 0): True}, 1))
    assert result["made_up"] == 1 and result["recall"] is None
    standup = evals.CASES[0]
    result = evals.score(standup, summarize.Outcome(notes, [], {}, 1))
    assert result["recall"] == 0.0 and result["owners"] is None


def test_an_api_error_on_a_case_is_scored_not_crashed(app, owner):
    client, _ = owner
    app.extensions["claude"] = FakeClaude(script=[LLMError("overloaded", "Claude is very busy.")], practice=False)
    post(client, "/lab/tests", {"prompt_version": "v2", "model": "claude-haiku-5-5"})
    with app.app_context():
        run = db.session().scalar(select(EvalRun))
        assert run.status == "done" and run.results[0]["error"] == "Claude is very busy."
        assert run.summary["passed"] == 0.0


def test_practice_mode_runs_free_even_in_the_demo(app, demo):
    client, _ = demo
    post(client, "/lab/tests", {"prompt_version": "v1", "model": "claude-opus-5-5"})
    with app.app_context():
        run = db.session().scalar(select(EvalRun).where(EvalRun.sample.is_(False)))
        assert run.practice and run.status == "done" and run.cost_micros == 0
    assert "Practice" in words(client.get("/lab/tests"))


def test_the_demo_cant_run_it_for_real(app, demo):
    client, _ = demo
    use_claude(app, GOOD)
    assert post(client, "/lab/tests", {"prompt_version": "v1", "model": "claude-opus-5-5"}).status_code == 403
    assert "The demo can't run the test set" in words(client.get("/lab/tests"))


def test_made_up_choices_are_refused(app, owner):
    client, _ = owner
    response = post(client, "/lab/tests", {"prompt_version": "../secrets", "model": "claude-opus-5-5"})
    assert "Choose a prompt version" in words(client.get(response.headers["Location"]))


def test_the_test_set_respects_the_daily_cap(app, owner):
    client, _ = owner
    app.config["DAILY_CAP_CENTS"] = 0
    use_claude(app, GOOD)
    response = post(client, "/lab/tests", {"prompt_version": "v1", "model": "claude-opus-5-5"})
    assert "spending limit" in words(client.get(response.headers["Location"]))


def test_the_prompt_version_setting_is_used(app, owner):
    client, workspace_id = owner
    fake = use_claude(app, GOOD)
    post(client, "/settings", {"action": "prompt", "prompt_version": "v2"})
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    with app.app_context():
        assert db.session().get(Workspace, workspace_id).prompt_version == "v2"
    assert "Before you answer, check every quote" in fake.calls[0]["system"][0]["text"]
    assert latest(app, meeting_id).prompt_version == "v2"


def test_try_claude_command(app):
    runner = app.test_cli_runner()
    refused = runner.invoke(args=["try-claude"])
    assert refused.exit_code != 0 and "no ANTHROPIC_API_KEY" in refused.output
    from stickyminutes import demo_samples
    from stickyminutes.llm import transcript_lines
    standup = demo_samples.SAMPLES[0]["answer"]
    app.extensions["claude"] = FakeClaude(script=[lambda messages: demo_samples.build(standup, transcript_lines(messages))],
                                          practice=False)
    result = runner.invoke(args=["try-claude", "--sample", "standup", "--model", "claude-sonnet-5-5"])
    assert result.exit_code == 0, result.output
    assert "Try 1: passed every check." in result.output and "Monday stand-up" in result.output
    assert "Fix the bug that makes the discount code disappear (Ben Cruz, due" in result.output
