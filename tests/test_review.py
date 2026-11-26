"""Review & Proof: accepting, rejecting and editing notes, and the proof shown with them."""
from sqlalchemy import select

from stickyminutes import db
from stickyminutes.models import Item

from .conftest import post, text, words
from .samples import GOOD
from .test_summarize import add_meeting, run_summary, use_claude


def summarized(app, client):
    use_claude(app, GOOD)
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    return meeting_id


def item_of(app, meeting_id, kind, position=0):
    with app.app_context():
        s = db.session()
        item = s.scalar(select(Item).where(Item.meeting_id == meeting_id, Item.kind == kind, Item.position == position))
        s.expunge(item)
        return item


def test_the_notes_show_their_proof_and_buttons(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    page = words(client.get(f"/meetings/{meeting_id}"))
    assert "0 of 6 notes checked" in page
    assert "Proof" in page and "“We agreed last week on 450 pesos, so let's keep it.” line 4" in page
    assert page.count("Accept") >= 6 and "Reject" in page
    assert text(client.get(f"/meetings/{meeting_id}")).count('aria-label="Edit"') == 6


def test_accept_reject_and_undo(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    decision = item_of(app, meeting_id, "decision")
    response = post(client, f"/items/{decision.id}/review", {"decision": "accept"})
    assert response.status_code == 302 and response.headers["Location"].endswith(f"#item-{decision.id}")
    assert item_of(app, meeting_id, "decision").review == "accepted"
    post(client, f"/items/{decision.id}/review", {"decision": "reject"})
    assert item_of(app, meeting_id, "decision").review == "rejected"
    page = words(client.get(f"/meetings/{meeting_id}"))
    assert "1 of 6 notes checked" in page and "Rejected" in page
    post(client, f"/items/{decision.id}/review", {"decision": "undo"})
    assert item_of(app, meeting_id, "decision").review == "unreviewed"
    assert post(client, f"/items/{decision.id}/review", {"decision": "maybe"}).status_code == 400


def test_edit_an_action_item(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    action = item_of(app, meeting_id, "action")
    page = text(client.get(f"/items/{action.id}/edit"))
    assert "Edit Action Item" in page and "Said: “by Friday”" in page
    assert "Line 2, Ben Cruz:" in page  # the proof beside the form
    response = post(client, f"/items/{action.id}/edit", {"text": "Send the label files to the printer",
                                                         "owner": "Ana Reyes", "due_date": "2026-12-01", "priority": "low"})
    assert response.status_code == 302
    edited = item_of(app, meeting_id, "action")
    assert (edited.owner, edited.due_date.isoformat(), edited.priority) == ("Ana Reyes", "2026-12-01", "low")
    assert edited.edited and edited.review == "accepted" and edited.due_phrase is None
    assert "Edited" in words(client.get(f"/meetings/{meeting_id}"))


def test_edit_a_decisions_reason(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    decision = item_of(app, meeting_id, "decision", 1)
    post(client, f"/items/{decision.id}/edit", {"text": "Launch on December 15", "detail": "The roaster delivers on the 10th"})
    assert item_of(app, meeting_id, "decision", 1).detail == "The roaster delivers on the 10th"


def test_edit_problems_come_back_on_the_form(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    action = item_of(app, meeting_id, "action")
    response = post(client, f"/items/{action.id}/edit", {"text": " ", "owner": "Nobody", "due_date": "soon", "priority": "urgent"})
    assert response.status_code == 400
    page = text(response)
    for message in ("Write the note.", "Choose someone from the list.", "Enter a date like", "Choose a priority."):
        assert message in page


def test_another_workspace_cant_touch_the_notes(app, owner, demo):
    client, _ = owner
    meeting_id = summarized(app, client)
    action = item_of(app, meeting_id, "action")
    stranger, _ = demo
    assert stranger.get(f"/items/{action.id}/edit").status_code == 404
    assert post(stranger, f"/items/{action.id}/review", {"decision": "reject"}).status_code == 404
    assert post(stranger, f"/items/{action.id}/edit", {"text": "Mine"}).status_code == 404
