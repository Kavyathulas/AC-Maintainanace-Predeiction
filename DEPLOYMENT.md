# Running AC Maintenance Prediction

## Why not Render

Render was the first deployment target, but its free web service tier
spins the whole process down after ~15 minutes with no inbound HTTP
traffic (and only wakes back up on the next request). That's incompatible
with this project's core requirement: `app.py` runs an in-process
APScheduler job that polls ThingSpeak every 30 seconds and needs to keep
running continuously, whether or not anyone is looking at the dashboard.
On Render's free tier the background poller would go dark every time the
service spun down between visitors — real sensor readings would simply
never get logged during those gaps.

(Along the way we also fixed two genuine platform-interaction bugs in this
codebase — the readings table never being created under gunicorn, and the
scheduler never starting under gunicorn either — but the spin-down
behavior itself is a hard limit of Render's free tier, not something
fixable from here. Upgrading to a paid Render instance would remove the
spin-down, but for a college project, running locally is simpler and free.)

So: run it locally, with an optional ngrok tunnel for the times a public
link is actually needed.

## Running locally

This project runs inside **WSL2 (Ubuntu)** — see the Environment note in
`CLAUDE.md` for why (Windows Smart App Control blocks the compiled DLLs in
the numpy/pandas/scikit-learn wheels on native Windows).

```bash
wsl
cd ~/ac-maintain
source .venv/bin/activate
cd "/mnt/c/Users/Kavya Thulasidharan/Downloads/AC Maintain"
python app.py
```

This starts the Flask dev server on port 5000, creates `ac_readings.db` if
it doesn't already exist, and starts the 30-second ThingSpeak poller in
the same process. Leave this terminal running — closing it (or Ctrl+C)
stops both the web server and the poller.

Open `http://localhost:5000` in a browser and log in with the
`ADMIN_USERNAME`/`ADMIN_PASSWORD` from `.env`.

## Sharing a public link with ngrok

To let someone else reach your locally-running instance:

1. [Install ngrok](https://ngrok.com/download) (one-time), and authenticate
   it with your ngrok account token if you haven't already
   (`ngrok config add-authtoken <token>`).
2. With `app.py` already running (see above), open a **second** terminal
   and run:
   ```bash
   ngrok http 5000
   ```
3. ngrok prints a forwarding URL that looks like
   `https://xxxx-xx-xx-xxx-xx.ngrok-free.app` — share that. It proxies
   straight through to your local Flask process, so the login page,
   dashboard, charts, and chatbot all work exactly as they do at
   `localhost:5000`.

**Both `python app.py` and `ngrok http 5000` need to stay running**, in
their own terminals, for the link to keep working — closing either one
breaks it. The ngrok URL also isn't stable on the free plan: every time
you restart ngrok it generates a **new** random URL, so you'll need to
re-share the link after any restart.

## Environment variables

Same `.env` file as always — see `.env.example` for the full list, and
`CLAUDE.md`'s "Config still needed" section for which are required vs.
optional. Nothing about running locally + ngrok changes what belongs in
`.env`. `DATABASE_URL` in particular should stay unset: `database.py`
auto-detects it, and with it unset keeps using the local `ac_readings.db`
SQLite file (see that file's module docstring — the PostgreSQL support
built for the Render attempt is still there but sits inert unless
`DATABASE_URL` is set).
