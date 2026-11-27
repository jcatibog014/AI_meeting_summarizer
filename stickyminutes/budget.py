"""The spending guard: every real summary costs the owner money, so two limits stand in front of it.

1. **The site's daily cap** (`DAILY_CAP_CENTS`, $1 at first): the sum of every
   Claude call today (UTC), from the `usage_ledger`, owner and demos alike.
   A new summary must fit under it, with its estimate (from count_tokens).
2. **A demo visitor's runs** (`DEMO_RUNS_PER_DAY`, 3): counted in limits.py
   under a key for this workspace and this day. It counts STARTS, so deleting
   a meeting doesn't give a run back.

Practice mode (no API key) costs nothing, so neither limit applies to it.
A summary already running may go a little over the cap with its repair turns:
it is never cut off halfway.
"""
from datetime import timedelta

from sqlalchemy import func, select

from . import limits, llm
from .models import RateLimit, UsageEntry


class OverBudget(Exception):
    """A summary can't start today. The message says why, in plain words."""


def cap_micros(app):
    return app.config["DAILY_CAP_CENTS"] * 10_000


def spent_today(s, moment):
    return s.scalar(select(func.coalesce(func.sum(UsageEntry.cost_micros), 0))
                    .where(UsageEntry.day == moment.date())) or 0


def _demo_key(workspace, moment):
    return f"demo-runs:{workspace.id}:{moment.date().isoformat()}"


def demo_runs_used(s, workspace, moment):
    row = s.get(RateLimit, _demo_key(workspace, moment))
    return row.count if row is not None and row.window_start + timedelta(days=1) > moment else 0


def demo_runs_left(s, app, workspace, moment):
    return max(0, app.config["DEMO_RUNS_PER_DAY"] - demo_runs_used(s, workspace, moment))


def check(s, app, workspace, moment, estimate_micros=0):
    """Raise OverBudget if this workspace may not start a real summary now. Counts a demo's run.
    The caller commits."""
    if llm.is_practice(app):
        return
    cap = cap_micros(app)
    if spent_today(s, moment) + estimate_micros > cap:
        raise OverBudget("Sticky Minutes has reached today's spending limit for Claude. "
                         "Summaries start again tomorrow (the day changes at 8 AM in Manila).")
    if workspace.is_demo:
        allowed = app.config["DEMO_RUNS_PER_DAY"]
        if not limits.hit(s, _demo_key(workspace, moment), allowed, 86400, moment):
            raise OverBudget(f"The demo can run {allowed} real summaries a day, and you've used them. "
                             "The sample meetings are already summarized.")


def record(s, workspace, run, cost_micros, moment):
    """Write one call's cost to the ledger (practice runs cost nothing and write nothing)."""
    if run.practice or getattr(run, "sample", False):
        return
    s.add(UsageEntry(workspace_id=workspace.id, run_id=run.id, day=moment.date(), is_demo=workspace.is_demo,
                     cost_micros=cost_micros, created_at=moment))
