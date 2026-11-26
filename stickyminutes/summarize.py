"""Summarizing a meeting: one Run, from "queued" to "done", with checks and repair turns.

    start()   checks the budget, makes a Run (queued). The caller commits, then calls launch().
    launch()  runs work() in a background thread (a summary takes 20-90 seconds;
              the page asks /status.json every 2 seconds and reloads when it's done).
    work()    the loop:

        ask Claude  ->  check the answer  ->  all good?  ->  save the notes
                             |  problems
                             v
                   send the problems back ("fix these, return the whole JSON")
                   and ask again, at most MAX_ATTEMPTS times in all

The checks are the three layers (schema.py explains them): the JSON's shape,
Pydantic's rules, and grounding in the transcript (checks.py). Every problem
found is saved as a RunIssue, with the attempt that had it, and marked
`fixed` when a later attempt no longer has it: the Quality Lab shows them.

A repair turn sends Claude's previous answer back UNCHANGED (its content
blocks, thinking included) and adds the problems as a new user message. The
transcript block is marked for the prompt cache, so the second and third
attempts read it back at a fraction of the price.

When the attempts run out, the best answer that has the right shape is
saved anyway, with each doubtful note FLAGGED (Needs review). A note is
never dropped quietly: the reader decides.
"""
import logging
import threading
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, select

from . import budget, checks, db, llm, meetings, pricing, schema, transcripts
from .dates import utcnow
from .models import Item, Meeting, Run, RunIssue, Workspace

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).parent / "prompts"
PROMPT_VERSION = "v1"
MAX_ATTEMPTS = 3            # the first answer and up to 2 repairs
OUTPUT_GUESS = 3_000        # output tokens we expect, for the estimate (thinking included)
STALE_AFTER = timedelta(minutes=10)
KINDS = (("key_points", "point"), ("decisions", "decision"), ("action_items", "action"), ("open_questions", "question"))
# Layer 3 (checks.py): function(notes, lines, meeting, found) -> [schema.Problem].
# `found` is filled with (section, item, quote) -> True/False: was that quote in the transcript?
reviewers = [checks.review]


class CantStart(Exception):
    """A summary can't start. The message says why."""


@lru_cache(maxsize=8)
def prompt(version=PROMPT_VERSION):
    path = PROMPTS / f"{version}.md"
    if not path.is_file() or "/" in version or "\\" in version:
        raise CantStart(f"There is no prompt called {version}.")
    return path.read_text(encoding="utf-8").strip()


def prompt_versions():
    return sorted(path.stem for path in PROMPTS.glob("v*.md"))


def build_messages(meeting, lines):
    """The first user message: the transcript (cached) and then the facts about this meeting."""
    transcript = f"<transcript>\n{transcripts.numbered(lines)}\n</transcript>"
    title = meeting.title if meeting.title_from_user else "(no title yet: name it)"
    about = "\n".join([
        f"Meeting: {title}",
        f"Date: {meeting.meeting_date.isoformat()} ({meeting.meeting_date.strftime('%A')})",
        f"Speakers: {', '.join(meeting.speakers) or 'not labelled'}",
        "",
        "Write the notes for this meeting.",
    ])
    return [{"role": "user", "content": [
        {"type": "text", "text": transcript, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": about},
    ]}]


def repair_message(problems):
    listed = "\n".join(f"- {problem}" for problem in problems[:40])
    more = f"\n- ...and {len(problems) - 40} more of the same kind" if len(problems) > 40 else ""
    return ("Your answer had these problems:\n" + listed + more + "\n\n"
            "Fix them and return the whole answer again, as JSON in the same shape. Keep everything that was right. "
            "If a quote can't be found, copy the exact words from the line, or point at the line that says it. "
            "If nothing in the transcript supports an item, leave the item out.")


def system_blocks(version):
    return [{"type": "text", "text": prompt(version)}]


def estimate(app, workspace, meeting, version=PROMPT_VERSION, model=None):
    """About what one summary will cost, in micro-dollars: count_tokens for the input + a guess for the output."""
    model = model or workspace.model
    lines = meetings.lines_of(meeting)
    tokens = llm.client_for(app).count_tokens(model, system_blocks(version), build_messages(meeting, lines))
    return pricing.cost_micros(model, input_tokens=tokens, output_tokens=OUTPUT_GUESS)


def is_busy(meeting, latest, moment):
    return meeting.status in ("queued", "running") and latest is not None and latest.created_at > moment - STALE_AFTER


def latest_run(s, meeting):
    return s.scalar(select(Run).where(Run.meeting_id == meeting.id).order_by(Run.id.desc()).limit(1))


def expire_stale(s, meeting, moment):
    """A summary that stopped without finishing (the server restarted mid-way) is marked failed."""
    latest = latest_run(s, meeting)
    if meeting.status in ("queued", "running") and (latest is None or latest.created_at <= moment - STALE_AFTER):
        meeting.status = "failed"
        if latest is not None and latest.status in ("queued", "running"):
            latest.status, latest.error_code = "failed", "stopped"
            latest.error = "The summary stopped before it finished (the server restarted). Run it again."
            latest.finished_at = moment
        return True
    return False


def start(s, app, workspace, meeting, moment, version=None, model=None):
    """Check the limits and make a queued Run. The caller commits, then calls launch(app, run.id)."""
    if is_busy(meeting, latest_run(s, meeting), moment):
        raise CantStart("This meeting is being summarized already.")
    model = model if model in pricing.MODELS else workspace.model
    version = version or workspace.prompt_version or PROMPT_VERSION
    try:
        guess = estimate(app, workspace, meeting, version, model)
    except llm.LLMError as error:
        raise CantStart(error.message) from error
    try:
        budget.check(s, app, workspace, moment, guess)
    except budget.OverBudget as error:
        raise CantStart(str(error)) from error
    run = Run(meeting_id=meeting.id, status="queued", model=model, prompt_version=version, effort=llm.EFFORT,
              practice=llm.is_practice(app), estimate_micros=guess, created_at=moment)
    s.add(run)
    meeting.status = "queued"
    s.flush()
    return run


def launch(app, run_id):
    if app.config.get("RUN_IN_THREAD"):
        threading.Thread(target=work, args=(app, run_id), name=f"summary-{run_id}", daemon=True).start()
    else:
        work(app, run_id)


def work(app, run_id):
    with app.app_context():
        s = db.new_session(app)
        try:
            _work(s, app, run_id)
        except Exception:  # a bug: say so on the run, never leave it "running"
            log.exception("Summary %s crashed", run_id)
            s.rollback()
            run = s.get(Run, run_id)
            if run is not None:
                _fail(s, run, "crash", "Something went wrong on our side while summarizing. Try again.")
        finally:
            s.close()


def _work(s, app, run_id):
    run = s.get(Run, run_id)
    if run is None or run.status != "queued":
        return
    meeting = s.get(Meeting, run.meeting_id)
    workspace = s.get(Workspace, meeting.workspace_id)
    client = llm.client_for(app)
    run.status = meeting.status = "running"
    run.started_at = utcnow()
    s.commit()

    lines = meetings.lines_of(meeting)

    def on_reply(reply, attempt):
        _count(s, run, workspace, reply)
        run.attempts, run.raw_output = attempt, reply.text
        run.stop_reason, run.served_model = reply.stop_reason, reply.model

    def on_checked(attempt, problems):
        _log_issues(s, run, attempt, problems)
        s.commit()

    outcome = ask_and_check(client, run.model, run.effort, system_blocks(run.prompt_version),
                            build_messages(meeting, lines), lines, meeting, on_reply, on_checked)
    if outcome.error is not None:
        run.attempts = outcome.attempts
        _fail(s, run, outcome.error.code, outcome.error.message)
        return
    if outcome.notes is None:
        _fail(s, run, "shape", "Claude's answer never had the right shape, even after "
              f"{MAX_ATTEMPTS - 1} tries to fix it. The Quality Lab lists the problems.")
        return
    save_notes(s, meeting, run, outcome.notes, outcome.problems, outcome.found)
    run.status = "needs_review" if outcome.problems else "done"
    meeting.status = "needs_review" if outcome.problems else "ready"
    run.finished_at = utcnow()
    s.commit()


@dataclass
class Outcome:
    notes: object | None      # the best MeetingNotes (the right shape), or None
    problems: list            # what is still wrong with it (each becomes a note's flag)
    found: dict               # (section, item, quote) -> was the quote on its line?
    attempts: int
    error: object | None = None   # an llm.LLMError, when Claude failed before any good shape


def ask_and_check(client, model, effort, system, messages, lines, meeting, on_reply=None, on_checked=None):
    """The loop: ask, check all three layers, send the problems back, at most MAX_ATTEMPTS times.
    Used by a meeting's summary (above) and by the Quality Lab's test set (evals.py).
    on_reply(reply, attempt) sees every answer (to count its cost); on_checked(attempt, problems) every check."""
    best, best_problems, best_found = None, [], {}
    attempt = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            reply = client.summarize(model, system, messages, effort)
        except llm.LLMError as error:
            if error.reply is not None and on_reply:  # a refused or cut-off answer was still paid for
                on_reply(error.reply, attempt)
            if best is not None:
                break  # an earlier answer had the right shape: keep it, flagged
            return Outcome(None, [], {}, attempt, error)
        if on_reply:
            on_reply(reply, attempt)
        notes, problems = schema.validate(reply.text)
        if notes is not None:
            found = {}
            for reviewer in reviewers:
                problems += reviewer(notes, lines, meeting, found)
            best, best_problems, best_found = notes, problems, found
        if on_checked:
            on_checked(attempt, problems)
        if not problems:
            break
        messages = messages + [{"role": "assistant", "content": reply.content},
                               {"role": "user", "content": repair_message(problems)}]
    return Outcome(best, best_problems, best_found, attempt)


def _count(s, run, workspace, reply):
    cost = 0 if run.practice else reply.cost_micros()
    run.input_tokens += reply.input_tokens
    run.output_tokens += reply.output_tokens
    run.cache_read_tokens += reply.cache_read
    run.cache_write_tokens += reply.cache_write
    run.cost_micros += cost
    budget.record(s, workspace, run, cost, utcnow())


def _log_issues(s, run, attempt, problems):
    """Save this attempt's problems, and mark the earlier ones it no longer has as fixed."""
    now = {(p.layer, p.path, p.message) for p in problems}
    for issue in run.issues:
        if issue.attempt < attempt and not issue.fixed and (issue.layer, issue.path, issue.message) not in now:
            issue.fixed = True
    for problem in problems:
        run.issues.append(RunIssue(attempt=attempt, layer=problem.layer, path=problem.path[:120], message=problem.message))


def _fail(s, run, code, message):
    run.status, run.error_code, run.error = "failed", code, message
    run.finished_at = utcnow()
    meeting = s.get(Meeting, run.meeting_id)
    meeting.status = "failed"
    s.commit()


def flags_by_item(problems):
    """'action_items.2.owner: ...' problems grouped as {('action_items', 2): ['owner: ...']}."""
    found = {}
    for problem in problems:
        parts = problem.path.split(".")
        if len(parts) >= 2 and parts[1].isdigit():
            found.setdefault((parts[0], int(parts[1])), []).append(problem.message if len(parts) == 2 else
                                                                   f"{'.'.join(parts[2:])}: {problem.message}")
    return found


def save_notes(s, meeting, run, notes, problems, found=None):
    """Replace the meeting's notes with this run's. Doubtful notes carry their flag."""
    s.execute(delete(Item).where(Item.meeting_id == meeting.id))
    flags = flags_by_item(problems)
    found = found or {}
    for section, kind in KINDS:
        for position, entry in enumerate(getattr(notes, section)):
            evidence = [{"line": e.line, "quote": e.quote, "found": found.get((section, position, j))}
                        for j, e in enumerate(entry.evidence)]
            item = Item(meeting_id=meeting.id, run_id=run.id, kind=kind, position=position,
                        text=getattr(entry, "text", None) or entry.task, evidence=evidence,
                        flag="; ".join(flags.get((section, position), [])) or None)
            if kind == "decision":
                item.detail = entry.rationale
            if kind == "action":
                item.owner, item.due_phrase, item.due_date, item.priority = entry.owner, entry.due_phrase, entry.due_date, entry.priority
            s.add(item)
    meeting.overview = notes.overview
    if not meeting.title_from_user:
        meeting.title = notes.title[:meetings.TITLE_MAX]
