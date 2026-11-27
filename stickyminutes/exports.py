"""Taking the minutes out of the app: Markdown, plain text (for an email), Word, and a share link.

Every export shows the same thing: the overview and the four parts, with
rejected notes left out (you said Claude got them wrong) and flagged notes
marked "(check this)". Each note keeps its line numbers, so a reader can
still find where it came from.

**The share link** `/s/<token>` is read-only and needs no login. Its token
is signed (tokens.py) over the meeting's id and `share_nonce`. Turning the
link off sets the nonce to None (every token fails); turning it on again
picks a NEW random number, so an old link never works again.
"""
import io
import re
import secrets

from . import tokens

SHARE_PURPOSE = "share"
PARTS = (("point", "Key Points"), ("decision", "Decisions"), ("action", "Action Items"), ("question", "Open Questions"))


def visible(items_by_kind):
    """The notes to export, by kind, without rejected ones."""
    return {kind: [item for item in items_by_kind.get(kind, []) if item.review != "rejected"] for kind, _ in PARTS}


def lines_label(item):
    numbers = sorted({e["line"] for e in item.evidence})
    if not numbers:
        return ""
    return ("line " if len(numbers) == 1 else "lines ") + ", ".join(str(n) for n in numbers)


def due_words(item):
    if item.due_date:
        return item.due_date.strftime("%a ") + f"{item.due_date.day} " + item.due_date.strftime("%b %Y")
    return item.due_phrase or ""


def describe(item, with_lines=True):
    """One note as a line of text (no Markdown): 'Send the files (Ben Cruz, due Fri 27 Nov 2026) [line 2]'."""
    words = item.text
    extras = []
    if item.kind == "action":
        extras.append(item.owner or "unassigned")
        if due := due_words(item):
            extras.append(f"due {due}")
        if item.priority == "high":
            extras.append("high priority")
        if item.status == "done":
            extras.append("done")
    if extras:
        words += f" ({', '.join(extras)})"
    if item.kind == "decision" and item.detail:
        words += f". Why: {item.detail}"
    if item.flag:
        words += " (check this)"
    if with_lines and (label := lines_label(item)):
        words += f" [{label}]"
    return words


def md_escape(text):
    """Stop *, _, # and friends in a note from turning into Markdown formatting."""
    return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", text or "")


def markdown(meeting, items_by_kind):
    notes = visible(items_by_kind)
    out = [f"# {md_escape(meeting.title)}", "",
           f"**Date:** {meeting.meeting_date.isoformat()}  ",
           f"**People:** {md_escape(', '.join(meeting.speakers) or 'not labelled')}", ""]
    if meeting.overview:
        out += [md_escape(meeting.overview), ""]
    for kind, heading in PARTS:
        out.append(f"## {heading}")
        out.append("")
        if not notes[kind]:
            out += ["_None._", ""]
            continue
        for item in notes[kind]:
            box = "- [x] " if kind == "action" and item.status == "done" else "- [ ] " if kind == "action" else "- "
            label = lines_label(item)
            out.append(box + md_escape(describe(item, with_lines=False)) + (f" [{label}]" if label else ""))
        out.append("")
    out.append("_Made with Sticky Minutes. Line numbers point at the meeting's transcript._")
    return "\n".join(out) + "\n"


def plain_text(meeting, items_by_kind):
    """For an email: no Markdown marks, short and readable."""
    notes = visible(items_by_kind)
    out = [f"{meeting.title} ({meeting.meeting_date.strftime('%a')} {meeting.meeting_date.day} {meeting.meeting_date.strftime('%b %Y')})", ""]
    if meeting.overview:
        out += [meeting.overview, ""]
    for kind, heading in PARTS:
        if notes[kind]:
            out.append(heading.upper())
            out += [f"- {describe(item)}" for item in notes[kind]]
            out.append("")
    return "\n".join(out).strip() + "\n"


def docx_bytes(meeting, items_by_kind):
    from docx import Document
    from docx.shared import Pt, RGBColor

    notes = visible(items_by_kind)
    document = Document()
    document.core_properties.title = meeting.title
    document.add_heading(meeting.title, level=0)
    facts = document.add_paragraph()
    facts.add_run("Date: ").bold = True
    facts.add_run(meeting.meeting_date.strftime("%A ") + f"{meeting.meeting_date.day} " + meeting.meeting_date.strftime("%B %Y"))
    facts.add_run("\nPeople: ").bold = True
    facts.add_run(", ".join(meeting.speakers) or "not labelled")
    if meeting.overview:
        document.add_paragraph(meeting.overview)
    for kind, heading in PARTS:
        document.add_heading(heading, level=1)
        if not notes[kind]:
            document.add_paragraph().add_run("None.").italic = True
            continue
        for item in notes[kind]:
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.add_run(item.text).bold = kind in ("decision", "action")
            rest = describe(item)[len(item.text):]
            if rest:
                small = paragraph.add_run(rest)
                small.font.size = Pt(9.5)
                small.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    footer = document.add_paragraph()
    note = footer.add_run("Made with Sticky Minutes. Line numbers point at the meeting's transcript.")
    note.italic = True
    note.font.size = Pt(9)
    data = io.BytesIO()
    document.save(data)
    return data.getvalue()


def filename(meeting, ending):
    """'2026-11-24 Launch planning.md', with only safe characters."""
    safe = re.sub(r"[^\w\- ]+", "", meeting.title).strip()[:60] or "Meeting"
    return f"{meeting.meeting_date.isoformat()} {safe}.{ending}"


# ---------- The share link ----------

def share_token(meeting):
    return tokens.make(SHARE_PURPOSE, meeting.id, meeting.share_nonce) if meeting.share_nonce else None


def turn_sharing(meeting, on):
    meeting.share_nonce = secrets.randbelow(1_000_000_000) + 1 if on else None


def meeting_for_token(s, token):
    from .models import Meeting
    parts = tokens.read_ints(SHARE_PURPOSE, token, 2)
    if parts is None:
        return None
    meeting = s.get(Meeting, parts[0])
    if meeting is None or meeting.share_nonce is None or meeting.share_nonce != parts[1]:
        return None
    return meeting

