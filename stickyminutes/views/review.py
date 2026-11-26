"""Review & Proof: accept, reject or edit each note Claude wrote, with its proof beside it.

A note belongs to a meeting, which belongs to a workspace: load_item() goes
through meetings.load(), so another workspace's note is a 404 like its meeting.
"""
from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db, meetings
from ..auth import login_required
from ..dates import utcnow
from ..models import Item

bp = Blueprint("review", __name__)
KIND_WORDS = {"point": "key point", "decision": "decision", "action": "action item", "question": "open question"}
DECISIONS = {"accept": "accepted", "reject": "rejected", "undo": "unreviewed"}


def load_item(s, item_id):
    item = s.get(Item, item_id)
    if item is None:
        abort(404)
    meeting = meetings.load(s, g.workspace, item.meeting_id)
    return item, meeting


def back_to(meeting, item):
    return redirect(url_for("meetings.show", meeting_id=meeting.id, _anchor=f"item-{item.id}"))


@bp.post("/items/<int:item_id>/review")
@login_required
def decide(item_id):
    s = db.session()
    item, meeting = load_item(s, item_id)
    choice = request.form.get("decision")
    if choice not in DECISIONS:
        abort(400, "Choose Accept, Reject or Undo.")
    item.review = DECISIONS[choice]
    meeting.updated_at = utcnow()
    s.commit()
    return back_to(meeting, item)


def owner_choices(meeting, current):
    names = list(meeting.speakers)
    if current and current not in names:
        names.append(current)
    return [("", "Unassigned")] + [(name, name) for name in names]


@bp.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit(item_id):
    s = db.session()
    item, meeting = load_item(s, item_id)
    errors = {}
    if request.method == "POST":
        form = request.form
        text = " ".join(form.get("text", "").split())
        if not text:
            errors["text"] = "Write the note."
        elif len(text) > 300:
            errors["text"] = "Use at most 300 characters."
        detail = " ".join(form.get("detail", "").split()) or None
        if detail and len(detail) > 300:
            errors["detail"] = "Use at most 300 characters."
        owner = form.get("owner", "").strip() or None
        if owner and owner not in dict(owner_choices(meeting, item.owner)):
            errors["owner"] = "Choose someone from the list."
        due = None
        if form.get("due_date", "").strip():
            try:
                due = date.fromisoformat(form["due_date"].strip())
            except ValueError:
                errors["due_date"] = "Enter a date like 2026-12-15, or leave it empty."
        priority = form.get("priority", "medium")
        if item.kind == "action" and priority not in ("low", "medium", "high"):
            errors["priority"] = "Choose a priority."
        if not errors:
            item.text = text
            if item.kind == "decision":
                item.detail = detail
            if item.kind == "action":
                if due != item.due_date:
                    item.due_phrase = None  # the meeting's words no longer describe the new date
                item.owner, item.due_date, item.priority = owner, due, priority
            item.edited = True
            item.review = "accepted"  # you wrote it yourself
            meeting.updated_at = utcnow()
            s.commit()
            flash(f"The {KIND_WORDS[item.kind]} is saved.")
            return back_to(meeting, item)
    lines = {line.n: line for line in meeting.lines}
    return render_template("item_edit.html", item=item, meeting=meeting, errors=errors, form=request.form,
                           kind_word=KIND_WORDS[item.kind], owners=owner_choices(meeting, item.owner),
                           lines=lines), 400 if errors else 200
