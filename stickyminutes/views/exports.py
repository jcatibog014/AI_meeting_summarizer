"""Export & Share: downloads, the print page, Copy as email, and the read-only share link."""
from urllib.parse import quote

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from .. import db, exports, meetings
from ..auth import login_required
from . import meetings as meeting_views
from .summaries import SECTIONS, items_of

bp = Blueprint("exports", __name__)
MAILTO_MAX = 1800  # longer mailto: links are cut off by some mail apps


def share_parts(s, meeting):
    token = exports.share_token(meeting)
    return {"share_url": url_for("exports.shared", token=token, _external=True) if token else None}


meeting_views.page_extras.append(share_parts)


def download(body, meeting, ending, mimetype):
    response = Response(body, mimetype=mimetype)
    name = exports.filename(meeting, ending)
    # filename* carries any letter safely; filename is a plain fallback for old browsers.
    plain = name.encode("ascii", "ignore").decode() or f"meeting.{ending}"
    response.headers["Content-Disposition"] = f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"
    return response


def loaded(meeting_id):
    s = db.session()
    meeting = meetings.load(s, g.workspace, meeting_id)
    if not meeting.overview:
        abort(409, "Summarize the meeting first: there are no notes to export yet.")
    return s, meeting, items_of(s, meeting)


@bp.get("/meetings/<int:meeting_id>/export.md")
@login_required
def markdown(meeting_id):
    _, meeting, items = loaded(meeting_id)
    return download(exports.markdown(meeting, items), meeting, "md", "text/markdown")


@bp.get("/meetings/<int:meeting_id>/export.docx")
@login_required
def word(meeting_id):
    _, meeting, items = loaded(meeting_id)
    return download(exports.docx_bytes(meeting, items), meeting, "docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@bp.get("/meetings/<int:meeting_id>/print")
@login_required
def printable(meeting_id):
    _, meeting, items = loaded(meeting_id)
    return render_template("minutes_print.html", meeting=meeting, items=exports.visible(items), sections=SECTIONS,
                           lines_label=exports.lines_label, due_words=exports.due_words)


@bp.get("/meetings/<int:meeting_id>/email")
@login_required
def email(meeting_id):
    _, meeting, items = loaded(meeting_id)
    body = exports.plain_text(meeting, items)
    mailto = f"mailto:?subject={quote('Minutes: ' + meeting.title)}&body={quote(body)}"
    return render_template("email.html", meeting=meeting, body=body, mailto=mailto if len(mailto) <= MAILTO_MAX else None)


@bp.post("/meetings/<int:meeting_id>/share")
@login_required
def share(meeting_id):
    s = db.session()
    meeting = meetings.load(s, g.workspace, meeting_id)
    on = request.form.get("on") == "1"
    if on and not meeting.overview:
        abort(409, "Summarize the meeting first: there is nothing to share yet.")
    exports.turn_sharing(meeting, on)
    s.commit()
    flash("The share link is on: anyone with it can read these minutes." if on else "The share link is off. It no longer works.")
    return redirect(url_for("meetings.show", meeting_id=meeting.id, _anchor="export"))


@bp.get("/s/<token>")
def shared(token):
    """The read-only minutes, for anyone with the link (no login)."""
    s = db.session()
    meeting = exports.meeting_for_token(s, token)
    if meeting is None:
        abort(404)
    response = Response(render_template("minutes_shared.html", meeting=meeting, items=exports.visible(items_of(s, meeting)),
                                        sections=SECTIONS, lines_label=exports.lines_label, due_words=exports.due_words))
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"  # the token never leaves in a Referer header
    return response
