"""The Action Tracker: every action item from every meeting, and a calendar feed of their due dates.

Action items are Items with kind "action". Rejected ones are left out (you
said Claude got them wrong). "Overdue" means open with a due date before
today in the workspace's time zone.

**The calendar feed** is a .ics file that Google Calendar, Outlook or
Apple Calendar can subscribe to. A calendar app fetches it without logging
in, so its link carries its own proof: a signed token (tokens.py) made of
the workspace's id and its `feed_nonce`. "Make a new link" adds 1 to the
nonce, and every old link stops working.
"""
from datetime import timedelta

from sqlalchemy import case, func, select

from . import tokens
from .dates import local_today, utcnow
from .models import Item, Meeting

TABS = (("open", "Open"), ("overdue", "Overdue"), ("done", "Done"), ("all", "All"))
FEED_PURPOSE = "calendar"


def base_query(workspace):
    return (select(Item, Meeting).join(Meeting, Meeting.id == Item.meeting_id)
            .where(Meeting.workspace_id == workspace.id, Item.kind == "action", Item.review != "rejected"))


def listing(s, workspace, tab="open", owner=None):
    today = local_today(workspace.time_zone)
    query = base_query(workspace)
    if tab == "open":
        query = query.where(Item.status == "open")
    elif tab == "overdue":
        query = query.where(Item.status == "open", Item.due_date < today)
    elif tab == "done":
        query = query.where(Item.status == "done")
    if owner == "-":
        query = query.where(Item.owner.is_(None))
    elif owner:
        query = query.where(Item.owner == owner)
    if tab == "done":
        query = query.order_by(Item.done_at.desc(), Item.id.desc())
    else:
        # Soonest first; no due date last; then the newest meeting.
        query = query.order_by(case((Item.due_date.is_(None), 1), else_=0), Item.due_date,
                               Meeting.meeting_date.desc(), Item.position)
    return s.execute(query).all()


def counts(s, workspace):
    today = local_today(workspace.time_zone)
    rows = s.execute(base_query(workspace).with_only_columns(Item.status, Item.due_date)).all()
    found = {"open": 0, "overdue": 0, "done": 0, "all": len(rows)}
    for status, due in rows:
        found[status] = found.get(status, 0) + 1
        if status == "open" and due is not None and due < today:
            found["overdue"] += 1
    return found


def open_count(s, workspace):
    query = base_query(workspace).where(Item.status == "open").with_only_columns(func.count())
    return s.scalar(query)


def owners(s, workspace):
    names = s.scalars(base_query(workspace).with_only_columns(Item.owner).distinct()).all()
    return sorted(name for name in names if name)


def is_overdue(item, today):
    return item.status == "open" and item.due_date is not None and item.due_date < today


def set_done(item, done, moment):
    item.status = "done" if done else "open"
    item.done_at = moment if done else None


# ---------- The calendar feed ----------

def feed_token(workspace):
    return tokens.make(FEED_PURPOSE, workspace.id, workspace.feed_nonce)


def workspace_for_token(s, token):
    from .models import Workspace
    parts = tokens.read_ints(FEED_PURPOSE, token, 2)
    if parts is None:
        return None
    workspace = s.get(Workspace, parts[0])
    if workspace is None or workspace.feed_nonce != parts[1]:
        return None
    return workspace


def ics_text(value):
    """Text for an .ics field: backslash, semicolon, comma and new lines escaped (RFC 5545)."""
    return (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def fold(line):
    """Lines longer than 75 bytes go on in the next line, which starts with a space (RFC 5545)."""
    data = line.encode("utf-8")
    if len(data) <= 75:
        return line
    pieces, current = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > (75 if not pieces else 74):
            pieces.append(current.decode("utf-8"))
            current = b""
        current += encoded
    pieces.append(current.decode("utf-8"))
    return "\r\n ".join(pieces)


def calendar(s, workspace, base_url):
    """Every open action item with a due date, as an all-day event on that day."""
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    rows = [(item, meeting) for item, meeting in listing(s, workspace, "open") if item.due_date]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Sticky Minutes//Action Items//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_text(workspace.name + ' - Action Items')}",
             "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for item, meeting in rows:
        who = f" ({item.owner})" if item.owner else ""
        link = f"{base_url}/meetings/{meeting.id}#item-{item.id}"
        lines += ["BEGIN:VEVENT", f"UID:action-{item.id}@stickyminutes", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{item.due_date.strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{(item.due_date + timedelta(days=1)).strftime('%Y%m%d')}",
                  f"SUMMARY:{ics_text(item.text + who)}",
                  f"DESCRIPTION:{ics_text('From the meeting: ' + meeting.title + chr(10) + link)}",
                  f"URL:{link}", "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"

