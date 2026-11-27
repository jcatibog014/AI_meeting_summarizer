# Sticky Minutes

**The meeting stuck. Here's what matters.** An AI meeting summarizer.

You give it the words of a meeting (a transcript). Claude, an AI, writes the minutes: a short summary, the key points, the decisions, the action items (who does what, by when) and the open questions. Then the app **checks** every note. Each note must point at the transcript line it comes from, and the app makes sure those words are really there.

![A meeting's notes as sticky notes](docs/screenshots/meeting.png)

## Try It

Open the app and click **Try the demo**. You are Lea, who runs the meetings at Kape Cloud, a small coffee company. Six sample meetings are already there. Their notes are **samples written for the demo** (not made by Claude), but they went through the same checks. You can also summarize up to 3 meetings of your own each day with the real Claude. The demo is only for you, and it is deleted after 24 hours.

![The login page with Try the demo](docs/screenshots/login.png)

## What It Can Do

| Part | What you can do |
| --- | --- |
| Transcripts | Paste a transcript, or upload a file from Zoom, Google Meet or Teams (.vtt), subtitles (.srt), text (.txt) or Word (.docx). Each line gets a number. |
| Summary | One click: Claude writes the summary, key points, decisions, action items and open questions. |
| Checks | The app checks the answer in three layers: the shape, the rules, and the transcript. If something is wrong, it sends the problems back to Claude to fix (at most 3 tries). |
| Proof | Every note shows its line numbers. Click one and the transcript line lights up. A tick means the quote was found; a red mark means it wasn't. |
| Review | Accept, reject or edit each note. You see how many notes you have checked. |
| Action Items | All action items from all meetings in one list: owner, due date, priority, overdue. Tick one when it is done. |
| Calendar | A private calendar link: the due dates show in Google Calendar, Outlook or Apple Calendar. |
| Export | Download Word or Markdown, print or save as PDF, or copy the minutes into an email. |
| Share | A read-only link to the minutes, for people without a login. You can turn it off. |
| Quality Lab | See every try, every problem the checks found, the tokens and the cost. Run a test set of 6 meetings to compare prompts and models. |
| Money | A daily spending limit for the whole site. Without an API key, the app runs in free practice mode. |
| Look | Sticky notes on a dotted board, in light or dark. Works on phones. |

## Pictures

### The Meetings Board

Every meeting is a card. The tag says if it is summarized or needs a look.

![The meetings board](docs/screenshots/meetings.png)

### Notes and Proof

Open "Proof" on a note to see the exact words it comes from. Click a line number and that line lights up in the transcript.

![A note with its proof open](docs/screenshots/proof.png)

![The transcript with a line lit up](docs/screenshots/transcript-line.png)

### When a Check Fails

Here one quote was never found, even after the fixes. The note keeps a flag, so you read it before you trust it.

![A meeting that needs review](docs/screenshots/needs-review.png)

You can edit any note. The proof is beside the form.

![Editing a note](docs/screenshots/edit-note.png)

### A New Meeting

Upload a file or paste the words. The page says where to find a transcript in Zoom, Google Meet and Teams.

![The New Meeting page](docs/screenshots/new-meeting.png)

### Action Items

All action items in one list, with Open, Overdue, Done and All tabs, and a filter by person.

![The Action Items page](docs/screenshots/actions.png)

![Overdue action items](docs/screenshots/actions-overdue.png)

### Export and Share

![Export and Share on a meeting](docs/screenshots/export.png)

![The minutes as text for an email](docs/screenshots/email.png)

The shared page shows only the minutes, not the transcript.

![The shared minutes](docs/screenshots/shared.png)

### Quality Lab

How the summaries went: tries, problems, tokens, cost and time.

![The Quality Lab runs](docs/screenshots/lab.png)

One run, try by try. Here the first answer pointed a quote at the wrong line; the second try fixed it.

![One run's checks](docs/screenshots/lab-run.png)

Which mistakes the checks catch most often, and how often a fix works.

![The problems page](docs/screenshots/lab-problems.png)

The test set: 6 meetings with known answers. Compare two prompts or two models.

![The test set](docs/screenshots/lab-tests.png)

![One test run](docs/screenshots/lab-test-run.png)

### Settings

Your account, the workspace, the Claude model, the prompt, the theme, and Log out.

![Settings](docs/screenshots/settings.png)

### Dark Mode and Phones

![A meeting in dark mode](docs/screenshots/dark-meeting.png)

<p>
  <img src="docs/screenshots/phone-meetings.png" alt="The meetings on a phone" width="260">
  <img src="docs/screenshots/phone-meeting.png" alt="A meeting on a phone" width="260">
  <img src="docs/screenshots/phone-actions.png" alt="Action items on a phone" width="260">
</p>

## How the Checks Work

Claude's answer passes three layers before it is saved:

| Layer | What it checks | Who checks |
| --- | --- | --- |
| 1. Shape | The answer is JSON with every field, the right types, and no extra fields. | The Claude API itself ("structured outputs"), from a schema made with Pydantic. |
| 2. Rules | Lengths, number ranges, no empty text, at most 4 or 5 sentences in the summary. | Pydantic, in Python. |
| 3. Transcript | Each quote is really on its line. Each owner is a person in the meeting. Due dates are not before the meeting. "By Friday" becomes a real date. | The app's own code (`checks.py`). |

If a layer finds problems, the app sends them back to Claude: "Your answer had these problems... return the whole answer again." After 3 tries, a note that is still wrong gets a flag. It is never quietly dropped.

## Tools

| Tool | What it does here |
| --- | --- |
| Python 3.13 | The language of the app. |
| Flask | The web app: pages, forms and links. |
| Claude API (`anthropic`) | Claude Opus 5.5 (or Sonnet 5.5, Haiku 5.5) writes the notes. |
| Pydantic | Describes the answer's shape and checks its rules. |
| SQLAlchemy and Alembic | The database tables, and changes to them over time. |
| SQLite and PostgreSQL | SQLite on your computer; PostgreSQL (Neon) on the live site. |
| python-docx | Reads Word transcripts and makes the Word download. |
| HTML, CSS and JavaScript | The pages and the sticky notes look. The pages also work without JavaScript. |
| pytest | The tests (167 of them). They never call Claude: a stand-in answers. |
| Render and Neon | The free web server and database for the live site. |

## Run It on Your Computer

```
cd C:\Users\USER\Documents\Workspace\AI_meeting_summarizer
```

```
python -m venv .venv
```

```
.venv\Scripts\python -m pip install -r requirements.txt
```

```
.venv\Scripts\flask --app stickyminutes upgrade-db
```

```
.venv\Scripts\flask --app stickyminutes create-owner
```

```
.venv\Scripts\flask --app stickyminutes run --debug --port 5016
```

Then open http://127.0.0.1:5016. To use the real Claude, copy `.env.example` to `.env` and put your API key in it. Without a key, summaries are free practice notes.

To test: `.venv\Scripts\python -m pytest`

To put it on the Internet, read [docs/DEPLOY.md](docs/DEPLOY.md).
