"""Layer 3: grounding and business rules, alone and inside the repair loop."""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from stickyminutes import checks, db, schema, transcripts
from stickyminutes.models import Item, Meeting, RunIssue

from .conftest import words
from .samples import GOOD, MEETING, good, with_action
from .test_summarize import add_meeting, latest, run_summary, use_claude

LINES = transcripts.parse(MEETING).lines
MEETING_ROW = SimpleNamespace(meeting_date=date(2026, 11, 24), speakers=["Maria Santos", "Ben Cruz", "Ana Reyes"])


def review(answer):
    notes, problems = schema.validate(__import__("json").dumps(answer))
    assert problems == [], problems
    found = {}
    return notes, checks.review(notes, LINES, MEETING_ROW, found), found


def test_the_good_answer_passes():
    _, problems, found = review(GOOD)
    assert problems == [] and all(found.values()) and len(found) == 6


@pytest.mark.parametrize("quote, words_", [
    ("WE AGREED   last week on 450 pesos", None),                 # case and spaces
    ("We agreed last week on 450 pesos, so let’s keep it.", None),   # curly apostrophe
])
def test_quotes_are_compared_kindly(quote, words_):
    answer = good()
    answer["decisions"][0]["evidence"][0]["quote"] = quote
    _, problems, _ = review(answer)
    assert problems == []


def test_a_made_up_quote_is_a_problem():
    answer = good()
    answer["decisions"][0]["evidence"][0]["quote"] = "We will charge 500 pesos"
    _, problems, found = review(answer)
    assert [(p.layer, p.path) for p in problems] == [("grounding", "decisions.0.evidence.0")]
    assert "isn't on line 4 or anywhere in the transcript" in problems[0].message
    assert found[("decisions", 0, 0)] is False


def test_a_quote_on_another_line_names_the_right_line():
    answer = good()
    answer["decisions"][1]["evidence"][0]["line"] = 2
    _, problems, _ = review(answer)
    assert "is on line 5, not line 2" in problems[0].message


def test_a_line_that_doesnt_exist():
    answer = good()
    answer["open_questions"][0]["evidence"][0]["line"] = 99
    _, problems, _ = review(answer)
    assert problems[0].path == "open_questions.0.evidence.0.line" and "lines 1 to 8" in problems[0].message


def test_a_first_name_owner_becomes_the_speaker_label():
    notes, problems, _ = review(with_action(owner="Ben"))
    assert problems == [] and notes.action_items[0].owner == "Ben Cruz"


def test_an_owner_nobody_mentioned_is_a_problem():
    _, problems, _ = review(with_action(owner="Carlos"))
    assert problems[0].path == "action_items.0.owner" and "isn't a speaker" in problems[0].message


def test_a_missing_due_date_is_worked_out_from_the_phrase():
    notes, problems, _ = review(with_action(due_date=None, due_phrase="by Friday"))
    assert problems == [] and notes.action_items[0].due_date == date(2026, 11, 27)


def test_a_due_date_that_doesnt_match_its_phrase():
    _, problems, _ = review(with_action(due_date="2026-12-04", due_phrase="by Friday"))
    assert "means 2026-11-27, not 2026-12-04" in problems[0].message


def test_a_due_date_before_the_meeting():
    _, problems, _ = review(with_action(due_date="2026-11-01", due_phrase=None))
    assert "before the meeting" in problems[0].message


def test_twins_are_merged():
    answer = good()
    answer["decisions"].append(dict(answer["decisions"][0], text="The price stays at 450 pesos"))
    notes, problems, _ = review(answer)
    assert problems == [] and len(notes.decisions) == 2


@pytest.mark.parametrize("phrase, expected", [
    ("tomorrow", date(2026, 11, 25)),
    ("by end of day", date(2026, 11, 24)),
    ("by Friday", date(2026, 11, 27)),
    ("on Tuesday", date(2026, 12, 1)),          # said on a Tuesday: next week's
    ("December 15", date(2026, 12, 15)),
    ("by 3rd January", date(2027, 1, 3)),
    ("the 10th", date(2026, 12, 10)),
    ("next Friday", None),                      # people mean different days
    ("next week", None),
    ("soon", None),
])
def test_due_phrases(phrase, expected):
    assert checks.resolve_due(phrase, date(2026, 11, 24)) == expected


# ---------- In the loop ----------

def test_a_made_up_quote_is_repaired(app, owner):
    client, _ = owner
    answer = good()
    answer["decisions"][0]["evidence"][0]["quote"] = "We will charge 500 pesos"
    fake = use_claude(app, answer, GOOD)
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    run = latest(app, meeting_id)
    assert (run.status, run.attempts) == ("done", 2)
    assert "decisions.0.evidence.0: the quote “We will charge 500 pesos” isn't on line 4" in fake.calls[1]["messages"][2]["content"]
    with app.app_context():
        issue = db.session().scalar(select(RunIssue).where(RunIssue.run_id == run.id))
        assert (issue.layer, issue.fixed) == ("grounding", True)


def test_a_problem_that_never_goes_away_is_flagged_not_dropped(app, owner):
    client, _ = owner
    use_claude(app, with_action(owner="Carlos"))
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    run = latest(app, meeting_id)
    assert (run.status, run.attempts) == ("needs_review", 3)
    with app.app_context():
        s = db.session()
        assert s.get(Meeting, meeting_id).status == "needs_review"
        flagged = s.scalars(select(Item).where(Item.meeting_id == meeting_id, Item.flag.is_not(None))).all()
        assert [item.text for item in flagged] == ["Send the final label files to the printer"]
        assert flagged[0].flag.startswith("owner: “Carlos” isn't a speaker")
    page = words(client.get(f"/meetings/{meeting_id}"))
    assert "Some Notes Need a Look" in page and "1 note still failed a check" in page


def test_found_quotes_are_marked_on_the_notes(app, owner):
    client, _ = owner
    answer = good()
    answer["key_points"][0]["evidence"].append({"line": 3, "quote": "nothing like this was said"})
    use_claude(app, answer)
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    with app.app_context():
        point = db.session().scalar(select(Item).where(Item.meeting_id == meeting_id, Item.kind == "point"))
        assert [e["found"] for e in point.evidence] == [True, False]
    page = client.get(f"/meetings/{meeting_id}").get_data(as_text=True)
    assert "chip chip-found" in page and "chip chip-missing" in page


def test_an_empty_answer_for_a_meeting_with_nothing_decided_is_fine(app, owner):
    client, _ = owner
    use_claude(app, good(decisions=[], action_items=[], open_questions=[]))
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    assert latest(app, meeting_id).status == "done"
    assert "None in this meeting." in words(client.get(f"/meetings/{meeting_id}"))
