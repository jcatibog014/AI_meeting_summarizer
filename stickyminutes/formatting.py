"""Small helpers that turn values into words on the page (Jinja filters)."""
from datetime import datetime

from flask import g

from . import pricing
from .dates import to_zone, utcnow


def _zone():
    workspace = g.get("workspace")
    return workspace.time_zone if workspace is not None else None


def day(value):
    """A date as 'Tue, 24 Nov 2026'."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = to_zone(value, _zone()).date()
    return f"{value.strftime('%a')}, {value.day} {value.strftime('%b %Y')}"


def short_day(value):
    """A date as '24 Nov' (this year) or '24 Nov 2025'."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = to_zone(value, _zone()).date()
    words = f"{value.day} {value.strftime('%b')}"
    return words if value.year == utcnow().year else f"{words} {value.year}"


def when(moment):
    """A UTC moment as local '24 Nov, 3:05 PM'."""
    if moment is None:
        return ""
    local = to_zone(moment, _zone())
    return f"{short_day(local.date())}, {local.strftime('%I:%M %p').lstrip('0')}"


def ago(moment):
    if moment is None:
        return ""
    seconds = max(0, int((utcnow() - moment).total_seconds()))
    if seconds < 60:
        return "just now"
    for size, word in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {word}{'s' if n != 1 else ''} ago"
    return "just now"


def number(value):
    return f"{value or 0:,}"


def seconds(value):
    """1.234 -> '1.2 s'; 75 -> '1 min 15 s'."""
    if value is None:
        return ""
    if value < 60:
        return f"{value:.1f} s"
    minutes, rest = divmod(int(value), 60)
    return f"{minutes} min {rest} s"


def percent(value):
    """0.8333 -> '83%'; None -> a dash (the number means nothing here)."""
    return "–" if value is None else f"{round(value * 100)}%"


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def init_app(app):
    app.jinja_env.filters.update(day=day, short_day=short_day, when=when, ago=ago, number=number,
                                 dollars=pricing.dollars, cents=pricing.cents, seconds=seconds,
                                 percent=percent)
    app.jinja_env.globals.update(plural=plural)
