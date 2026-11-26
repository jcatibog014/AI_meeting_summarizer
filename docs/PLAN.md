# Sticky Minutes — AI Meeting Summarizer (plan)

## Context

A new Workspace learning project. Skills to practise: **LLM APIs, structured outputs, validation**.
It turns a meeting transcript into a short summary, key points, decisions, action items and open
questions, and checks Claude's answer before saving it.

What you chose:
- **Name:** "Sticky Minutes" — "The meeting stuck. Here's what matters." Package `stickyminutes`, local port **5016**, cookie `stickyminutes_session`.
- **Access:** you (the owner) summarize freely. **Try Demo** shows ready-made sample meetings, and each visitor can run **3 real summaries a day**. A **daily spending cap** covers the whole site.
- **Extras:** all four groups: Review & Proof, Action Tracker, Export & Share, Quality Lab.
- **Look:** "Sticky notes".
- **PRs:** one PR, with a commit per stage and no stops.
- **Transcription is out:** no audio and no meeting bot. Input is text only: you paste it, or upload a Zoom, Meet or Teams `.vtt` file, or a `.srt`, `.txt` or `.docx` file.

Stack, as in Akda and Paper Plane: Flask, SQLAlchemy 2.0 + Alembic, SQLite locally, Neon live, Render, pytest, `.venv`, and an `AGENTS.md` with `CLAUDE.md` pointing to it. New: the `anthropic` Python SDK, `pydantic` and `python-docx`.

## How the LLM part works (the core of the project)

**Model call** (`stickyminutes/llm.py`):
- `client.messages.parse(model="claude-opus-5-5", output_format=MeetingNotes, output_config={"effort": "medium"}, max_tokens=16000)`.
- Adaptive thinking is always on with Opus 5.5. Effort is set explicitly.
- **Refusal fallback** is on by default: beta `server-side-fallback-2026-07-01` with `fallbacks: "default"`. Stage 3 checks that `client.beta.messages.parse` accepts it. If it doesn't, we use beta `create` with `output_config.format` set from `MeetingNotes.model_json_schema()` and validate the result with Pydantic ourselves.
- We always check `stop_reason` (`refusal`, `max_tokens`) before reading the output.
- Errors are caught from the most specific to the least: RateLimit → APIStatus → APIConnection. Each gives a friendly message and is saved on the run.
- The transcript block is cached (`cache_control`), so repair retries are cheap.
- `count_tokens` runs before the call. It turns down transcripts that are too long and gives the cost estimate shown on the Summarize button.
- `FakeClaude` follows the same interface and returns scripted answers, some of them deliberately wrong. It is used by every test and the demo samples, so the test suite never uses the network.

**The output shape** (`stickyminutes/schema.py`, Pydantic):
```
MeetingNotes: title, overview (2–4 sentences),
  key_points[], decisions[{text, rationale?}], action_items[{task, owner?, due_phrase?, due_date?, priority: low|medium|high}],
  open_questions[]   — every item carries evidence: [{line: int, quote: str}]
```

**Three layers of validation:**
1. **Schema**: structured outputs guarantee the JSON shape.
2. **Pydantic**: types, enums, lengths, ISO dates, no blank strings, and limits on list sizes.
3. **Grounding and business checks** (`stickyminutes/checks.py`):
   - each quote really is in the transcript, compared after normalising spaces and case;
   - line numbers are in range;
   - each owner is a speaker in the meeting, or else "Unassigned";
   - a due date is not before the meeting date;
   - a phrase like "next Friday" is worked out from the meeting date;
   - duplicate items are merged;
   - an empty meeting gives empty lists, not made-up items.

**Repair loop** (`stickyminutes/summarize.py`):
- If a check fails, the list of problems goes back to Claude as a follow-up turn: "fix these, return the whole JSON". This happens at most 2 times.
- Whatever still fails after that is saved as **Needs review** with the reason, never dropped silently.
- Every problem is logged in `run_issues`: the attempt, the layer, the path and the message.

**Runs:**
- A run happens in a background thread, and the meeting page asks every 2 s how it is going.
- A run is `queued → running → done | needs_review | failed`.
- Each run stores the model, the prompt version, the tokens (including cache reads), the cost in cents (from `pricing.py`), the time taken, the stop reason and the raw output.
- Prompts are versioned files (`stickyminutes/prompts/v1.md`), so the Quality Lab can compare them.

**Spending guard** (`stickyminutes/budget.py`):
- A `usage_ledger` records each run's cost.
- Before each call it checks the demo visitor's 3 runs a day and the site's daily cap (`DAILY_CAP_CENTS`, default $1).
- If `ANTHROPIC_API_KEY` isn't set, the app runs in a clearly labelled **practice mode** with FakeClaude.

## Data (main tables)

| Table | What it holds |
|---|---|
| `users` | the owner (`create-owner`) and demo visitors (`is_demo`, random `session_version`) |
| `meetings` | the title, date, source kind and transcript, plus `share_token_nonce` |
| `transcript_lines` | one row per line: number, speaker, time and text |
| `runs`, `run_issues` | each Claude call and every validation problem it had |
| `notes` | the overview and key points (JSON) for the accepted run |
| `decisions`, `action_items`, `open_questions` | the items, their evidence lines, their review state, and whether you edited them |
| `usage_ledger` | the spending guard |
| `eval_cases`, `eval_results` | the Quality Lab test set |

Every foreign key to a parent that gets deleted in bulk has an index that starts with that column. This was a lesson from Tally Ho!. `sqlite_autoincrement` is on for `users` and `meetings`.

## Stages (one PR, branch `build-sticky-minutes`, a commit per stage)

1. **Setup**:
   - app factory, config, `db.py` + Alembic, `flask upgrade-db`;
   - `create-owner`, login, the per-visitor Try Demo shell (deleted after 24 h);
   - Settings (theme, Log out, model choice with Opus 5.5 as the default), the sidebar;
   - the sticky notes look;
   - `AGENTS.md`/`CLAUDE.md`, `.env.example`.
2. **Transcripts**:
   - `transcripts.py` reads pasted text, `.vtt`, `.srt`, `.txt` and `.docx` into numbered lines and finds the speakers;
   - input checks: empty, too large, encoding, and a token count;
   - a meetings list and a transcript view.
3. **LLM core**: `llm.py` (real and fake), `schema.py`, prompt v1, `summarize.py` runs with status polling, cost recording, the refusal fallback, the error chain, and `budget.py`.
4. **Validation and repair**: `checks.py`, the repair loop, `run_issues`, Needs review, and working out relative dates. This stage has the largest set of tests, driven by FakeClaude's bad answers.
5. **Notes page + Review & Proof**:
   - sticky note columns: green Key Points, blue Decisions, yellow Actions, pink Open Questions;
   - each note has a "line 42" chip that scrolls to and highlights the line in the transcript beside it;
   - a tick when a quote is found, a flag when it isn't;
   - edit, accept or reject each note, and Run again.
6. **Action Tracker**: `/actions` across all meetings, with filters for owner, status and due date, Mark done, an Overdue list, and a signed `.ics` calendar feed of due dates.
7. **Export & Share**:
   - Markdown and Word (`python-docx`) downloads;
   - a print page for "Save as PDF" (no PDF library);
   - Copy as email;
   - a read-only share link `/s/<token>`, where the token is HMAC(SECRET_KEY, id:nonce) and can be turned off.
8. **Quality Lab** (owner):
   - a runs table with attempts, problems, tokens, cost and time;
   - a problems log grouped by check;
   - a test set of 6 transcripts with the expected decisions and actions;
   - "Run test set" scores each prompt version or model on recall, grounding rate and the share that pass on the first try. It costs money, so it asks first and shows the estimate.
9. **Demo + finish**:
   - 6 sample meetings (stand-up, client call, sprint planning, retro, one-on-one, budget review). Their results are scripted and go through the real checks: one has a flagged item, one needed a repair, and every page has content;
   - a test that fails if a demo page is empty;
   - `render.yaml` (service `sticky-minutes`), `docs/DEPLOY.md`, `docs/PLAN.md`;
   - an app icon and a README with screenshots.

## Look: "Sticky notes"

- **Board:** warm off-white with a faint dot grid. In dark mode it is a deep slate with muted notes.
- **Notes:** four soft colours, each slightly tilted (±1°), with a soft shadow.
- **Fonts:** Kalam for headings and note titles, Nunito for body text, both self-hosted with Fontsource.
- **Accent:** marker blue for buttons.
- **Layout:**
  - controls line up, with very few emoji;
  - the theme switch and Log out are in Settings only;
  - toasts are bottom-right;
  - page titles have no line of text under them;
  - phone layouts fit the screen with no sideways scrolling.

Chart and note colours are checked with the dataviz validator.

## What you do

- ~~Make the GitHub repo~~ Done: https://github.com/jcatibog014/AI_meeting_summarizer. **First step after approval:** I clone it into a new folder, `C:\Users\USER\Documents\Workspace\AI_meeting_summarizer`, and create the branch `build-sticky-minutes` from `main` (the repo already has commits on `main`).
- Get an Anthropic API key from the Console and put it in `.env` as `ANTHROPIC_API_KEY`. It must never be committed. Until it is there, the app runs in practice mode.
- Later, go live with Neon, the Render Blueprint `sticky-minutes`, `create-owner` from your PC, and the key in Render's settings.

## Verification

- `pytest` with FakeClaude, no network:
  - transcript parsers on real-looking Zoom, Meet and Teams `.vtt` files;
  - each check layer;
  - the repair loop (fixed on retry, still bad after 2 retries goes to Needs review);
  - refusal and max_tokens handling;
  - budget caps;
  - the share token;
  - `.ics`;
  - the demo has no empty pages;
  - index coverage.
- **One real smoke test**, only with your OK because it costs a few cents: `flask try-claude --sample standup` runs a sample through Opus 5.5 and prints the tokens, cost, attempts and problems.
- Run the app on 5016 with `--debug` and click through as the owner and as the demo. Playwright screenshots (borrowed from the expense_tracker `.venv`) go into the README.
- Report the tests as SQLite-only unless they run on a Neon branch.

## Progress

- [x] Stage 1: setup, owner login, Try Demo, Settings, the sticky notes look
- [x] Stage 2: transcripts
- [x] Stage 3: LLM core
- [x] Stage 4: validation and repair
- [x] Stage 5: notes page + Review & Proof
- [x] Stage 6: Action Tracker
- [x] Stage 7: Export & Share
- [x] Stage 8: Quality Lab
- [ ] Stage 9: demo + finish

## Where the Build Differs

- **No `messages.parse`:** the SDK's `parse()` checks Claude's JSON with Pydantic itself and raises on a failure, which throws away the raw answer the repair turn needs. So `llm.py` calls `client.beta.messages.create(...)` with `output_config.format` set from `anthropic.transform_schema(MeetingNotes)` (layer 1, the API), and `schema.py` validates the text with Pydantic itself (layer 2). The beta endpoint is used for the refusal fallback (`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`), which the installed SDK (2.14) accepts.
- **One `eval_runs` table, cases in code:** the plan named `eval_cases` and `eval_results` tables. The six test meetings are fixed, so they live in `evals.py` (reviewed like code), and each run keeps its per-case scores as JSON in `eval_runs.results`.
- **A prompt choice in Settings:** not in the plan; added so the Quality Lab's comparison of v1 and v2 can be acted on.
