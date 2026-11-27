"""Export & Share: Markdown, Word, print, email, and the read-only share link."""
import io

from docx import Document
from sqlalchemy import select

from stickyminutes import db, exports
from stickyminutes.models import Item, Meeting

from .conftest import browser, post, text, words
from .samples import GOOD, good
from .test_summarize import add_meeting, run_summary, use_claude


def summarized(app, client, answer=GOOD):
    use_claude(app, answer)
    meeting_id = add_meeting(client)
    run_summary(client, meeting_id)
    return meeting_id


def test_markdown_download(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    response = client.get(f"/meetings/{meeting_id}/export.md")
    assert response.mimetype == "text/markdown"
    assert 'filename="2026-11-24 Launch planning.md"' in response.headers["Content-Disposition"]
    body = response.get_data(as_text=True)
    assert body.startswith("# Launch planning\n")
    assert "## Decisions" in body and "- The launch is on December 15. [line 5]" in body
    assert "- [ ] Send the final label files to the printer (Ben Cruz, due Fri 27 Nov 2026, high priority) [line 2]" in body


def test_markdown_marks_in_notes_are_escaped():
    assert exports.md_escape("Use *bold* and # tags") == "Use \\*bold\\* and \\# tags"


def test_word_download(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    response = client.get(f"/meetings/{meeting_id}/export.docx")
    assert response.mimetype.endswith("wordprocessingml.document")
    document = Document(io.BytesIO(response.data))
    paragraphs = [p.text for p in document.paragraphs]
    assert paragraphs[0] == "Launch planning" and "Action Items" in paragraphs
    assert any(p.startswith("Book the photographer for the product photos (Ana Reyes, due") for p in paragraphs)


def test_rejected_notes_are_left_out_and_flagged_ones_marked(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client, good(key_points=[]))
    with app.app_context():
        s = db.session()
        decision = s.scalar(select(Item).where(Item.meeting_id == meeting_id, Item.kind == "decision", Item.position == 0))
        decision.review = "rejected"
        question = s.scalar(select(Item).where(Item.meeting_id == meeting_id, Item.kind == "question"))
        question.flag = "the quote isn't on line 8"
        s.commit()
    body = client.get(f"/meetings/{meeting_id}/export.md").get_data(as_text=True)
    assert "450 pesos" not in body and "Who writes the newsletter? (check this)" in body
    assert "## Key Points\n\n_None._" in body


def test_print_page_and_email(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    page = words(client.get(f"/meetings/{meeting_id}/print"))
    assert "Print or save as PDF" in page and "Ben Cruz, due Fri 27 Nov 2026, high priority" in page
    email = text(client.get(f"/meetings/{meeting_id}/email"))
    assert "DECISIONS\n- The price stays at 450 pesos." in email
    assert "mailto:?subject=Minutes%3A%20Launch%20planning" in email


def test_nothing_to_export_before_a_summary(owner):
    client, _ = owner
    meeting_id = add_meeting(client)
    assert client.get(f"/meetings/{meeting_id}/export.md").status_code == 409
    assert post(client, f"/meetings/{meeting_id}/share", {"on": "1"}).status_code == 409


def share_link(client, meeting_id):
    page = text(client.get(f"/meetings/{meeting_id}"))
    return page.split('id="share-url" type="text" value="')[1].split('"')[0]


def test_the_share_link(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    assert "Make a link" in words(client.get(f"/meetings/{meeting_id}"))
    post(client, f"/meetings/{meeting_id}/share", {"on": "1"})
    link = share_link(client, meeting_id)
    response = browser(app).get(link)  # someone without a login
    assert response.status_code == 200 and response.headers["X-Robots-Tag"] == "noindex"
    page = words(response)
    assert "Shared minutes, read only" in page and "The launch is on December 15." in page
    assert "Ben Cruz: Then we'll go with" not in page  # the transcript isn't shared
    assert "Accept" not in page and "Run again" not in page


def test_turning_it_off_and_on_never_brings_an_old_link_back(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    post(client, f"/meetings/{meeting_id}/share", {"on": "1"})
    first = share_link(client, meeting_id)
    post(client, f"/meetings/{meeting_id}/share", {"on": "0"})
    assert browser(app).get(first).status_code == 404
    post(client, f"/meetings/{meeting_id}/share", {"on": "1"})
    assert browser(app).get(first).status_code == 404
    assert browser(app).get(share_link(client, meeting_id)).status_code == 200


def test_a_forged_share_token_is_refused(app, owner):
    client, _ = owner
    meeting_id = summarized(app, client)
    post(client, f"/meetings/{meeting_id}/share", {"on": "1"})
    with app.app_context():
        nonce = db.session().get(Meeting, meeting_id).share_nonce
    assert browser(app).get(f"/s/{meeting_id}.{nonce}.notTheRealSignature").status_code == 404
    assert browser(app).get(f"/s/{meeting_id + 1}.{nonce}.x").status_code == 404


def test_another_workspace_cant_export_or_share(app, owner, demo):
    client, _ = owner
    meeting_id = summarized(app, client)
    stranger, _ = demo
    for url in ("export.md", "export.docx", "print", "email"):
        assert stranger.get(f"/meetings/{meeting_id}/{url}").status_code == 404, url
    assert post(stranger, f"/meetings/{meeting_id}/share", {"on": "1"}).status_code == 404
