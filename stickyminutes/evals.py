"""The Quality Lab's test set: six small meetings whose right answers we know, to score a prompt or a model.

Changing the prompt (prompts/v2.md) or the model changes the notes. Is it
better? Reading one meeting's notes can't say; a fixed test set can. Each
case lists what a good answer MUST have:

- decisions: each as a few keywords that its text must contain;
- action items: keywords + the owner who must be named;
- `nothing`: a chat where nothing was decided or promised. Any decision or
  action item there is MADE UP, and is counted against the run.

A run sends every case through the very same loop as a real summary
(summarize.ask_and_check: the three layers of checks and the repair turns),
then scores it:

- recall: how many of the expected decisions and action items were found;
- owners: of the action items found, how many name the right owner;
- grounding: the share of quotes that really were on their line;
- right first time: no problem at all in the first answer;
- passed: no problem left after the repairs;
- made up: decisions or action items in the "nothing" case;
- cost and time.

It costs real money with a real API key (six summaries), so the page shows
the estimate and asks first; the daily cap applies. In practice mode it is
free and scores FakeClaude's simple notes.
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select

from . import budget, checks, db, llm, pricing, summarize, transcripts
from .dates import utcnow
from .models import EvalRun, UsageEntry, Workspace

log = logging.getLogger(__name__)


@dataclass
class Case:
    key: str
    title: str
    day: date
    transcript: str
    decisions: list = field(default_factory=list)        # [("keyword", ...), ...]
    actions: list = field(default_factory=list)          # [(("keyword", ...), "Owner"), ...]
    nothing: bool = False


CASES = [
    Case("standup", "Daily stand-up", date(2026, 11, 16), """\
Maria Santos: Morning, everyone. Let's go around quickly. Ben?
Ben Cruz: Yesterday I fixed the checkout bug on the phone app. I'll deploy the fix by Wednesday.
Ana Reyes: I'm still working on the subscription emails. I'm stuck until I get the new logo files.
Maria Santos: Carlo, can you send Ana the logo files today?
Carlo Mendoza: Sure, I'll send them right after this call.
Maria Santos: Good. We agreed to skip Friday's stand-up because of the holiday.
Ben Cruz: Works for me.
""", decisions=[("skip", "friday")], actions=[(("deploy", "fix"), "Ben Cruz"), (("logo",), "Carlo Mendoza")]),

    Case("client", "Wholesale call with Café Rosa", date(2026, 11, 18), """\
Lea Ramos: Thanks for joining, Rosa. You wanted to talk about the wholesale order.
Rosa Villanueva: Yes. We go through about twenty kilos a month now. Can you give us a better price?
Lea Ramos: For twenty kilos a month we can do 820 pesos a kilo instead of 900.
Rosa Villanueva: That works for us. Let's go with 820 and one delivery a month.
Lea Ramos: Great. I'll send you the contract by Friday.
Rosa Villanueva: Could you also include a sample of the new dark roast?
Lea Ramos: Of course, I will add a sample bag to the first delivery.
Rosa Villanueva: One thing I'm not sure about yet is whether we need decaf too.
""", decisions=[("820",)], actions=[(("contract",), "Lea Ramos"), (("sample",), "Lea Ramos")]),

    Case("idea", "Office subscription idea", date(2026, 11, 19), """\
Ben Cruz: I've been thinking about a coffee subscription for offices.
Ana Reyes: Interesting. Offices might want bigger bags than homes do.
Ben Cruz: Maybe. Or a coffee machine rental too, but that sounds complicated.
Ana Reyes: Some of our competitors do that. I'm not sure it pays off.
Ben Cruz: True. It's just an idea for now, nothing to decide today.
Ana Reyes: Let's keep thinking about it.
""", nothing=True),

    Case("planning", "Sprint planning", date(2026, 11, 23), """\
Maria Santos: The sprint goal is the new loyalty points page.
Ben Cruz: I'll build the points page. It should be ready by Thursday.
Ana Reyes: I can write the help text for it tomorrow.
Maria Santos: We decided to leave the referral feature for the next sprint.
Carlo Mendoza: Who will test the page on older phones?
Maria Santos: Carlo, you take the testing, please.
Carlo Mendoza: Okay, I'll test it on Friday.
""", decisions=[("referral",)], actions=[(("points page",), "Ben Cruz"), (("help text",), "Ana Reyes"), (("test",), "Carlo Mendoza")]),

    Case("retro", "Monthly retro", date(2026, 11, 20), """\
Maria Santos: What went well this month?
Ben Cruz: The new roaster delivered on time every single week.
Ana Reyes: Customer emails were answered faster since we added the reply templates.
Maria Santos: And what didn't go well?
Carlo Mendoza: Shipping to Mindanao took too long, sometimes ten days.
Maria Santos: Then let's switch Mindanao orders to the faster courier starting December.
Ben Cruz: Agreed.
Carlo Mendoza: I'll compare the two couriers' prices and share them on Monday.
""", decisions=[("courier",)], actions=[(("compare",), "Carlo Mendoza")]),

    Case("one-on-one", "Lea and Ana, one-on-one", date(2026, 11, 24), """\
Lea Ramos: Kumusta, Ana? How are the customer emails going?
Ana Reyes: Okay naman. A bit busy because of the holiday orders.
Lea Ramos: Do you need help? We could hire a part-time helper for December.
Ana Reyes: Yes please, that would help a lot.
Lea Ramos: Okay, we agreed: a part-time helper for December. I'll post the job ad tomorrow.
Ana Reyes: Salamat! Also, I want to learn the new email tool.
Lea Ramos: Sure, take the online course this month. The company will pay for it.
""", decisions=[("helper",)], actions=[(("job ad",), "Lea Ramos")]),
]


def has_words(text, keywords):
    words = checks.normal(text)
    return all(keyword in words for keyword in keywords)


def score(case, outcome):
    """One case's numbers (None where a number means nothing, like recall in the "nothing" case)."""
    notes = outcome.notes
    result = {"case": case.key, "title": case.title, "attempts": outcome.attempts}
    if notes is None:
        result.update(recall=0.0 if not case.nothing else None, owners=None, grounding=None, passed=False,
                      made_up=None, error=outcome.error.message if outcome.error else "No answer had the right shape.")
        return result
    expected = len(case.decisions) + len(case.actions)
    found_decisions = sum(any(has_words(d.text, keys) for d in notes.decisions) for keys in case.decisions)
    action_hits = [next((a for a in notes.action_items if has_words(a.task, keys)), None) for keys, _ in case.actions]
    found_actions = sum(hit is not None for hit in action_hits)
    right_owners = sum(hit is not None and hit.owner == owner for hit, (_, owner) in zip(action_hits, case.actions))
    quotes = list(outcome.found.values())
    result.update(
        recall=(found_decisions + found_actions) / expected if expected else None,
        owners=right_owners / found_actions if found_actions else None,
        grounding=sum(1 for ok in quotes if ok) / len(quotes) if quotes else None,
        passed=not outcome.problems,
        made_up=len(notes.decisions) + len(notes.action_items) if case.nothing else None,
        decisions=len(notes.decisions), actions=len(notes.action_items))
    return result


def average(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def summary(results):
    return {
        "recall": average(r.get("recall") for r in results),
        "owners": average(r.get("owners") for r in results),
        "grounding": average(r.get("grounding") for r in results),
        "first_try": average(1.0 if r.get("first_try") else 0.0 for r in results),
        "passed": average(1.0 if r.get("passed") else 0.0 for r in results),
        "made_up": sum(r.get("made_up") or 0 for r in results),
        "attempts": average(r.get("attempts") for r in results),
        "seconds": average(r.get("seconds") for r in results),
        "cases": len(results),
    }


def case_meeting(case):
    parsed = transcripts.parse(case.transcript)
    meeting = SimpleNamespace(title=case.title, title_from_user=True, meeting_date=case.day, speakers=parsed.speakers)
    return meeting, parsed.lines


def estimate(app, version, model):
    client = llm.client_for(app)
    total = 0
    for case in CASES:
        meeting, lines = case_meeting(case)
        tokens = client.count_tokens(model, summarize.system_blocks(version), summarize.build_messages(meeting, lines))
        total += pricing.cost_micros(model, input_tokens=tokens, output_tokens=summarize.OUTPUT_GUESS)
    return total


def start(s, app, workspace, version, model, moment):
    """Make a queued EvalRun. The caller commits, then calls launch(). Raises summarize.CantStart."""
    if version not in summarize.prompt_versions():
        raise summarize.CantStart("Choose a prompt version from the list.")
    if model not in pricing.MODELS:
        raise summarize.CantStart("Choose a model from the list.")
    busy = s.scalar(select(EvalRun.id).where(EvalRun.workspace_id == workspace.id, EvalRun.status.in_(("queued", "running")),
                                             EvalRun.created_at > moment - summarize.STALE_AFTER))
    if busy:
        raise summarize.CantStart("A test run is already going. Wait for it to finish.")
    practice = llm.is_practice(app)
    try:
        guess = 0 if practice else estimate(app, version, model)
    except llm.LLMError as error:
        raise summarize.CantStart(error.message) from error
    if not practice and budget.spent_today(s, moment) + guess > budget.cap_micros(app):
        raise summarize.CantStart("The test set would go over today's spending limit for Claude. Try again tomorrow.")
    run = EvalRun(workspace_id=workspace.id, prompt_version=version, model=model, practice=practice,
                  estimate_micros=guess, created_at=moment)
    s.add(run)
    s.flush()
    return run


def launch(app, run_id):
    if app.config.get("RUN_IN_THREAD"):
        threading.Thread(target=work, args=(app, run_id), name=f"eval-{run_id}", daemon=True).start()
    else:
        work(app, run_id)


def work(app, run_id):
    with app.app_context():
        s = db.new_session(app)
        try:
            _work(s, app, run_id)
        except Exception:
            log.exception("Test run %s crashed", run_id)
            s.rollback()
            run = s.get(EvalRun, run_id)
            if run is not None:
                run.status, run.error, run.finished_at = "failed", "Something went wrong on our side.", utcnow()
                s.commit()
        finally:
            s.close()


def _work(s, app, run_id):
    run = s.get(EvalRun, run_id)
    if run is None or run.status != "queued":
        return
    workspace = s.get(Workspace, run.workspace_id)
    client = llm.client_for(app)
    run.status, run.started_at = "running", utcnow()
    s.commit()
    results = []
    for case in CASES:
        meeting, lines = case_meeting(case)
        first = {}
        began = time.perf_counter()

        def on_reply(reply, attempt):
            if not run.practice:
                cost = reply.cost_micros()
                run.cost_micros += cost
                s.add(UsageEntry(workspace_id=workspace.id, day=utcnow().date(), is_demo=workspace.is_demo,
                                 cost_micros=cost, created_at=utcnow()))

        def on_checked(attempt, problems):
            if attempt == 1:
                first["problems"] = len(problems)

        outcome = summarize.ask_and_check(client, run.model, llm.EFFORT, summarize.system_blocks(run.prompt_version),
                                          summarize.build_messages(meeting, lines), lines, meeting, on_reply, on_checked)
        result = score(case, outcome)
        result["first_try"] = outcome.attempts == 1 and first.get("problems") == 0
        result["seconds"] = round(time.perf_counter() - began, 2)
        results.append(result)
        run.results = list(results)  # a new list, so SQLAlchemy sees the change
        s.commit()
    run.summary = summary(results)
    run.status, run.finished_at = "done", utcnow()
    s.commit()


def expire_stale(s, workspace, moment):
    for run in s.scalars(select(EvalRun).where(EvalRun.workspace_id == workspace.id, EvalRun.status.in_(("queued", "running")),
                                               EvalRun.created_at <= moment - summarize.STALE_AFTER)):
        run.status, run.error, run.finished_at = "failed", "It stopped before it finished (the server restarted).", moment
