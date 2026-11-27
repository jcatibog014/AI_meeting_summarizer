# Put Sticky Minutes on the Internet

Sticky Minutes runs on **Render** (the web server) and **Neon** (the PostgreSQL database). Both have free plans. Claude needs an **Anthropic API key**, which is paid by use. You need about 30 minutes.

Never paste a password, an API key or a connection string into a chat, an issue or a commit. Keep them only in Render and on your PC.

## Part 1: The Claude API Key

1. Go to https://platform.claude.com and log in.
2. Open **Billing** and add a little credit (for example $5). One summary with Claude Opus 5.5 costs about 3 to 10 cents.
3. Open **API keys** and click **Create key**. Name it `sticky-minutes`. Copy the key (it starts with `sk-ant-`). You see it only once.
4. On your PC, make a file called `.env` in the project folder (copy `.env.example`) and put the key after `ANTHROPIC_API_KEY=`. Git never uploads `.env`.

Try it on your PC first. It makes ONE real summary of a demo meeting (a few cents) and prints what happened. Press Enter after each line:

```
cd C:\Users\USER\Documents\Workspace\AI_meeting_summarizer
```

```
.venv\Scripts\flask --app stickyminutes try-claude --sample standup
```

You should see "Try 1: passed every check." (or a problem and a second try), the tokens, the cost and the notes.

## Part 2: The Database (Neon)

1. Go to https://neon.tech and log in.
2. Click **New Project**. Name: `sticky-minutes`. Region: **AWS Asia Pacific (Singapore)** (close to Render's Singapore servers).
3. Open **Connection Details**. Choose **Pooled connection**. Copy the connection string. It starts with `postgresql://`.

## Part 3: The Web Server (Render)

1. Go to https://render.com and log in with GitHub.
2. Click **New** and then **Blueprint**.
3. Choose the repo **jcatibog014/AI_meeting_summarizer**. Render reads `render.yaml`.
4. Render asks for the values marked "sync: false":
   - `DATABASE_URL`: paste Neon's connection string from Part 2.
   - `ANTHROPIC_API_KEY`: paste your key from Part 1.
   - `BASE_URL`: leave empty for now.
5. Click **Apply**. Render builds the app and makes the tables by itself (`upgrade-db`).
6. When it says **Live**, copy the site's address (like `https://sticky-minutes-xxxx.onrender.com`).
7. In Render, open the service, then **Environment**. Set `BASE_URL` to that address. Save. Render restarts the app.

`DAILY_CAP_CENTS` is the most the whole site may spend on Claude in one day (100 = $1). Change it in **Environment** if you need more.

## Part 4: Your Login

There is no sign-up page: only you have a real account. Make it from your PC, on Neon's database. Press Enter after each line:

```
cd C:\Users\USER\Documents\Workspace\AI_meeting_summarizer
```

```
$env:DATABASE_URL = "paste Neon's connection string here"
```

```
.venv\Scripts\flask --app stickyminutes create-owner
```

It asks for your name, your email and a password (twice). Then close this PowerShell window, so the connection string isn't kept.

## Part 5: Try It

1. Open the address and log in with your email and password.
2. Click **New meeting**, paste a transcript (or upload a Zoom, Google Meet or Teams `.vtt`), and click **Summarize**. It takes 20 to 90 seconds.
3. Log out (in Settings) and click **Try the demo** to see what visitors see. Each visitor can run 3 real summaries a day.

The free plan sleeps after 15 minutes without visitors. The first visit after that takes about a minute.
