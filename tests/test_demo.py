"""The demo: every page it can open shows an example, and the samples say they are samples."""
from datetime import datetime

import pytest
from sqlalchemy import func, select

from stickyminutes import db, demo_samples, seed, transcripts
from stickyminutes.models import EvalRun, Item, Meeting, Run

from .conftest import browser, text, words


def demo_meetings(app, workspace_id):
    with app.app_context():
        s = db.session()
        rows = s.scalars(select(Meeting).where(Meeting.workspace_id == workspace_id).order_by(Meeting.id)).all()
        s.expunge_all()
        return rows


def test_every_page_of_the_demo_shows_an_example(app, demo):
    client, workspace_id = demo
    meetings = demo_meetings(app, workspace_id)
    assert len(meetings) == 6
    pages = {
        "/meetings": "Monday Stand-up",
        "/actions": "Fix the bug that makes the discount code disappear",
        "/actions?tab=overdue": "Overdue:",
        "/actions?tab=done": "Add a grind check to the packing list",
        "/lab": "Sample",
        "/lab/problems": "action_items.#.evidence.#",
        "/lab/tests": "v2",
        "/settings": "Kape Cloud Meetings",
        "/meetings/new": "Where to Find a Transcript",
    }
    for url, expected in pages.items():
        response = client.get(url)
        assert response.status_code == 200, url
        assert expected in words(response) or expected in text(response), url
    assert "No Action Items Yet" not in words(client.get("/actions"))
    for meeting in meetings:
        page = words(client.get(f"/meetings/{meeting.id}"))
        assert "Key Points" in page and "Sample notes, written for the demo" in page, meeting.title
        for extra in ("export.md", "print", "email"):
            assert client.get(f"/meetings/{meeting.id}/{extra}").status_code == 200
    with app.app_context():
        s = db.session()
        run = s.scalar(select(Run).join(Meeting).where(Meeting.workspace_id == workspace_id))
        test_run = s.scalar(select(EvalRun).where(EvalRun.workspace_id == workspace_id))
        item = s.scalar(select(Item).join(Meeting).where(Meeting.workspace_id == workspace_id))
    assert "Checks, Try by Try" in words(client.get(f"/lab/runs/{run.id}"))
    assert "Office subscription idea" in words(client.get(f"/lab/tests/{test_run.id}"))
    assert client.get(f"/items/{item.id}/edit").status_code == 200


def test_the_samples_show_each_state(app, demo):
    client, workspace_id = demo
    by_title = {m.title: m for m in demo_meetings(app, workspace_id)}
    assert by_title["Sprint Planning: Loyalty Points"].status == "needs_review"
    assert {m.status for t, m in by_title.items() if t != "Sprint Planning: Loyalty Points"} == {"ready"}
    with app.app_context():
        s = db.session()
        runs = {s.get(Meeting, r.meeting_id).title: r for r in s.scalars(select(Run).join(Meeting).where(Meeting.workspace_id == workspace_id))}
        assert runs["Wholesale Call with Café Rosa"].attempts == 2  # the wrong line was repaired
        assert runs["Sprint Planning: Loyalty Points"].attempts == 3  # the reworded quote never was
        assert all(r.sample and r.cost_micros == 0 for r in runs.values())
        flagged = s.scalars(select(Item).where(Item.flag.is_not(None), Item.meeting_id == by_title["Sprint Planning: Loyalty Points"].id)).all()
        assert [i.text for i in flagged] == ["Write the help text and the FAQ for the points page"]
        assert s.scalar(select(func.count()).select_from(Item).join(Meeting).where(Meeting.workspace_id == workspace_id, Item.edited.is_(True))) == 1
        assert s.scalar(select(func.count()).select_from(Item).join(Meeting).where(Meeting.workspace_id == workspace_id, Item.status == "done")) == 3
        assert by_title["Wholesale Call with Café Rosa"].share_nonce is not None
        tests = s.scalars(select(EvalRun).where(EvalRun.workspace_id == workspace_id).order_by(EvalRun.id)).all()
        assert [(t.prompt_version, t.sample) for t in tests] == [("v1", True), ("v2", True)]
        assert tests[0].summary["made_up"] == 1 and tests[1].summary["made_up"] == 0
        assert tests[1].summary["recall"] == 1.0 and tests[0].summary["passed"] < 1.0
    # The shared sample opens without a login.
    page = text(client.get(f"/meetings/{by_title['Wholesale Call with Café Rosa'].id}"))
    link = page.split('id="share-url" type="text" value="')[1].split('"')[0]
    assert browser(app).get(link).status_code == 200


def test_samples_cost_nothing_and_leave_the_demos_three_runs(app, demo):
    client, workspace_id = demo
    meeting_id = demo_meetings(app, workspace_id)[0].id
    from stickyminutes.llm import FakeClaude
    app.extensions["claude"] = FakeClaude(practice=False)  # as if the owner has set an API key
    assert "The demo has 3 real summaries left today" in words(client.get(f"/meetings/{meeting_id}"))
    with app.app_context():
        from stickyminutes.models import UsageEntry
        assert db.session().scalar(select(func.count()).select_from(UsageEntry)) == 0


@pytest.mark.parametrize("spec", demo_samples.SAMPLES, ids=[s["key"] for s in demo_samples.SAMPLES])
def test_every_sample_quote_is_on_a_line(spec):
    """The samples' words must be in their transcripts (one, on purpose, isn't)."""
    lines = [(line.n, line.speaker, line.text) for line in transcripts.parse(spec["transcript"], spec["kind"]).lines]
    answer = demo_samples.build(spec["answer"], lines)
    texts = {n: t for n, _, t in lines}
    missing = [e["quote"] for section in ("key_points", "decisions", "action_items", "open_questions")
               for item in answer[section] for e in item["evidence"] if not demo_samples.checks_has(e["quote"], texts[e["line"]])]
    assert missing == (["I'll do the help text and FAQ tomorrow."] if spec.get("flag") else [])


@pytest.mark.parametrize("moment", [datetime(2026, 11, 22, 23, 30), datetime(2026, 11, 23, 1, 0), datetime(2027, 2, 28, 12, 0)])
def test_the_demo_works_on_any_day(app, moment):
    """Relative due dates are worked out from each sample's date, whatever day it is (UTC moments)."""
    with app.test_request_context():
        s = db.session()
        me = seed.build(s, moment)
        s.commit()
        meetings = s.scalars(select(Meeting).where(Meeting.workspace_id == me.workspace_id)).all()
        assert len(meetings) == 6 and sum(m.status == "needs_review" for m in meetings) == 1
