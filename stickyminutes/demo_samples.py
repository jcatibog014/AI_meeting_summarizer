"""The demo's sample meetings (Kape Cloud, a coffee subscription company) and their sample notes.

The notes are SAMPLE answers written for the demo, not made by Claude (a
real summary would cost the owner money for every visitor). They are
honest about it: every page says "Sample". But they go through the REAL
pipeline: each sample answer is handed to summarize.ask_and_check by a
scripted FakeClaude, so the checks run on it exactly as on Claude's:

- "Wholesale call" first points a quote at the wrong line: the grounding
  check catches it, a repair turn fixes it (2 tries);
- "Sprint planning" rewords one quote every time: after 3 tries the note
  keeps its flag (Needs review);
- relative due dates ("by Thursday") are worked out by checks.py, so the
  older meetings' items are overdue today.

An evidence entry is written as the words it quotes ({"find": "..."}); the
builder finds the line that has them, so the line numbers are always right
(unless a sample is wrong on purpose).

Afterwards some notes are accepted, edited or done, and one meeting has a
share link, so every page of the demo has an example. Two sample runs of
the Quality Lab's test set (prompts v1 and v2) are scored the same way.
"""
import copy
from datetime import timedelta

from sqlalchemy import select

from . import evals, exports, meetings, summarize, transcripts
from .dates import local_today
from .llm import FakeClaude, transcript_lines
from .models import EvalRun, Item, Run


def ev(*phrases):
    return [{"find": phrase} for phrase in phrases]


SAMPLES = [
    {
        "key": "standup", "title": "Monday Stand-up", "days_ago": 1, "kind": "vtt",
        "source_name": "GMT20261123-010203_Recording.transcript.vtt", "seconds": 24.6,
        "transcript": """WEBVTT

1
00:00:02.100 --> 00:00:05.400
Lea Ramos: Good morning, everyone. Quick round, please. Ben, you first.

2
00:00:05.900 --> 00:00:11.200
Ben Cruz: Morning. I finished the new checkout page on Friday.

3
00:00:11.300 --> 00:00:16.800
Ben Cruz: Today I'm fixing the bug where the discount code disappears. The fix will be ready for testing by Wednesday.

4
00:00:17.500 --> 00:00:23.000
Ana Reyes: Customer care had forty-two messages over the weekend, mostly about late deliveries in Cebu.

5
00:00:23.400 --> 00:00:29.100
Carlo Mendoza: That's the courier. They lost a truck for two days. It should be back to normal tomorrow.

6
00:00:29.800 --> 00:00:35.600
Lea Ramos: Ana, can you send the Cebu customers a short sorry message with a ten percent voucher?

7
00:00:36.000 --> 00:00:38.200
Ana Reyes: Yes, I'll send it today.

8
00:00:38.900 --> 00:00:45.000
Lea Ramos: Okay. We agreed last week to move the stand-up to 9:30 from next Monday, so please remember.

9
00:00:45.600 --> 00:00:51.300
Carlo Mendoza: Noted. Also, I still don't know if the new warehouse shelves arrive this week.

10
00:00:51.900 --> 00:00:56.000
Lea Ramos: Carlo, please call the supplier and tell me by Thursday.

11
00:00:56.400 --> 00:00:57.500
Carlo Mendoza: Will do.
""",
        "answer": {
            "title": "Monday stand-up",
            "overview": "The team went round with their updates. The checkout page is done and a discount code bug is being fixed, and late deliveries in Cebu came from the courier losing a truck. Cebu customers get a sorry message with a voucher.",
            "key_points": [
                {"text": "The new checkout page was finished on Friday.", "evidence": ev("I finished the new checkout page on Friday.")},
                {"text": "Most weekend messages to customer care were about late deliveries in Cebu.", "evidence": ev("mostly about late deliveries in Cebu")},
                {"text": "The courier lost a truck for two days; deliveries should be normal again tomorrow.", "evidence": ev("They lost a truck for two days.")},
            ],
            "decisions": [{"text": "The stand-up moves to 9:30 from next Monday.", "rationale": None,
                           "evidence": ev("move the stand-up to 9:30 from next Monday")}],
            "action_items": [
                {"task": "Fix the bug that makes the discount code disappear", "owner": "Ben Cruz", "due_phrase": "by Wednesday",
                 "due_date": None, "priority": "high", "evidence": ev("fixing the bug where the discount code disappears")},
                {"task": "Send Cebu customers a sorry message with a 10% voucher", "owner": "Ana Reyes", "due_phrase": "today",
                 "due_date": None, "priority": "medium", "evidence": ev("send the Cebu customers a short sorry message", "I'll send it today.")},
                {"task": "Call the shelf supplier and tell Lea when the shelves arrive", "owner": "Carlo Mendoza", "due_phrase": "by Thursday",
                 "due_date": None, "priority": "medium", "evidence": ev("Carlo, please call the supplier and tell me by Thursday.")},
            ],
            "open_questions": [{"text": "Will the new warehouse shelves arrive this week?",
                                "evidence": ev("if the new warehouse shelves arrive this week")}],
        },
        "accept": [("decision", 0), ("point", 0), ("action", 1)],
        "done": [1],
    },
    {
        "key": "client", "title": "Wholesale Call with Café Rosa", "days_ago": 5, "kind": "docx",
        "source_name": "Cafe Rosa call (transcript).docx", "seconds": 41.2, "repair": True, "share": True,
        "transcript": """Lea Ramos: Thanks for making time, Rosa. You wanted to talk about a bigger monthly order.
Rosa Villanueva: Yes. Our two branches now use about thirty kilos of beans a month.
Rosa Villanueva: We love the Benguet blend, but the price is getting hard for us.
Lea Ramos: For thirty kilos a month we can offer 780 pesos a kilo instead of 880.
Rosa Villanueva: That helps a lot. And can you deliver every two weeks?
Lea Ramos: Every two weeks is fine. Delivery is free inside Metro Manila.
Rosa Villanueva: Then let's go with 780 pesos and a delivery every two weeks.
Lea Ramos: Great. I'll send the contract by Friday.
Rosa Villanueva: Could you also bring a sample of the new dark roast for our baristas?
Lea Ramos: Of course. I will bring a sample bag on the first delivery.
Rosa Villanueva: One thing we haven't decided is whether our third branch joins in January.
Lea Ramos: No rush. Tell us when you know.
""",
        "answer": {
            "title": "Wholesale call with Café Rosa",
            "overview": "Café Rosa's two branches now use about thirty kilos of beans a month and asked for a better price. They agreed on 780 pesos a kilo with a delivery every two weeks, free inside Metro Manila.",
            "key_points": [
                {"text": "Café Rosa uses about thirty kilos of beans a month across two branches.", "evidence": ev("Our two branches now use about thirty kilos of beans a month.")},
                {"text": "Delivery is free inside Metro Manila.", "evidence": ev("Delivery is free inside Metro Manila.")},
            ],
            "decisions": [{"text": "Café Rosa pays 780 pesos a kilo, with a delivery every two weeks.",
                           "rationale": "They now order about thirty kilos a month, and the old price was getting hard for them.",
                           "evidence": ev("let's go with 780 pesos and a delivery every two weeks", "we can offer 780 pesos a kilo instead of 880")}],
            "action_items": [
                {"task": "Send Café Rosa the contract", "owner": "Lea Ramos", "due_phrase": "by Friday", "due_date": None,
                 "priority": "high", "evidence": ev("I'll send the contract by Friday.")},
                {"task": "Bring a sample bag of the new dark roast on the first delivery", "owner": "Lea Ramos",
                 "due_phrase": "on the first delivery", "due_date": None, "priority": "low",
                 "evidence": ev("I will bring a sample bag on the first delivery.")},
            ],
            "open_questions": [{"text": "Will Café Rosa's third branch join in January?",
                                "evidence": ev("whether our third branch joins in January")}],
        },
        "accept": [("decision", 0), ("action", 0)],
    },
    {
        "key": "planning", "title": "Sprint Planning: Loyalty Points", "days_ago": 8, "kind": "paste", "seconds": 37.9,
        "flag": True,
        "transcript": """Lea Ramos: This sprint's goal is the loyalty points page. Customers earn one point for every hundred pesos.
Ben Cruz: I'll build the points page. It should be ready for testing by Thursday.
Ana Reyes: I can write the help text and the FAQ tomorrow.
Maria Santos: What about the referral program? Customers keep asking for it.
Lea Ramos: We decided to leave referrals for the next sprint. Points first.
Maria Santos: Fine by me, as long as it's in January.
Carlo Mendoza: Who tests the page on older Android phones? Last time the layout broke.
Lea Ramos: Carlo, you take the testing, please. Ben can lend you the old Samsung.
Carlo Mendoza: Okay, I'll test it on Friday.
Ben Cruz: Do points expire? We never said.
Lea Ramos: Good question. Let's ask Maria's accountant before we launch.
""",
        "answer": {
            "title": "Sprint planning: loyalty points",
            "overview": "The sprint goal is the loyalty points page, where customers earn a point for every hundred pesos. Referrals wait for the next sprint, and nobody knows yet whether points expire.",
            "key_points": [
                {"text": "Customers will earn one point for every hundred pesos.", "evidence": ev("Customers earn one point for every hundred pesos.")},
                {"text": "The page broke on older Android phones last time, so it needs testing there.", "evidence": ev("Last time the layout broke.")},
            ],
            "decisions": [{"text": "Referrals wait for the next sprint; points come first.", "rationale": "Maria agreed, as long as referrals come in January.",
                           "evidence": ev("We decided to leave referrals for the next sprint.", "Fine by me, as long as it's in January.")}],
            "action_items": [
                {"task": "Build the loyalty points page", "owner": "Ben Cruz", "due_phrase": "by Thursday", "due_date": None,
                 "priority": "high", "evidence": ev("I'll build the points page.")},
                {"task": "Write the help text and the FAQ for the points page", "owner": "Ana Reyes", "due_phrase": "tomorrow",
                 "due_date": None, "priority": "medium", "evidence": ev("I'll do the help text and FAQ tomorrow.")},  # reworded: never found
                {"task": "Test the points page on older Android phones", "owner": "Carlo Mendoza", "due_phrase": "on Friday",
                 "due_date": None, "priority": "medium", "evidence": ev("Carlo, you take the testing, please.", "I'll test it on Friday.")},
                {"task": "Ask the accountant whether points should expire", "owner": None, "due_phrase": "before we launch",
                 "due_date": None, "priority": "medium", "evidence": ev("Let's ask Maria's accountant before we launch.")},
            ],
            "open_questions": [{"text": "Do loyalty points expire?", "evidence": ev("Do points expire?")}],
        },
    },
    {
        "key": "retro", "title": "October Retro", "days_ago": 12, "kind": "srt", "source_name": "october-retro.srt",
        "seconds": 29.3, "accept": "all", "done": [0, 1],
        "transcript": """1
00:00:01,000 --> 00:00:04,000
Maria Santos: Let's start with what went well in October.

2
00:00:04,500 --> 00:00:08,000
Ben Cruz: The new roaster delivered on time every single week.

3
00:00:08,600 --> 00:00:14,000
Ana Reyes: Customer emails got answered in under four hours since we added the reply templates.

4
00:00:14,500 --> 00:00:16,000
Maria Santos: And what didn't go well?

5
00:00:16,400 --> 00:00:20,500
Carlo Mendoza: Shipping to Mindanao was slow, sometimes ten days.

6
00:00:21,000 --> 00:00:26,000
Ana Reyes: And three customers got the wrong grind, all from the same packing day.

7
00:00:26,500 --> 00:00:31,000
Maria Santos: Then let's switch Mindanao orders to the faster courier starting December.

8
00:00:31,500 --> 00:00:36,000
Ben Cruz: Agreed. It costs a bit more, but we lose customers when it's slow.

9
00:00:36,500 --> 00:00:41,000
Carlo Mendoza: I'll compare the two couriers' prices and share them on Monday.

10
00:00:41,500 --> 00:00:45,000
Ana Reyes: I'll add a grind check to the packing list today.
""",
        "answer": {
            "title": "October retro",
            "overview": "October went well for deliveries from the roaster and for fast email replies. Shipping to Mindanao was slow and some orders had the wrong grind, so Mindanao moves to a faster courier in December.",
            "key_points": [
                {"text": "The new roaster delivered on time every week.", "evidence": ev("The new roaster delivered on time every single week.")},
                {"text": "Reply templates brought customer email answers under four hours.", "evidence": ev("Customer emails got answered in under four hours")},
                {"text": "Three customers got the wrong grind, all from one packing day.", "evidence": ev("three customers got the wrong grind, all from the same packing day")},
            ],
            "decisions": [{"text": "Mindanao orders switch to the faster courier from December.",
                           "rationale": "It costs a bit more, but slow shipping loses customers.",
                           "evidence": ev("let's switch Mindanao orders to the faster courier starting December", "we lose customers when it's slow")}],
            "action_items": [
                {"task": "Compare the two couriers' prices and share them", "owner": "Carlo Mendoza", "due_phrase": "on Monday",
                 "due_date": None, "priority": "medium", "evidence": ev("I'll compare the two couriers' prices and share them on Monday.")},
                {"task": "Add a grind check to the packing list", "owner": "Ana Reyes", "due_phrase": "today",
                 "due_date": None, "priority": "high", "evidence": ev("I'll add a grind check to the packing list today.")},
            ],
            "open_questions": [],
        },
    },
    {
        "key": "one-on-one", "title": "One-on-one: Lea and Ana", "days_ago": 3, "kind": "paste", "seconds": 22.8,
        "edit": True,
        "transcript": """Lea Ramos: Kumusta, Ana? How are the customer emails going this week?
Ana Reyes: Okay naman. Busy because of the Christmas orders, almost double.
Lea Ramos: Do you need help? We could hire a part-time helper for December.
Ana Reyes: Yes please, that would help a lot, especially on weekends.
Lea Ramos: Okay, we agreed: a part-time helper for December, weekends included. I'll post the job ad tomorrow.
Ana Reyes: Salamat! Also, I want to learn the new email tool everyone talks about.
Lea Ramos: Sure, take the online course this month. Kape Cloud will pay for it.
Ana Reyes: Can I take Friday afternoon off for my sister's graduation?
Lea Ramos: Of course, no problem. Just tell Ben so he covers the chat.
""",
        "answer": {
            "title": "One-on-one: Lea and Ana",
            "overview": "Christmas orders almost doubled customer emails, so Kape Cloud will hire a part-time helper for December. Ana will take an online course on the new email tool, paid by the company.",
            "key_points": [{"text": "Christmas orders almost doubled the customer emails.", "evidence": ev("Busy because of the Christmas orders, almost double.")}],
            "decisions": [
                {"text": "Hire a part-time helper for December, weekends included.", "rationale": "The Christmas orders almost doubled the emails.",
                 "evidence": ev("we agreed: a part-time helper for December, weekends included")},
                {"text": "Kape Cloud pays for Ana's online course on the new email tool.", "rationale": None,
                 "evidence": ev("Kape Cloud will pay for it.")},
                {"text": "Ana takes Friday afternoon off.", "rationale": "Her sister's graduation.",
                 "evidence": ev("Can I take Friday afternoon off", "Of course, no problem.")},
            ],
            "action_items": [
                {"task": "Post the job ad for the part-time helper", "owner": "Lea Ramos", "due_phrase": "tomorrow",
                 "due_date": None, "priority": "high", "evidence": ev("I'll post the job ad tomorrow.")},
                {"task": "Take the online course on the new email tool", "owner": "Ana Reyes", "due_phrase": "this month",
                 "due_date": None, "priority": "low", "evidence": ev("take the online course this month")},
                {"task": "Tell Ben to cover the chat on Friday afternoon", "owner": "Ana Reyes", "due_phrase": None,
                 "due_date": None, "priority": "medium", "evidence": ev("Just tell Ben so he covers the chat.")},
            ],
            "open_questions": [],
        },
    },
    {
        "key": "budget", "title": "Budget Review: January to March", "days_ago": 6, "kind": "paste", "seconds": 33.4,
        "transcript": """Maria Santos: Let's go through the budget for January to March.
Carlo Mendoza: Shipping is our biggest cost, about 180,000 pesos a quarter.
Maria Santos: Can we bring that down?
Carlo Mendoza: If we ship twice a week instead of every day, we save maybe twenty percent.
Lea Ramos: Customers might not like waiting longer, though.
Maria Santos: Let's try twice a week in Luzon only and see what customers say.
Ben Cruz: The app needs a bigger server plan too. It's 9,000 pesos more a month.
Maria Santos: We approved the server plan already. The app was slow during the sale.
Lea Ramos: Marketing wants 50,000 pesos for the summer campaign.
Maria Santos: I'm not sure yet. Lea, bring me the campaign plan by next Friday and we'll decide then.
Lea Ramos: Okay.
""",
        "answer": {
            "title": "Q1 budget review",
            "overview": "Shipping is the biggest cost at about 180,000 pesos a quarter, so Luzon will try shipping twice a week. The bigger server plan is approved, and the summer campaign waits for a plan.",
            "key_points": [
                {"text": "Shipping costs about 180,000 pesos a quarter, the biggest cost.", "evidence": ev("Shipping is our biggest cost, about 180,000 pesos a quarter.")},
                {"text": "Shipping twice a week could save about twenty percent.", "evidence": ev("we save maybe twenty percent")},
            ],
            "decisions": [
                {"text": "Try shipping twice a week in Luzon only, and listen to customers.", "rationale": "It could save about twenty percent of shipping costs.",
                 "evidence": ev("Let's try twice a week in Luzon only")},
                {"text": "The bigger server plan (9,000 pesos more a month) is approved.", "rationale": "The app was slow during the sale.",
                 "evidence": ev("We approved the server plan already.", "The app was slow during the sale.")},
            ],
            "action_items": [{"task": "Bring the summer campaign plan to Maria", "owner": "Lea Ramos", "due_phrase": "by next Friday",
                              "due_date": None, "priority": "medium", "evidence": ev("Lea, bring me the campaign plan by next Friday")}],
            "open_questions": [
                {"text": "Will marketing get 50,000 pesos for the summer campaign?", "evidence": ev("Marketing wants 50,000 pesos for the summer campaign.")},
                {"text": "Will customers accept waiting longer for deliveries?", "evidence": ev("Customers might not like waiting longer, though.")},
            ],
        },
    },
]


def build(answer, lines, wrong_line=False):
    """The sample answer with each {"find": words} turned into {"line": n, "quote": words}.
    wrong_line: the first decision's first quote points two lines too far (for the repair sample)."""
    answer = copy.deepcopy(answer)
    texts = {n: text for n, _, text in lines}
    for section in ("key_points", "decisions", "action_items", "open_questions"):
        for item in answer[section]:
            for e in item["evidence"]:
                words = e.pop("find")
                matches = [n for n, text in texts.items() if checks_has(words, text)]
                e["line"], e["quote"] = (matches[0] if matches else 1), words
    if wrong_line and answer["decisions"]:
        answer["decisions"][0]["evidence"][0]["line"] += 2
    return answer


def checks_has(words, text):
    from .checks import quote_on
    return quote_on(words, text)


def scripted(spec):
    """The FakeClaude script for one sample: the answer, or a wrong one first and then the right one."""
    def first(messages):
        return build(spec["answer"], transcript_lines(messages), wrong_line=spec.get("repair", False))

    def fixed(messages):
        return build(spec["answer"], transcript_lines(messages))
    return [first, fixed] if spec.get("repair") else [fixed]


def add_meeting(s, app, workspace, spec, moment):
    day = local_today(workspace.time_zone, moment) - timedelta(days=spec["days_ago"])
    parsed = transcripts.parse(spec["transcript"], spec["kind"])
    meeting = meetings.create(s, workspace, parsed, spec["title"], day, spec.get("source_name"))
    when = moment - timedelta(days=spec["days_ago"]) + timedelta(hours=2)
    meeting.created_at = when
    run = Run(meeting_id=meeting.id, status="queued", model=workspace.model, prompt_version="v1", sample=True,
              practice=False, created_at=when)
    s.add(run)
    s.flush()
    summarize._work(s, app, run.id, client=FakeClaude(script=scripted(spec), practice=False))
    run.started_at, run.finished_at = when, when + timedelta(seconds=spec["seconds"])
    items = s.scalars(select(Item).where(Item.meeting_id == meeting.id)).all()
    by_key = {(item.kind, item.position): item for item in items}
    accept = spec.get("accept", [])
    for item in items:
        if accept == "all" or (item.kind, item.position) in accept:
            item.review = "accepted"
    for position in spec.get("done", []):
        if (action := by_key.get(("action", position))) is not None:
            action.status, action.done_at = "done", when + timedelta(days=1)
    if spec.get("edit") and (course := by_key.get(("action", 1))) is not None:
        course.due_date, course.due_phrase = day + timedelta(days=21), None
        course.text, course.edited, course.review = "Finish the online course on the new email tool", True, "accepted"
    if spec.get("share"):
        exports.turn_sharing(meeting, True)
    return meeting


# ---------- The Quality Lab's sample test runs ----------

def eval_answer(case, perfect):
    """A sample answer for one test case. The v1 sample misses some owners, makes one decision up
    in the "nothing" meeting, and rewords a quote in the client call (never fixed)."""
    def answer(messages):
        lines = transcript_lines(messages)
        texts = {n: text for n, _, text in lines}
        repairing = len(messages) > 1

        def evidence_for(keywords):
            for n, text in texts.items():
                if all(k in text.lower() for k in keywords):
                    return [{"line": n, "quote": " ".join(text.split()[:10])}]
            return [{"line": 1, "quote": " ".join(texts[1].split()[:6])}]
        decisions = [{"text": " ".join(keys).capitalize() + " (agreed).", "rationale": None, "evidence": evidence_for(keys)}
                     for keys in case.decisions]
        actions = [{"task": "Handle the " + " ".join(keys), "owner": owner, "due_phrase": None, "due_date": None,
                    "priority": "medium", "evidence": evidence_for(keys)} for keys, owner in case.actions]
        if not perfect:
            if case.key == "idea":
                decisions = [{"text": "Start an office subscription.", "rationale": None,
                              "evidence": [{"line": 1, "quote": "a coffee subscription for offices"}]}]
            if case.key == "planning" and actions:
                actions[-1]["owner"] = None  # forgot who took the testing
            if case.key == "client" and actions:
                actions[0]["evidence"] = [{"line": 5, "quote": "I'll get the contract to you Friday"}]
            if case.key == "retro" and not repairing:
                decisions[0]["evidence"][0]["line"] += 1
        elif case.key == "standup" and not repairing:
            actions[0]["evidence"][0]["line"] += 1  # v2 also needs one repair, then passes
        return {"title": case.title, "overview": "A sample answer for the test set.", "key_points": [],
                "decisions": decisions, "action_items": actions, "open_questions": []}
    return answer


def by_case(messages):
    first = transcript_lines(messages)[0][2]
    return next(case for case in evals.CASES if case.transcript.splitlines()[0].split(": ", 1)[1] == first)


def add_eval_run(s, app, workspace, version, perfect, when, seconds):
    run = EvalRun(workspace_id=workspace.id, prompt_version=version, model=workspace.model, sample=True, created_at=when)
    s.add(run)
    s.flush()
    script = [lambda messages: eval_answer(by_case(messages), perfect)(messages)]
    evals._work(s, app, run.id, client=FakeClaude(script=script, practice=False))
    run.started_at, run.finished_at = when, when + timedelta(seconds=sum(seconds))
    results = []
    for result, took in zip(run.results, seconds):
        results.append(dict(result, seconds=took))
    run.results = results
    run.summary = evals.summary(results)


def fill(s, workspace, me, moment):
    from flask import current_app
    app = current_app._get_current_object()
    for spec in SAMPLES:
        add_meeting(s, app, workspace, spec, moment)
    add_eval_run(s, app, workspace, "v1", False, moment - timedelta(days=4), [31.2, 44.8, 19.5, 52.1, 38.0, 27.4])
    add_eval_run(s, app, workspace, "v2", True, moment - timedelta(days=2), [36.7, 29.9, 17.2, 34.5, 40.3, 25.1])
