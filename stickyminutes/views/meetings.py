"""The meetings board, adding a meeting, and a meeting's own page."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .. import db, meetings, transcripts
from ..auth import login_required
from ..dates import local_today

bp = Blueprint("meetings", __name__)
# A meeting page's extra parts that later stages add: function(s, meeting) -> dict
page_extras = []
# A meeting's status as (words, pill style).
STATUS = {
    "new": ("Not summarized", ""),
    "queued": ("Waiting to start", "pill-accent"),
    "running": ("Summarizing", "pill-accent"),
    "ready": ("Summarized", "pill-ok"),
    "needs_review": ("Needs review", "pill-warn"),
    "failed": ("Didn't finish", "pill-danger"),
}


@bp.app_template_global()
def meeting_status(meeting):
    return STATUS.get(meeting.status, STATUS["new"])


@bp.get("/meetings")
@login_required
def index():
    s = db.session()
    return render_template("meetings.html", meetings=meetings.listing(s, g.workspace))


@bp.route("/meetings/new", methods=["GET", "POST"])
@login_required
def new():
    today = local_today(g.workspace.time_zone)
    errors, form = {}, request.form
    if request.method == "POST":
        s = db.session()
        try:
            title = meetings.clean_title(form.get("title"))
        except meetings.Invalid as problem:
            errors["title"] = str(problem)
        try:
            day = meetings.parse_day(form.get("meeting_date"), today)
        except meetings.Invalid as problem:
            errors["meeting_date"] = str(problem)
        upload = request.files.get("file")
        parsed, source_name = None, None
        try:
            if upload and upload.filename:
                source_name = upload.filename
                parsed = transcripts.read_upload(upload.filename, upload.read(transcripts.MAX_BYTES + 1))
            elif form.get("transcript", "").strip():
                parsed = transcripts.parse(form["transcript"], "paste")
            else:
                errors["transcript"] = "Paste the transcript, or choose a file to upload."
        except transcripts.TranscriptProblem as problem:
            errors["transcript"] = str(problem)
        if not errors:
            try:
                meeting = meetings.create(s, g.workspace, parsed, title, day, source_name)
            except meetings.Invalid as problem:
                errors["transcript"] = str(problem)
            else:
                s.commit()
                who = len(meeting.speakers)
                flash(f"Saved {meeting.line_count:,} lines" + (f" from {who} speaker{'s' if who != 1 else ''}." if who else "."))
                return redirect(url_for("meetings.show", meeting_id=meeting.id))
    return render_template("meeting_new.html", errors=errors, form=form, today=today,
                           kinds=transcripts.KINDS), 400 if errors else 200


@bp.get("/meetings/<int:meeting_id>")
@login_required
def show(meeting_id):
    s = db.session()
    meeting = meetings.load(s, g.workspace, meeting_id)
    data = {}
    for extra in page_extras:
        data.update(extra(s, meeting))
    return render_template("meeting.html", meeting=meeting, kinds=transcripts.KINDS,
                           estimate=transcripts.estimate_tokens(sum(len(line.text) for line in meeting.lines)), **data)


@bp.post("/meetings/<int:meeting_id>/edit")
@login_required
def edit(meeting_id):
    s = db.session()
    meeting = meetings.load(s, g.workspace, meeting_id)
    try:
        title = meetings.clean_title(request.form.get("title"))
        day = meetings.parse_day(request.form.get("meeting_date"), local_today(g.workspace.time_zone))
    except meetings.Invalid as problem:
        flash(str(problem), "error")
        return redirect(url_for("meetings.show", meeting_id=meeting.id))
    if title:
        meeting.title, meeting.title_from_user = title, True
    meeting.meeting_date = day
    s.commit()
    flash("The meeting's details are saved.")
    return redirect(url_for("meetings.show", meeting_id=meeting.id))


@bp.post("/meetings/<int:meeting_id>/delete")
@login_required
def delete(meeting_id):
    s = db.session()
    meeting = meetings.load(s, g.workspace, meeting_id)
    title = meeting.title
    s.delete(meeting)
    s.commit()
    flash(f"Deleted “{title}”.")
    return redirect(url_for("meetings.index"))
