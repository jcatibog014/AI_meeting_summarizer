"""Try Demo: one click, and the visitor has their own sample workspace for 24 hours."""
from flask import Blueprint, current_app, flash, g, redirect, url_for

from .. import db, limits, seed
from ..auth import log_in
from ..dates import utcnow

bp = Blueprint("demo", __name__)
DEMOS_PER_IP = 10  # an hour


@bp.post("/demo")
def start():
    """A fresh sandbox for this visitor alone. Nobody sees anyone else's demo."""
    if g.user is not None and g.user.is_demo:
        return redirect(url_for("meetings.index"))  # this browser already has one
    s = db.session()
    moment = utcnow()
    seed.purge(s, moment)
    # Not while developing on your own PC (--debug): screenshots start many demos in a row.
    if not current_app.debug and not limits.hit(s, f"demo-ip:{limits.client_ip()}", DEMOS_PER_IP, 3600, moment):
        s.commit()
        flash("That's a lot of demos from your network. Please try again in an hour.", "error")
        return redirect(url_for("auth.login"))
    if seed.count(s) >= seed.MAX_DEMOS:
        s.commit()
        flash("The demo is very busy right now. Please try again in a little while.", "error")
        return redirect(url_for("auth.login"))
    me = seed.build(s, moment)
    s.commit()
    log_in(me)
    # Shown once, as a toast (_toasts.html); the small Demo tag in the menu stays.
    flash(f"You are {seed.DEMO_NAME}, who runs the meetings at {seed.DEMO_COMPANY}. The sample meetings are "
          "already summarized, and you can summarize a few of your own each day. Deleted after 24 hours.", "demo")
    return redirect(url_for("meetings.index"))
