"""The Quality Lab: runs, problems, and the test set."""
import json

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select

from .. import db, evals, lab, llm, meetings, pricing, summarize
from ..auth import login_required, not_for_demo
from ..dates import utcnow
from ..models import EvalRun, Run

bp = Blueprint("lab", __name__)
TABS = (("lab.index", "Runs"), ("lab.problems", "Problems"), ("lab.tests", "Test Set"))


def tab_data():
    return {"tabs": TABS, "here": request.endpoint}


@bp.get("/lab")
@login_required
def index():
    s = db.session()
    return render_template("lab_runs.html", runs=lab.recent_runs(s, g.workspace), totals=lab.totals(s, g.workspace),
                           problems=lab.problem_counts(s, g.workspace), **tab_data())


@bp.get("/lab/runs/<int:run_id>")
@login_required
def run(run_id):
    s = db.session()
    found = s.get(Run, run_id)
    if found is None:
        abort(404)
    meeting = meetings.load(s, g.workspace, found.meeting_id)
    try:
        pretty = json.dumps(json.loads(found.raw_output), indent=2, ensure_ascii=False) if found.raw_output else None
    except ValueError:
        pretty = found.raw_output  # broken JSON: show it as it came
    by_attempt = {}
    for issue in found.issues:
        by_attempt.setdefault(issue.attempt, []).append(issue)
    return render_template("lab_run.html", run=found, meeting=meeting, raw=pretty, by_attempt=by_attempt,
                           layers={key: name for key, name, _ in lab.LAYERS}, model=pricing.model(found.model), **tab_data())


@bp.get("/lab/problems")
@login_required
def problems():
    s = db.session()
    return render_template("lab_problems.html", groups=lab.problem_groups(s, g.workspace), layers=lab.LAYERS, **tab_data())


@bp.get("/lab/tests")
@login_required
def tests():
    s = db.session()
    evals.expire_stale(s, g.workspace, utcnow())
    s.commit()
    runs = s.scalars(select(EvalRun).where(EvalRun.workspace_id == g.workspace.id).order_by(EvalRun.id.desc())).all()
    app = current_app._get_current_object()
    return render_template("lab_tests.html", cases=evals.CASES, runs=runs, versions=summarize.prompt_versions(),
                           models=pricing.MODELS.values(), practice=llm.is_practice(app),
                           running=any(r.status in ("queued", "running") for r in runs), **tab_data())


@bp.post("/lab/tests")
@login_required
def start_tests():
    app = current_app._get_current_object()
    if not llm.is_practice(app):
        not_for_demo("The demo can't run the test set: it would cost the owner six real summaries.")
    s = db.session()
    try:
        run = evals.start(s, app, g.workspace, request.form.get("prompt_version", ""), request.form.get("model", ""), utcnow())
    except summarize.CantStart as problem:
        flash(str(problem), "error")
        return redirect(url_for("lab.tests"))
    s.commit()
    evals.launch(app, run.id)
    return redirect(url_for("lab.test_run", run_id=run.id))


def load_eval(s, run_id):
    found = s.get(EvalRun, run_id)
    if found is None or found.workspace_id != g.workspace.id:
        abort(404)
    return found


@bp.get("/lab/tests/<int:run_id>")
@login_required
def test_run(run_id):
    s = db.session()
    found = load_eval(s, run_id)
    by_case = {result["case"]: result for result in found.results or []}
    return render_template("lab_test_run.html", run=found, cases=evals.CASES, by_case=by_case,
                           model=pricing.model(found.model), **tab_data())


@bp.get("/lab/tests/<int:run_id>/status.json")
@login_required
def test_status(run_id):
    s = db.session()
    found = load_eval(s, run_id)
    return jsonify(status=found.status, done=len(found.results or []), cases=len(evals.CASES),
                   finished=found.status not in ("queued", "running"))
