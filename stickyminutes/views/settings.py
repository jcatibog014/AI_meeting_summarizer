"""Settings: your account, the workspace (name, time zone, which Claude model), and the look.

Settings holds every control and preference (the theme, Log out); the menus
only take you to pages. Later stages add sections through `actions` and `extras`.
"""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .. import db, pricing
from ..auth import login_required, name_problem, not_for_demo, password_problem, set_password
from ..dates import is_zone, zone_names

bp = Blueprint("settings", __name__)
# Sections that later modules add: action name -> function(s, workspace, form) -> (errors, message)
actions = {}
# Extra things the page shows: function(s, workspace) -> dict
extras = []


def zone_choices():
    """Every time zone, as "Asia/Manila", sorted (the ones with a "/" are the real places)."""
    return sorted(name for name in zone_names() if "/" in name and not name.startswith(("Etc/", "SystemV/")))


def save_workspace(s, workspace, form):
    errors = {}
    name = " ".join(form.get("name", "").split())
    zone_name = form.get("time_zone", "").strip()
    if problem := name_problem(name, "a name for the workspace"):
        errors["name"] = problem
    if not is_zone(zone_name):
        errors["time_zone"] = "Choose a time zone from the list."
    if errors:
        return errors, None
    workspace.name, workspace.time_zone = name, zone_name
    return {}, "The workspace is saved."


def save_model(s, workspace, form):
    choice = form.get("model", "")
    if choice not in pricing.MODELS:
        return {"model": "Choose a model from the list."}, None
    workspace.model = choice
    return {}, f"New summaries will use {pricing.MODELS[choice].label}."


actions["workspace"] = save_workspace
actions["model"] = save_model


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def page():
    s = db.session()
    errors = {}
    if request.method == "POST":
        action = request.form.get("action")
        if action == "name":
            not_for_demo("The demo can't change its account.")
            name = " ".join(request.form.get("user_name", "").split())
            if problem := name_problem(name):
                errors["user_name"] = problem
            else:
                g.user.name = name
                s.commit()
                flash("Your name has been changed.")
                return redirect(url_for("settings.page"))
        elif action == "password":
            not_for_demo("The demo can't change its account.")
            if not check_password_hash(g.user.password_hash, request.form.get("current_password", "")):
                errors["current_password"] = "That isn't your current password."
            new = request.form.get("new_password", "")
            if problem := password_problem(new, request.form.get("confirm_password", "")):
                errors["new_password"] = problem
            if not errors:
                set_password(g.user, new)
                s.commit()
                session["session_version"] = g.user.session_version  # this device stays logged in
                flash("Your password has been changed. Your other devices are logged out.")
                return redirect(url_for("settings.page"))
        elif action in actions:
            errors, message = actions[action](s, g.workspace, request.form)
            if not errors:
                s.commit()
                flash(message)
                return redirect(url_for("settings.page", _anchor=request.form.get("anchor") or None))
            s.rollback()
        else:
            abort(400, "Choose something to change.")
    data = {"settings_sections": []}
    for extra in extras:
        found = extra(s, g.workspace)
        data["settings_sections"] += found.pop("settings_sections", [])
        data.update(found)
    return render_template("settings.html", errors=errors, form=request.form, zones=zone_choices(),
                           models=pricing.MODELS.values(), **data), 400 if errors else 200
