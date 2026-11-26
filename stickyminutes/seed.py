"""Try Demo: a sandbox workspace for one visitor, deleted after 24 hours.

The visitor is "Lea Ramos", who runs the meetings at Kape Cloud, a small
coffee subscription company. Nobody can log in to a demo with a password:
Try Demo logs the browser straight in (views/demo.py), and the user starts
with a random session_version, so an old cookie never fits a new demo.

Deleting the workspace deletes everything in it (ON DELETE CASCADE), except
the spending ledger's rows, which keep counting towards the site's daily cap
(budget.py).
"""
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select
from werkzeug.security import generate_password_hash

from .models import User, Workspace

DEMO_LIFETIME = timedelta(hours=24)
MAX_DEMOS = 20
DEMO_NAME = "Lea Ramos"
DEMO_COMPANY = "Kape Cloud"
# Later stages add their sample data: function(s, workspace, me, moment)
fillers = []


def count(s):
    return s.scalar(select(func.count()).select_from(Workspace).where(Workspace.is_demo.is_(True)))


def purge(s, moment):
    """Delete every demo past its time. Called on each Try Demo click and by purge-demos."""
    old = s.scalars(select(Workspace.id).where(Workspace.is_demo.is_(True),
                                               Workspace.demo_expires_at <= moment)).all()
    if old:
        s.execute(delete(Workspace).where(Workspace.id.in_(old)))
    return len(old)


def build(s, moment):
    """A new demo workspace with its sample meetings. Returns the visitor (a User). The caller commits."""
    workspace = Workspace(name=f"{DEMO_COMPANY} Meetings", is_demo=True,
                          demo_expires_at=moment + DEMO_LIFETIME, created_at=moment)
    s.add(workspace)
    s.flush()
    me = User(workspace=workspace, name=DEMO_NAME, is_demo=True,
              # An address no one can own (.invalid) and a password no one knows.
              email=f"demo{workspace.id}.{secrets.token_hex(4)}@kapecloud.invalid",
              password_hash=generate_password_hash(secrets.token_urlsafe(24)),
              session_version=secrets.randbelow(1_000_000) + 2, created_at=moment)
    s.add(me)
    s.flush()
    for fill in fillers:
        fill(s, workspace, me, moment)
    return me


def init_app(app):
    import click
    from flask.cli import with_appcontext

    from . import db
    from .dates import utcnow

    @click.command("purge-demos")
    @with_appcontext
    def purge_demos_command():
        """Delete demos older than 24 hours."""
        s = db.session()
        gone = purge(s, utcnow())
        s.commit()
        click.echo(f"Deleted {gone} old demo{'s' if gone != 1 else ''}.")

    app.cli.add_command(purge_demos_command)
