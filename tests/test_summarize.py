"""A summary from start to end: the run, repair turns, failures, the notes saved, and the budget."""
import pytest
from sqlalchemy import func, select

from stickyminutes import db, summarize
from stickyminutes.llm import FakeClaude, LLMError
from stickyminutes.models import Item, Meeting, Run, RunIssue, UsageEntry

from .conftest import post, text, words
from .samples import GOOD, MEETING, good


def use_claude(app, *script, practice=False):
    """Make the app's Claude a FakeClaude with this script (practice=False: counted like real money)."""
    fake = FakeClaude(script=list(script) if script else None, practice=practice)
    app.extensions["claude"] = fake
    return fake


def add_meeting(client, transcript=MEETING, title="Launch planning"):
    response = post(client, "/meetings/new", {"title": title, "meeting_date": "2026-11-24", "transcript": transcript})
    assert response.status_code == 302, text(response)
    return int(response.headers["Location"].rsplit("/", 1)[-1])


def run_summary(client, meeting_id):
    return post(client, f"/meetings/{meeting_id}/summarize")


def latest(app, meeting_id):
    with app.app_context():
        s = db.session()
        run = s.scalar(select(Run).where(Run.meeting_id == meeting_id).order_by(Run.id.desc()))
        s.expunge_all()
        return run


def test_a_good_answer_is_saved_as_notes(app, owner):
    client, _ = owner
    fake = use_claude(app, GOOD)
    meeting_id = add_meeting(client)
    assert run_summary(client, meeting_id).status_code == 302
    run = latest(app, meeting_id)
    assert (run.status, run.attempts, run.served_model) == ("done", 1, "claude-opus-5-5")
    assert run.cost_micros > 0 and run.input_tokens > 0
    with app.app_context():
        s = db.session()
        meeting = s.get(Meeting, meeting_id)
        assert meeting.status == "ready" and meeting.overview.startswith("The team set the launch")
        kinds = s.execute(select(Item.kind, func.count()).where(Item.meeting_id == meeting_id).group_by(Item.kind)).all()
        assert dict(kinds) == {"point": 1, "decision": 2, "action": 2, "question": 1}
    page = words(client.get(f"/meetings/{meeting_id}"))
    assert "The launch is on December 15." in page and "Ben Cruz" in page and "Run again" in page
    # The transcript went in a cached block, and the facts about the meeting after it.
    first = fake.calls[0]["messages"][0]["content"]
    assert first[0]["cache_control"] == {"type": "ephemeral"} and "[5] Ben Cruz: Then we'll go with" in first[0]["text"]
    assert "Date: 2026-11-24 (Tuesday)" in first[1]["text"]


def test_the_title_comes_from_claude_only_when_we_made_it_up(app, owner):
    client, _ = owner
    use_claude(app, GOOD)
    mine = add_meeting(client, title="Launch planning")
    untitled = add_meeting(client, title="")
    run_summary(client, mine)
    run_summary(client, untitled)
    with app.app_context():
        s = db.session()
        assert s.get(Meeting, mine).title == "Launch planning"
        assert s.get(Meeting, untitled).title == "New blend launch"


def test_broken_json_is_repaired_on_the_next_try(app, owner):
    client, _ = owner
    fake = use_claude(app, '{"title": "New blend', GOOD)
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    run = latest(app, meeting_id)
    assert (run.status, run.attempts) == ("done", 2)
    with app.app_context():
        issues = db.session().scalars(select(RunIssue).where(RunIssue.run_id == run.id)).all()
        assert [(i.attempt, i.layer, i.fixed) for i in issues] == [(1, "schema", True)]
    # The repair turn sent the first answer back as it was, then the problems.
    second = fake.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"] == [{"type": "text", "text": '{"title": "New blend'}]
    assert "not valid JSON" in second[2]["content"]


def test_a_broken_rule_is_sent_back_with_its_place(app, owner):
    client, _ = owner
    long_overview = "One. Two. Three. Four. Five. Six."
    fake = use_claude(app, good(overview=long_overview), GOOD)
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    assert latest(app, meeting_id).status == "done"
    assert "overview: has 6 sentences; use 2 to 4" in fake.calls[1]["messages"][2]["content"]


def test_an_answer_that_never_gets_its_shape_fails(app, owner):
    client, _ = owner
    use_claude(app, "nope")
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    run = latest(app, meeting_id)
    assert (run.status, run.attempts, run.error_code) == ("failed", 3, "shape")
    page = words(client.get(f"/meetings/{meeting_id}"))
    assert "The Summary Didn't Finish" in page and "never had the right shape" in page


def test_a_refusal_fails_with_its_reason_and_is_still_paid_for(app, owner):
    client, _ = owner
    use_claude(app, ("refusal", ""))
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    run = latest(app, meeting_id)
    assert (run.status, run.error_code) == ("failed", "refusal")
    assert "declined" in run.error and run.input_tokens > 0


def test_an_api_error_fails_the_run_with_a_plain_message(app, owner):
    client, _ = owner
    use_claude(app, LLMError("overloaded", "Claude is very busy right now. Try again in a few minutes.", retry=True))
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    assert "very busy" in words(client.get(f"/meetings/{meeting_id}"))


def test_running_again_replaces_the_notes(app, owner):
    client, _ = owner
    use_claude(app, GOOD)
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    run_summary(client, meeting_id)
    with app.app_context():
        s = db.session()
        assert s.scalar(select(func.count()).select_from(Run).where(Run.meeting_id == meeting_id)) == 2
        assert s.scalar(select(func.count()).select_from(Item).where(Item.meeting_id == meeting_id)) == 6


def test_the_status_json_while_it_runs(app, owner):
    client, _ = owner
    meeting_id = add_meeting(client)
    with app.app_context():
        s = db.session()
        s.get(Meeting, meeting_id).status = "running"
        s.add(Run(meeting_id=meeting_id, status="running", model="claude-opus-5-5", prompt_version="v1"))
        s.commit()
    state = client.get(f"/meetings/{meeting_id}/status.json").get_json()
    assert state == {"status": "running", "words": "Summarizing", "attempts": 0, "finished": False}
    assert "data-status-url" in text(client.get(f"/meetings/{meeting_id}"))
    run_summary(client, meeting_id)  # a second click while it runs
    assert "being summarized already" in text(client.get(f"/meetings/{meeting_id}"))


def test_a_run_that_died_with_the_server_is_marked_failed(app, owner):
    client, _ = owner
    meeting_id = add_meeting(client)
    with app.app_context():
        s = db.session()
        s.get(Meeting, meeting_id).status = "running"
        s.add(Run(meeting_id=meeting_id, status="running", model="claude-opus-5-5", prompt_version="v1",
                  created_at=summarize.utcnow() - summarize.STALE_AFTER))
        s.commit()
    assert client.get(f"/meetings/{meeting_id}/status.json").get_json()["status"] == "failed"
    assert "server restarted" in words(client.get(f"/meetings/{meeting_id}"))


def test_practice_mode_costs_nothing(app, owner):
    client, _ = owner
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    run = latest(app, meeting_id)
    assert run.practice and run.status == "done" and run.cost_micros == 0
    with app.app_context():
        assert db.session().scalar(select(func.count()).select_from(UsageEntry)) == 0
    assert "Practice notes" in words(client.get(f"/meetings/{meeting_id}"))


def test_the_demo_gets_three_real_summaries_a_day(app, demo):
    client, _ = demo
    use_claude(app, GOOD)
    meeting_id = add_meeting(client)
    for _ in range(3):
        run_summary(client, meeting_id)
    assert "0 real summaries left today" in words(client.get(f"/meetings/{meeting_id}"))
    response = run_summary(client, meeting_id)
    page = words(client.get(response.headers["Location"]))
    assert "can run 3 real summaries a day" in page
    with app.app_context():
        assert db.session().scalar(select(func.count()).select_from(Run)) == 3


def test_the_site_stops_at_its_daily_cap(app, owner):
    client, _ = owner
    app.config["DAILY_CAP_CENTS"] = 1
    use_claude(app, GOOD)
    meeting_id = add_meeting(client)
    with app.app_context():
        s = db.session()
        s.add(UsageEntry(day=summarize.utcnow().date(), cost_micros=9_990))
        s.commit()
    response = run_summary(client, meeting_id)
    assert "today's spending limit" in words(client.get(response.headers["Location"]))


def test_the_ledger_keeps_counting_after_a_demo_is_deleted(app, demo):
    from stickyminutes import seed
    client, workspace_id = demo
    use_claude(app, GOOD)
    run_summary(client, add_meeting(client))
    with app.app_context():
        s = db.session()
        spent = s.scalar(select(func.sum(UsageEntry.cost_micros)))
        s.get(seed.Workspace, workspace_id).demo_expires_at = summarize.utcnow()
        seed.purge(s, summarize.utcnow())
        s.commit()
        assert spent > 0 and s.scalar(select(func.sum(UsageEntry.cost_micros))) == spent


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-haiku-5-5"])
def test_the_workspaces_model_is_used(app, owner, model):
    client, _ = owner
    fake = use_claude(app, GOOD)
    post(client, "/settings", {"action": "model", "model": model})
    run_summary(client, add_meeting(client))
    assert fake.calls[0]["model"] == model


def test_another_workspace_cant_start_or_watch_it(app, owner, demo):
    client, _ = owner
    meeting_id = add_meeting(client)
    stranger, _ = demo
    assert run_summary(stranger, meeting_id).status_code == 404
    assert stranger.get(f"/meetings/{meeting_id}/status.json").status_code == 404
