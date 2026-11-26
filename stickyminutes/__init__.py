"""Sticky Minutes, an AI meeting summarizer. "The meeting stuck. Here's what matters."

Paste or upload a meeting transcript, and Claude turns it into a short
summary, key points, decisions, action items and open questions. Then the
app CHECKS the answer before saving it: the shape (schema.py), the rules
(Pydantic), and that every note really comes from the transcript
(checks.py). See llm.py and summarize.py for the LLM part.

Flask builds the app inside create_app() (the "app factory" pattern).
Tests call it with their own settings, so each test gets a fresh app and database.
"""
import os
from datetime import timedelta
from pathlib import Path

from flask import Flask, g, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

APP_NAME = "Sticky Minutes"
TAGLINE = "The meeting stuck. Here's what matters."
DEV_SECRET_KEY = "dev-only-not-secret"
LOCAL_PORT = 5016


def content_security_policy():
    """What the browser may load. Scripts, styles and fonts come only from this
    site, so even if a transcript had a <script> in it, the browser would refuse to run it."""
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "font-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    on_render = bool(os.environ.get("RENDER"))  # Render sets RENDER=true on its servers
    app.config.from_mapping(
        # Signs the login cookie, share links and the calendar feed.
        SECRET_KEY=os.environ.get("SECRET_KEY", DEV_SECRET_KEY),
        # Local SQLite file, in the instance/ folder (git ignores it).
        DATABASE=str(Path(app.instance_path) / "stickyminutes.sqlite"),
        # Set on the live site: then we use PostgreSQL (Neon) instead of SQLite.
        DATABASE_URL=os.environ.get("DATABASE_URL"),
        ON_RENDER=on_render,
        BASE_URL=os.environ.get("BASE_URL", f"http://127.0.0.1:{LOCAL_PORT}").rstrip("/"),
        # Claude. Without a key the app runs in practice mode (llm.FakeClaude), clearly labelled.
        ANTHROPIC_API_KEY=os.environ.get("ANTHROPIC_API_KEY", ""),
        # The most the whole site may spend on Claude in one day (UTC), in US cents.
        DAILY_CAP_CENTS=env_int("DAILY_CAP_CENTS", 100),
        # Real summaries a demo visitor may run in a day.
        DEMO_RUNS_PER_DAY=env_int("DEMO_RUNS_PER_DAY", 3),
        # Summaries run in a background thread. Tests run them straight away instead.
        RUN_IN_THREAD=True,
        # The login cookie has its own name. Browsers keep cookies per HOST, not per port,
        # and every Flask app calls its cookie "session": the owner's other apps on
        # 127.0.0.1 (ports 5000-5015) would overwrite Sticky Minutes' login.
        SESSION_COOKIE_NAME="stickyminutes_session",
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=on_render,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        # A transcript upload is at most 2 MB (transcripts.py says so nicely).
        MAX_CONTENT_LENGTH=3 * 1000 * 1000,
    )
    if test_config:
        app.config.update(test_config)
    if app.testing:
        app.config["RUN_IN_THREAD"] = bool(test_config and test_config.get("RUN_IN_THREAD"))
    if on_render:
        # Render's proxy talks HTTPS to the visitor and HTTP to us: believe its X-Forwarded-* headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        if app.config["SECRET_KEY"] == DEV_SECRET_KEY:
            raise RuntimeError("Set the SECRET_KEY environment variable on Render.")
        if not app.config["DATABASE_URL"]:
            raise RuntimeError("Set the DATABASE_URL environment variable on Render (Neon's connection string).")

    from . import auth, db, formatting, seed
    from .views import demo, meetings, settings, summaries

    db.init_app(app)
    auth.init_app(app)
    formatting.init_app(app)
    seed.init_app(app)
    # auth comes first: its before_request (load_user) must run before the others'.
    for blueprint in (auth.bp, meetings.bp, summaries.bp, settings.bp, demo.bp):
        app.register_blueprint(blueprint)

    from .dates import utcnow
    app.jinja_env.globals.update(APP_NAME=APP_NAME, TAGLINE=TAGLINE, now=utcnow,
                                 has_page=lambda endpoint: endpoint in app.view_functions)

    @app.get("/healthz")
    def healthz():
        return "ok"

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("Content-Security-Policy", content_security_policy())
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if g.get("user") is not None:
            # Pages with someone's meetings on them are never kept by the browser or a proxy.
            response.headers.setdefault("Cache-Control", "no-store")
        if on_render:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    def error_page(code, message):
        return render_template("error.html", code=code, message=message), code

    @app.errorhandler(400)
    def bad_request(error):
        return error_page(400, error.description or "Something in that request was wrong.")

    @app.errorhandler(403)
    def forbidden(error):
        return error_page(403, error.description or "You can't do that.")

    @app.errorhandler(404)
    def not_found(error):
        return error_page(404, "We couldn't find that. It may have been deleted, or it isn't yours to see.")

    @app.errorhandler(409)
    def conflict(error):
        return error_page(409, error.description or "That can't be done right now.")

    @app.errorhandler(413)
    def too_big(error):
        return error_page(413, "That file is too big. A transcript can be at most 2 MB.")

    @app.errorhandler(429)
    def too_many(error):
        return error_page(429, error.description or "Too many tries. Please wait a little and try again.")

    return app
