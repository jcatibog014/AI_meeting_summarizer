"""Adding, showing, editing and deleting meetings, and keeping each workspace's meetings its own."""
import io

from sqlalchemy import func, select

from stickyminutes import db
from stickyminutes.models import Meeting, TranscriptLine

from .conftest import browser, make_owner, post, text, words
from .test_transcripts import PASTED, ZOOM_VTT


def add_meeting(client, **data):
    data = {"title": "Launch planning", "meeting_date": "2026-11-24", "transcript": PASTED, **data}
    response = post(client, "/meetings/new", data, content_type="multipart/form-data")
    assert response.status_code == 302, text(response)
    return int(response.headers["Location"].rsplit("/", 1)[-1])


def test_paste_a_transcript(app, owner):
    client, workspace_id = owner
    meeting_id = add_meeting(client)
    page = client.get(f"/meetings/{meeting_id}")
    assert "Launch planning" in text(page) and 'id="line-2"' in text(page)
    assert "Ben Cruz" in words(page) and "Not summarized" in words(page)
    with app.app_context():
        meeting = db.session().get(Meeting, meeting_id)
        assert meeting.workspace_id == workspace_id and meeting.line_count == 5
        assert meeting.speakers == ["Maria Santos", "Ben Cruz", "Ana Reyes"]


def test_upload_a_zoom_file(app, owner):
    client, _ = owner
    meeting_id = add_meeting(client, transcript="", title="",
                             file=(io.BytesIO(ZOOM_VTT.encode()), "GMT20261124-Recording.transcript.vtt"))
    with app.app_context():
        meeting = db.session().get(Meeting, meeting_id)
        assert meeting.source_kind == "vtt" and meeting.source_name.endswith(".vtt")
        assert meeting.title == "Meeting on 24 Nov 2026" and not meeting.title_from_user


def test_the_list_shows_the_meetings(owner):
    client, _ = owner
    add_meeting(client, title="Weekly sync")
    page = words(client.get("/meetings"))
    assert "Weekly sync" in page and "3 speakers" in page


def test_problems_come_back_on_the_form(owner):
    client, _ = owner
    response = post(client, "/meetings/new", {"title": "x", "meeting_date": "not a date", "transcript": ""})
    assert response.status_code == 400
    page = text(response)
    assert "Enter the meeting's date" in page and "Paste the transcript, or choose a file" in page


def test_edit_and_delete(app, owner):
    client, _ = owner
    meeting_id = add_meeting(client)
    post(client, f"/meetings/{meeting_id}/edit", {"title": "Launch (final)", "meeting_date": "2026-11-20"})
    with app.app_context():
        assert db.session().get(Meeting, meeting_id).title == "Launch (final)"
    post(client, f"/meetings/{meeting_id}/delete")
    with app.app_context():
        s = db.session()
        assert s.get(Meeting, meeting_id) is None
        assert s.scalar(select(func.count()).select_from(TranscriptLine)) == 0


def test_another_workspaces_meeting_is_not_found(app, owner, demo):
    client, _ = owner
    meeting_id = add_meeting(client)
    stranger, _ = demo
    for url in (f"/meetings/{meeting_id}",):
        assert stranger.get(url).status_code == 404
    assert post(stranger, f"/meetings/{meeting_id}/delete").status_code == 404
    assert post(stranger, f"/meetings/{meeting_id}/edit", {"title": "Mine now"}).status_code == 404


def test_a_second_owner_account_cant_see_it_either(app, owner):
    client, _ = owner
    meeting_id = add_meeting(client)
    other_id, _ = make_owner(app, name="Ben", email="ben@example.com")
    assert browser(app, other_id).get(f"/meetings/{meeting_id}").status_code == 404
