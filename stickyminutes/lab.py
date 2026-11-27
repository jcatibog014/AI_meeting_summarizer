"""The Quality Lab's numbers: how the summaries went, what the checks caught, and what it cost.

Everything comes from `runs` and `run_issues` (summarize.py writes them),
for the meetings in this workspace. A problem's path ("action_items.2.owner")
is grouped with the same path in other items ("action_items.#.owner"), so
the Problems page shows WHICH kind of mistake Claude makes, and how often a
repair turn fixed it.
"""
import re

from sqlalchemy import case, func, select

from .models import Meeting, Run, RunIssue

FINISHED = ("done", "needs_review", "failed")
LAYERS = (("schema", "Shape (the API's layer)", "The answer wasn't JSON of the right shape."),
          ("rules", "Rules (Pydantic)", "A length, number or sentence rule was broken."),
          ("grounding", "Grounding (the transcript)", "A quote, line, owner or date didn't match the meeting."))


def runs_query(workspace):
    return select(Run).join(Meeting, Meeting.id == Run.meeting_id).where(Meeting.workspace_id == workspace.id)


def recent_runs(s, workspace, limit=50):
    return s.scalars(runs_query(workspace).order_by(Run.id.desc()).limit(limit)).all()


def problem_counts(s, workspace):
    """{run id: number of problems found} for the runs table."""
    rows = s.execute(select(RunIssue.run_id, func.count()).join(Run, Run.id == RunIssue.run_id)
                     .join(Meeting, Meeting.id == Run.meeting_id).where(Meeting.workspace_id == workspace.id)
                     .group_by(RunIssue.run_id)).all()
    return dict(rows)


def totals(s, workspace):
    finished = runs_query(workspace).where(Run.status.in_(FINISHED)).subquery()
    row = s.execute(select(
        func.count(), func.coalesce(func.avg(finished.c.attempts), 0),
        func.coalesce(func.sum(case((finished.c.attempts == 1, 1), else_=0)), 0),
        func.coalesce(func.sum(finished.c.cost_micros), 0),
        func.coalesce(func.sum(case((finished.c.status == "failed", 1), else_=0)), 0),
    ).select_from(finished)).one()
    count, attempts, first, cost, failed = row
    with_issues = set(s.scalars(select(RunIssue.run_id).join(Run, Run.id == RunIssue.run_id)
                                .join(Meeting, Meeting.id == Run.meeting_id)
                                .where(Meeting.workspace_id == workspace.id, RunIssue.attempt == 1)).all())
    first_ids = s.scalars(runs_query(workspace).where(Run.status.in_(FINISHED), Run.attempts == 1)
                          .with_only_columns(Run.id)).all()
    right_first = sum(1 for run_id in first_ids if run_id not in with_issues)
    issues = s.execute(select(func.count(), func.coalesce(func.sum(case((RunIssue.fixed.is_(True), 1), else_=0)), 0))
                       .join(Run, Run.id == RunIssue.run_id).join(Meeting, Meeting.id == Run.meeting_id)
                       .where(Meeting.workspace_id == workspace.id)).one()
    return {"runs": count, "attempts": float(attempts or 0), "right_first": right_first, "failed": failed,
            "cost": int(cost or 0), "problems": issues[0], "fixed": int(issues[1] or 0)}


def pattern(path):
    """'action_items.2.evidence.0' -> 'action_items.#.evidence.#'."""
    return re.sub(r"\.\d+", ".#", path) or "(the whole answer)"


def problem_groups(s, workspace):
    """[(layer, [(pattern, count, fixed, latest message), ...]), ...], most common first."""
    rows = s.execute(select(RunIssue.layer, RunIssue.path, RunIssue.message, RunIssue.fixed)
                     .join(Run, Run.id == RunIssue.run_id).join(Meeting, Meeting.id == Run.meeting_id)
                     .where(Meeting.workspace_id == workspace.id).order_by(RunIssue.id.desc())).all()
    groups = {}
    for layer, path, message, fixed in rows:
        entry = groups.setdefault(layer, {}).setdefault(pattern(path), [0, 0, message])
        entry[0] += 1
        entry[1] += 1 if fixed else 0
    out = []
    for layer, _, _ in LAYERS:
        found = groups.get(layer, {})
        out.append((layer, sorted(((key, n, fixed, example) for key, (n, fixed, example) in found.items()),
                                  key=lambda row: (-row[1], row[0]))))
    return out
