# AGENTS.md

This file guides AI coding agents (Claude Code, Codex, Cursor, Copilot and others) working in this repository.

## Overview

**Sticky Minutes** ("The meeting stuck. Here's what matters."), an AI meeting summarizer in Python (Flask). The repo is `AI_meeting_summarizer` and the Python package is `stickyminutes`. You paste or upload a meeting transcript; Claude turns it into a summary, key points, decisions, action items and open questions; the app CHECKS the answer before it is saved. The plan is `docs/PLAN.md`.

It is a learning project for **LLM APIs, structured outputs and validation**, so those parts stay easy to read: short comments that explain *why*, the official `anthropic` SDK, Pydantic for the answer's shape, checks written by hand, and no extra libraries unless the owner asks for them. Write the README in simple (A1-level) English.

Python 3.13 is at `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`. Use the virtual environment:

- Install: `.venv\Scripts\python -m pip install -r requirements.txt` (create `.venv` with `python -m venv .venv` first if it's missing).
- First time: `.venv\Scripts\flask --app stickyminutes upgrade-db` (makes the tables), then `.venv\Scripts\flask --app stickyminutes create-owner` (your login). Or click Try the demo.
- Claude: put `ANTHROPIC_API_KEY=...` in `.env` (git ignores it; copy `.env.example`). Without a key the app runs in **practice mode** (`llm.FakeClaude`), and every page says so.
- Run: `.venv\Scripts\flask --app stickyminutes run --debug --port 5016`, then open http://127.0.0.1:5016. (Ports: Swap Meter 5000, Ambon Alert 5001, Ang Gastos! 5002, Sangkap 5003, Gawi 5004, Akda 5005, Hire Wire 5006, Plan-It 5007, ShiroMoto 5008, DFJC 5009, Ticket Tock 5010, Tally Ho! 5011, J: Drive 5012, Right On Cue 5013, Pulse Check 5014, Paper Plane 5015.)
- Test: `.venv\Scripts\python -m pytest`. Every test gets a fresh SQLite file and **never calls Claude or the internet** (`ANTHROPIC_API_KEY` is empty in tests, so `FakeClaude` answers). Set `TEST_DATABASE_URL` to an **empty** PostgreSQL database to run the same tests there. SQLAlchemy warnings fail the tests (`pytest.ini`).
- Other commands: `set-password <email>`, `purge-demos`.

## Architecture

- **The login cookie is `stickyminutes_session`, not Flask's `session`:** browsers keep cookies per host, not per port, so the owner's other Flask apps on 127.0.0.1 would overwrite it (`tests/test_auth.py::test_the_login_cookie_has_its_own_name`).
- **Accounts (`auth.py`):** no sign-up, because every summary is a paid Claude call on the owner's key. The OWNER is made from the PC (`create-owner`), logs in by email, and has the one real workspace. Hashes from Werkzeug; 5 wrong passwords lock the account for 15 minutes, one address may try 30 logins per 15 minutes (`limits.py`). `load_user()` checks `session_version` (a password change logs out every other cookie) and a demo's expiry, and puts `g.user` / `g.workspace` on the request.
- **Demo (`seed.py`, `views/demo.py`):** Try Demo makes a sandbox `Workspace` ("Kape Cloud Meetings") with one person, Lea Ramos. Nobody can log in to a demo with a password; demo users start with a random `session_version`; `workspaces` and `users` use `sqlite_autoincrement`, so a deleted demo's ids are never handed out again. Demos are deleted after 24 hours (`seed.purge`, on every Try Demo click and by `purge-demos`). At most 20 at once, 10 per network an hour (not with `--debug`). **Every page the demo can open must show an example, so add sample data with every new feature** (`seed.fillers`).
- **Settings (`views/settings.py`):** your account, the workspace (name, time zone), the Claude model (`pricing.MODELS`: Opus 5.5 by default, Sonnet 5.5, Haiku 5.5), the theme and Log out. Later modules add sections with `actions` / `extras`.
- **Database:** SQLAlchemy 2.0 ORM (typed `Mapped[...]`), plain (not Flask-SQLAlchemy). `db.py` makes one engine per app and one session per request: `db.session()`; code outside a request (the summarizing thread) uses `db.new_session()` and closes it. SQLite locally (`instance/stickyminutes.sqlite`, WAL), PostgreSQL (**Neon**, psycopg 3) when `DATABASE_URL` is set. **Money is in micro-dollars** (an int; `pricing.py`).
- **Migrations: Alembic**, in `stickyminutes/migrations/`. `flask --app stickyminutes upgrade-db` runs them (with SQLite's foreign keys off during the run, so a table rebuild can't cascade-delete rows); Render runs it before gunicorn.
  - **To change the schema:** edit `models.py`, then `.venv\Scripts\alembic revision --autogenerate -m "what changed" --rev-id 000N`, **read the new file and fix it** (booleans default to `sa.true()` / `sa.false()`, never `sa.text('1')`; a new NOT NULL column needs a `server_default`), and commit it. `tests/test_migrations.py` fails if the models and the migrations disagree.
  - Every foreign key to a parent that is deleted in bulk (`ON DELETE CASCADE` / `SET NULL`) needs an index that STARTS with that column (`test_bulk_deleted_parents_have_an_index_for_each_child`).
- **Every page works without JavaScript.** `app.js` only adds extras. The CSP has no inline scripts or styles, so **never use `style=""` or inline `<script>`** (`tests/test_look.py`).
- Commit messages and PR bodies go through files (`git commit -F`, `gh pr create --body-file`): PowerShell 5.1 breaks quotes in arguments.

## UI rules (the owner's priority is neatness)

- **Look: "Sticky notes".** A warm paper board with a faint dot grid (`--board`, `--board-dot`); notes in four soft colours, each a little tilted: green Key Points, blue Decisions, yellow Action Items, pink Open Questions (`--note-*`); Kalam (a marker hand) for headings, Nunito for text, both self-hosted in `static/fonts/` (Fontsource 5); marker blue buttons (`--accent`); page titles have a yellow highlighter swipe (`.marker`). The logo is two sticky notes (`_icons.html logo()`, the same picture as `static/icons/logo.svg`). Dark mode (a deep slate board with muted notes) is defined twice in `style.css` (device setting + the choice in Settings); change both blocks together. `tests/test_look.py` checks both themes for 4.5:1 text (on every note colour too) and 3:1 control edges.
- **Settings holds the controls, and the menus only navigate.** The theme and Log out are in Settings only; the menu's bottom row (your name) opens Settings.
- **Messages are toasts** (`_toasts.html`, bottom right): `flash(msg)` fades after 6 seconds; `flash(msg, "error")` stays until closed.
- **No decorative emoji.** Icons are the line SVGs in `_icons.html`.
- **Page titles are bare:** `page_head(title)` from `_macros.html`, with no line of text under the title.
- **Title Case** for the menu, page titles, section headings, tabs and empty-state titles. **Sentence case** for everything else: buttons ("New meeting", "Run again"), labels, hints, messages. The main button of a page is last on the right.
- Controls are the same height (`--control-height`). Sizes in `rem`; the root font steps up at 1600 / 1920 / 2300px. Tabs are pills that wrap, never a sideways scroll. Phone layouts fit the screen with no sideways scrolling.
- The sidebar shows from 56rem up; below that, a top bar with a Menu button.
