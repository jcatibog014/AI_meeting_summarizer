"""The Action Items page, Mark done, and the calendar feed."""
from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from .. import actions, db
from ..auth import login_required, safe_next
from ..dates import local_today, utcnow
from .review import load_item

bp = Blueprint("actions", __name__)


@bp.app_template_global()
def open_actions(workspace):
    """The number beside "Action Items" in the menu."""
    return actions.open_count(db.session(), workspace) if workspace is not None else 0


@bp.get("/actions")
@login_required
def index():
    s = db.session()
    tab = request.args.get("tab", "open")
    if tab not in dict(actions.TABS):
        tab = "open"
    owner = request.args.get("owner") or None
    rows = actions.listing(s, g.workspace, tab, owner)
    feed_url = url_for("actions.feed", token=actions.feed_token(g.workspace), _external=True)
    return render_template("actions.html", rows=rows, tab=tab, owner=owner, tabs=actions.TABS,
                           counts=actions.counts(s, g.workspace), owners=actions.owners(s, g.workspace),
                           today=local_today(g.workspace.time_zone), feed_url=feed_url)


@bp.post("/items/<int:item_id>/done")
@login_required
def done(item_id):
    s = db.session()
    item, meeting = load_item(s, item_id)
    if item.kind != "action":
        abort(400, "Only action items can be done.")
    finished = request.form.get("done") == "1"
    actions.set_done(item, finished, utcnow())
    s.commit()
    flash(("Done: " if finished else "Open again: ") + item.text)
    return redirect(safe_next(request.form.get("next"), url_for("meetings.show", meeting_id=meeting.id, _anchor=f"item-{item.id}")))


@bp.post("/actions/calendar/new-link")
@login_required
def new_feed_link():
    s = db.session()
    g.workspace.feed_nonce += 1
    s.commit()
    flash("Here is a new calendar link. The old one has stopped working.")
    return redirect(url_for("actions.index", _anchor="calendar"))


@bp.get("/actions/calendar/<token>.ics")
def feed(token):
    """For calendar apps: no login, the signed token is the proof."""
    s = db.session()
    workspace = actions.workspace_for_token(s, token)
    if workspace is None:
        abort(404)
    body = actions.calendar(s, workspace, current_app.config["BASE_URL"])
    response = Response(body, mimetype="text/calendar")
    response.headers["Content-Disposition"] = 'inline; filename="action-items.ics"'
    response.headers["Cache-Control"] = "private, max-age=900"
    return response
