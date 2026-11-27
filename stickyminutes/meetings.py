"""Meetings: making one from a transcript, finding one, and the rules about who may see it.

A meeting belongs to ONE workspace. load() is the only way pages find a
meeting, and a meeting in another workspace is "not found", never
"forbidden", so nobody can learn that meeting 41 exists.
"""
from datetime import date

from flask import abort
from sqlalchemy import func, select

from .models import Meeting, TranscriptLine

TITLE_MAX = 120
DEMO_MAX_MEETINGS = 30


class Invalid(ValueError):
    """A form value a person must fix. The message says what."""


def default_title(day: date):
    return f"Meeting on {day.day} {day.strftime('%b %Y')}"


def clean_title(text):
    title = " ".join((text or "").split())
    if len(title) > TITLE_MAX:
        raise Invalid(f"Use at most {TITLE_MAX} characters for the title.")
    return title


def parse_day(text, today):
    """'2026-11-24' -> date. Empty -> today. Too far ahead or not a date -> Invalid."""
    text = (text or "").strip()
    if not text:
        return today
    try:
        day = date.fromisoformat(text)
    except ValueError as error:
        raise Invalid("Enter the meeting's date, like 2026-11-24.") from error
    if day.year < 2000 or (day - today).days > 366:
        raise Invalid("That date looks wrong. When was the meeting?")
    return day


def count(s, workspace):
    return s.scalar(select(func.count()).select_from(Meeting).where(Meeting.workspace_id == workspace.id))


def create(s, workspace, parsed, title, day, source_name=None):
    """A new meeting with its numbered lines. The caller commits."""
    if workspace.is_demo and count(s, workspace) >= DEMO_MAX_MEETINGS:
        raise Invalid(f"The demo holds at most {DEMO_MAX_MEETINGS} meetings. Delete one to add another.")
    meeting = Meeting(workspace_id=workspace.id, title=title or default_title(day), title_from_user=bool(title),
                      meeting_date=day, source_kind=parsed.kind, source_name=(source_name or None) and source_name[:200],
                      line_count=len(parsed.lines), word_count=parsed.words, speakers=parsed.speakers)
    s.add(meeting)
    s.flush()
    s.add_all(TranscriptLine(meeting_id=meeting.id, n=line.n, speaker=line.speaker, at=line.at, text=line.text)
              for line in parsed.lines)
    s.flush()
    return meeting


def load(s, workspace, meeting_id):
    """The meeting if it is in this workspace, else a 404."""
    meeting = s.get(Meeting, meeting_id)
    if meeting is None or meeting.workspace_id != workspace.id:
        abort(404)
    return meeting


def listing(s, workspace):
    return s.scalars(select(Meeting).where(Meeting.workspace_id == workspace.id)
                     .order_by(Meeting.meeting_date.desc(), Meeting.id.desc())).all()


def lines_of(meeting):
    """The saved lines as transcripts.Line, the shape Claude's prompt and the checks use."""
    from .transcripts import Line
    return [Line(row.n, row.speaker, row.at, row.text) for row in meeting.lines]
