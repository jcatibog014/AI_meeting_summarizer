"""The Action Tracker: every action item, its tabs and filters, Mark done, and the calendar feed."""
from datetime import date, timedelta

from sqlalchemy import select

from stickyminutes import actions, db
from stickyminutes.models import Item, Workspace

from .conftest import browser, post, text, words
from .samples import GOOD, good
from .test_summarize import add_meeting, run_summary, use_claude


def two_meetings(app, client):
    """The sample meeting twice: 4 action items (2 Ben, 2 Ana), due 25 and 27 Nov 2026."""
    use_claude(app, GOOD)
    ids = [add_meeting(client, title=title) for title in ("Launch planning", "Launch follow-up")]
    for meeting_id in ids:
        run_summary(client, meeting_id)
    return ids


def action_ids(app):
    with app.app_context():
        return db.session().scalars(select(Item.id).where(Item.kind == "action").order_by(Item.id)).all()


def test_every_meetings_actions_in_one_list(app, owner):
    client, _ = owner
    two_meetings(app, client)
    page = words(client.get("/actions?tab=all"))
    assert text(client.get("/actions?tab=all")).count('class="action-task"') == 4
    assert "Launch follow-up" in page and "All 4" in page
    assert ">4</span>" in text(client.get("/meetings"))  # the menu's count


def test_owner_filter_and_unassigned(app, owner):
    client, _ = owner
    two_meetings(app, client)
    page = words(client.get("/actions?owner=Ana Reyes"))
    assert "Book the photographer" in page and "Send the final label files" not in page
    assert "No action items match." in words(client.get("/actions?owner=-"))


def test_mark_done_and_open_again(app, owner):
    client, _ = owner
    two_meetings(app, client)
    first = action_ids(app)[0]
    response = post(client, f"/items/{first}/done", {"done": "1", "next": "/actions?tab=open"})
    assert response.headers["Location"].endswith("/actions?tab=open")
    assert "Open 3" in words(client.get("/actions")) and "Done 1" in words(client.get("/actions"))
    post(client, f"/items/{first}/done", {"done": "0"})
    with app.app_context():
        item = db.session().get(Item, first)
        assert item.status == "open" and item.done_at is None


def test_done_only_goes_back_to_this_site(app, owner):
    client, _ = owner
    two_meetings(app, client)
    response = post(client, f"/items/{action_ids(app)[0]}/done", {"done": "1", "next": "https://evil.example"})
    assert "evil" not in response.headers["Location"]


def test_overdue_tab(app, owner):
    client, _ = owner
    use_claude(app, good(action_items=[dict(GOOD["action_items"][0], due_phrase=None, due_date="2026-11-24")]))
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    # Pretend the meeting happened long ago, so the item is late today.
    with app.app_context():
        s = db.session()
        item = s.scalar(select(Item).where(Item.kind == "action"))
        item.due_date = date.today() - timedelta(days=3)
        s.commit()
    page = words(client.get("/actions?tab=overdue"))
    assert "Overdue 1" in page and "Overdue:" in page


def test_rejected_items_are_left_out(app, owner):
    client, _ = owner
    two_meetings(app, client)
    post(client, f"/items/{action_ids(app)[0]}/review", {"decision": "reject"})
    assert "All 3" in words(client.get("/actions"))


def test_a_note_can_be_marked_done_on_its_meeting_page(app, owner):
    client, _ = owner
    meeting_id = two_meetings(app, client)[0]
    first = action_ids(app)[0]
    response = post(client, f"/items/{first}/done", {"done": "1"})
    assert response.headers["Location"].endswith(f"/meetings/{meeting_id}#item-{first}")
    assert "Reopen" in words(client.get(f"/meetings/{meeting_id}"))
    with app.app_context():
        point = db.session().scalar(select(Item.id).where(Item.kind == "point"))
    assert post(client, f"/items/{point}/done", {"done": "1"}).status_code == 400


def test_the_calendar_feed(app, owner):
    client, workspace_id = owner
    two_meetings(app, client)
    page = text(client.get("/actions"))
    link = page.split('id="feed-url" type="text" value="')[1].split('"')[0]
    response = browser(app).get(link)  # a calendar app: not logged in
    assert response.status_code == 200 and response.mimetype == "text/calendar"
    body = response.get_data(as_text=True)
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.count("BEGIN:VEVENT") == 4
    assert "DTSTART;VALUE=DATE:20261127" in body and "SUMMARY:Send the final label files to the printer (Ben Cruz)" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))


def test_a_new_feed_link_ends_the_old_one(app, owner):
    client, workspace_id = owner
    with app.app_context():
        old = actions.feed_token(db.session().get(Workspace, workspace_id))
    post(client, "/actions/calendar/new-link")
    assert browser(app).get(f"/actions/calendar/{old}.ics").status_code == 404
    assert browser(app).get("/actions/calendar/1.1.forged.ics").status_code == 404


def test_ics_text_is_escaped_and_folded():
    assert actions.ics_text("a, b; c\\d\ne") == "a\\, b\\; c\\\\d\\ne"
    folded = actions.fold("SUMMARY:" + "café " * 30)
    assert all(len(piece.encode()) <= 75 for piece in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == "SUMMARY:" + "café " * 30


def test_another_workspace_cant_mark_it_done(app, owner, demo):
    client, _ = owner
    two_meetings(app, client)
    stranger, _ = demo
    assert post(stranger, f"/items/{action_ids(app)[0]}/done", {"done": "1"}).status_code == 404
