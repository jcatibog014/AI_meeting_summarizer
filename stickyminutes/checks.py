"""Layer 3: does every note really come from THIS meeting? (Grounding and business rules.)

The schema (layers 1 and 2, schema.py) can say "a quote is a string of 1 to
300 characters". Only code that has the transcript can say "that quote is
on line 12". These checks need the meeting, so they run after Pydantic:

- **Quotes:** each evidence quote must be on its line, compared after
  normalising (case, spaces, curly quotes, punctuation at the ends). A quote
  that's on a DIFFERENT line is reported with the right line; one that isn't
  in the transcript at all is reported as made up.
- **Lines:** each evidence line must exist.
- **Owners:** an action item's owner must be a speaker or a name said in the
  meeting. "Ben" for the speaker "Ben Cruz" is fixed quietly to "Ben Cruz".
- **Due dates:** never before the meeting, never years ahead. A clear phrase
  ("tomorrow", "by Friday", "on December 15", "the 15th") is worked out from
  the meeting's date: a missing due_date is filled in, a different one is a
  problem. Vague phrases ("next week", "soon") are left alone.
- **Duplicates:** the same note twice in one part is merged into one.

Some things are FIXED here (owner names, filled-in dates, merged twins): they
are certain, and a repair turn would cost money for nothing. Everything else
is a Problem for the repair turn; a problem still there after the last try
becomes the note's flag (summarize.py).
"""
import calendar
import re
from datetime import date, timedelta

from .schema import Problem

SECTIONS = ("key_points", "decisions", "action_items", "open_questions")
WEEKDAYS = {name.lower(): number for number, name in enumerate(calendar.day_name)}
MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_abbr) if name})
LATEST_DUE = timedelta(days=730)


# ---------- Comparing words ----------

def normal(text):
    """Text for comparing: lowercase, straight quotes, one space, no punctuation at the ends."""
    text = (text or "").lower()
    for curly, straight in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("…", "...")):
        text = text.replace(curly, straight)
    text = " ".join(text.split())
    return text.strip(" .,;:!?\"'()-")


def quote_on(quote, line_text):
    return bool(normal(quote)) and normal(quote) in normal(line_text)


def where_is(quote, lines):
    """The numbers of the lines that have this quote."""
    return [line.n for line in lines if quote_on(quote, line.text)]


# ---------- Due dates ----------

def resolve_due(phrase, meeting_day):
    """A clear due phrase -> the date it means, from the meeting's day. Vague or unknown -> None."""
    words = normal(phrase)
    if not words:
        return None
    if re.search(r"\btoday\b|\bend of (the )?day\b|\btonight\b|\beod\b", words):
        return meeting_day
    if re.search(r"\btomorrow\b", words):
        return meeting_day + timedelta(days=1)
    if re.search(r"\b(next|following|end|this week|soon|asap|later|week|month)\b", words):
        return None  # "next Friday", "next week", "end of the month": people mean different days
    for name, number in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", words):
            ahead = (number - meeting_day.weekday()) % 7 or 7  # "Friday" said on a Friday is next week's
            return meeting_day + timedelta(days=ahead)
    # "December 15", "15 December", "Dec 15th"
    month_day = re.search(r"\b([a-z]+)\.? (\d{1,2})(?:st|nd|rd|th)?\b", words) or None
    day_month = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?([a-z]+)\b", words)
    for month_name, day_text in ([month_day.groups()] if month_day else []) + ([day_month.groups()[::-1]] if day_month else []):
        if month_name in MONTHS:
            return _next_date(meeting_day, MONTHS[month_name], int(day_text))
    # "the 15th": the next 15th
    if match := re.search(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", words):
        day_number = int(match[1])
        for months_ahead in range(0, 3):
            year = meeting_day.year + (meeting_day.month - 1 + months_ahead) // 12
            month = (meeting_day.month - 1 + months_ahead) % 12 + 1
            if day_number <= calendar.monthrange(year, month)[1]:
                candidate = date(year, month, day_number)
                if candidate >= meeting_day:
                    return candidate
    return None


def _next_date(meeting_day, month, day_number):
    for year in (meeting_day.year, meeting_day.year + 1):
        if day_number <= calendar.monthrange(year, month)[1]:
            candidate = date(year, month, day_number)
            if candidate >= meeting_day:
                return candidate
    return None


# ---------- Owners ----------

def match_owner(owner, speakers, transcript_words):
    """The owner as the meeting names them, or None if nobody in the meeting has that name.
    'Ben' -> 'Ben Cruz' when exactly one speaker is called Ben."""
    wanted = normal(owner)
    if not wanted:
        return None
    for speaker in speakers:
        if normal(speaker) == wanted:
            return speaker
    first_names = [speaker for speaker in speakers if normal(speaker).split(" ")[0] == wanted]
    if len(first_names) == 1:
        return first_names[0]
    # A name said in the meeting ("Ana, can you ..."), even if Ana never spoke.
    if all(re.search(rf"\b{re.escape(part)}\b", transcript_words) for part in wanted.split()):
        return owner
    return None


# ---------- The check ----------

def merge_twins(notes):
    """The same note twice in one part: keep the first, with both notes' evidence (at most 3)."""
    for section in SECTIONS:
        kept, seen = [], {}
        for item in getattr(notes, section):
            key = normal(getattr(item, "text", None) or item.task)
            if key in seen:
                first = seen[key]
                for e in item.evidence:
                    if len(first.evidence) < 3 and all((e.line, normal(e.quote)) != (f.line, normal(f.quote)) for f in first.evidence):
                        first.evidence.append(e)
                continue
            seen[key] = item
            kept.append(item)
        setattr(notes, section, kept)


def review(notes, lines, meeting, found):
    """Check (and quietly fix what is certain) one answer. Returns the problems.
    `found[(section, i, j)]` is set to whether each quote was found on its line."""
    problems = []
    by_n = {line.n: line for line in lines}
    last = len(lines)
    transcript_words = normal(" ".join(line.text for line in lines))
    merge_twins(notes)

    for section in SECTIONS:
        for i, item in enumerate(getattr(notes, section)):
            for j, e in enumerate(item.evidence):
                path = f"{section}.{i}.evidence.{j}"
                line = by_n.get(e.line)
                if line is None:
                    found[(section, i, j)] = False
                    problems.append(Problem("grounding", f"{path}.line",
                                            f"line {e.line} doesn't exist; the transcript has lines 1 to {last}"))
                    continue
                if quote_on(e.quote, line.text):
                    found[(section, i, j)] = True
                    continue
                found[(section, i, j)] = False
                elsewhere = where_is(e.quote, lines)
                if elsewhere:
                    problems.append(Problem("grounding", path, f"the quote “{e.quote}” is on line {elsewhere[0]}, not line {e.line}"))
                else:
                    problems.append(Problem("grounding", path, f"the quote “{e.quote}” isn't on line {e.line} or anywhere "
                                            "in the transcript; copy the words exactly"))

    for i, action in enumerate(notes.action_items):
        path = f"action_items.{i}"
        if action.owner:
            matched = match_owner(action.owner, meeting.speakers, transcript_words)
            if matched is None:
                problems.append(Problem("grounding", f"{path}.owner", f"“{action.owner}” isn't a speaker or a name said in "
                                        "the meeting; use their speaker label, or null if nobody took it on"))
            else:
                action.owner = matched
        worked_out = resolve_due(action.due_phrase, meeting.meeting_date) if action.due_phrase else None
        if action.due_date is None and worked_out is not None:
            action.due_date = worked_out
        elif action.due_date is not None:
            if action.due_date < meeting.meeting_date:
                problems.append(Problem("grounding", f"{path}.due_date", f"{action.due_date.isoformat()} is before the meeting "
                                        f"({meeting.meeting_date.isoformat()})"))
            elif action.due_date > meeting.meeting_date + LATEST_DUE:
                problems.append(Problem("grounding", f"{path}.due_date", f"{action.due_date.isoformat()} is years after the meeting"))
            elif worked_out is not None and worked_out != action.due_date:
                problems.append(Problem("grounding", f"{path}.due_date",
                                        f"“{action.due_phrase}” said on {meeting.meeting_date.strftime('%A')} "
                                        f"{meeting.meeting_date.isoformat()} means {worked_out.isoformat()}, not {action.due_date.isoformat()}"))
    return problems
