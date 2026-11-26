"""The meetings board: every meeting in the workspace, newest first."""
from flask import Blueprint, render_template

from ..auth import login_required

bp = Blueprint("meetings", __name__)


@bp.get("/meetings")
@login_required
def index():
    return render_template("meetings.html", meetings=[])
