"""Summarize a meeting, watch it run, and the notes on the meeting's page."""
from flask import Blueprint, current_app, flash, g, jsonify, redirect, url_for
from sqlalchemy import select

from .. import budget, db, llm, meetings, pricing, summarize, transcripts
from ..auth import login_required
from ..dates import utcnow
from ..models import Item
from . import meetings as meeting_views

bp = Blueprint("summaries", __name__)
SECTIONS = (("point", "Key Points", "green"), ("decision", "Decisions", "blue"),
            ("action", "Action Items", "yellow"), ("question", "Open Questions", "pink"))


def rough_estimate(workspace, meeting):
    """The cost shown on the button, from the transcript's length (no API call on every page view).
    The real count (count_tokens) is taken when the summary starts."""
    chars = sum(len(line.text) for line in meeting.lines) + len(summarize.prompt()) + 400
    return pricing.cost_micros(workspace.model, input_tokens=transcripts.estimate_tokens(chars),
                               output_tokens=summarize.OUTPUT_GUESS)


def items_of(s, meeting):
    rows = s.scalars(select(Item).where(Item.meeting_id == meeting.id).order_by(Item.kind, Item.position)).all()
    grouped = {kind: [] for kind, _, _ in SECTIONS}
    for item in rows:
        grouped.setdefault(item.kind, []).append(item)
    return grouped


def page_parts(s, meeting):
    moment = utcnow()
    if summarize.expire_stale(s, meeting, moment):
        s.commit()
    app = current_app._get_current_object()
    items = items_of(s, meeting)
    return {
        "run": summarize.latest_run(s, meeting),
        "items": items,
        "flagged_count": sum(1 for group in items.values() for item in group if item.flag),
        "sections": SECTIONS,
        "practice": llm.is_practice(app),
        "runs_left": budget.demo_runs_left(s, app, g.workspace, moment) if g.workspace.is_demo else None,
        "estimate_micros": rough_estimate(g.workspace, meeting),
        "model_label": pricing.model(g.workspace.model).label,
    }


meeting_views.page_extras.append(page_parts)


@bp.post("/meetings/<int:meeting_id>/summarize")
@login_required
def start(meeting_id):
    s = db.session()
    meeting = meetings.load(s, g.workspace, meeting_id)
    app = current_app._get_current_object()
    moment = utcnow()
    summarize.expire_stale(s, meeting, moment)
    try:
        run = summarize.start(s, app, g.workspace, meeting, moment)
    except summarize.CantStart as problem:
        s.commit()  # a refused demo run isn't counted, but an expired one is cleared
        flash(str(problem), "error")
        return redirect(url_for("meetings.show", meeting_id=meeting.id))
    s.commit()
    summarize.launch(app, run.id)
    return redirect(url_for("meetings.show", meeting_id=meeting.id))


@bp.get("/meetings/<int:meeting_id>/status.json")
@login_required
def status(meeting_id):
    """The meeting page asks this every 2 seconds while a summary runs."""
    s = db.session()
    meeting = meetings.load(s, g.workspace, meeting_id)
    if summarize.expire_stale(s, meeting, utcnow()):
        s.commit()
    run = summarize.latest_run(s, meeting)
    words, _ = meeting_views.STATUS.get(meeting.status, meeting_views.STATUS["new"])
    return jsonify(status=meeting.status, words=words, attempts=run.attempts if run else 0,
                   finished=meeting.status not in ("queued", "running"))

