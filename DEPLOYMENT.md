# Deployment to Render

This project can be hosted on Render using the following setup. These are
code-only instructions; deploy through Render's web dashboard.

Required environment variables (set these in Render service settings):
- `THINGSPEAK_CHANNEL_ID` — ThingSpeak channel id
- `THINGSPEAK_READ_API_KEY` — ThingSpeak read API key
- `TELEGRAM_BOT_TOKEN` — Telegram bot token (optional; if unset notifier prints)
- `TELEGRAM_CHAT_ID` — Telegram chat id (optional)
- `GEMINI_API_KEY` — Gemini API key for chatbot (optional; `/api/chat` returns 503 if unset)
- `SECRET_KEY` — Flask session signing key. **Required** — the app now
  gates every route behind a login page and refuses to start without it.
- `ADMIN_USERNAME` and `ADMIN_PASSWORD` — the one shared login for the
  dashboard/API. **Required** — same as above, the app won't start
  without them.
- `DATABASE_URL` — PostgreSQL connection string. **Optional but strongly
  recommended on Render** — see "Persistent storage" below. Render sets
  this automatically once you create a Postgres database and link it to
  this web service. Unset = falls back to the local SQLite file, which
  Render wipes on every redeploy.

Build command:
```
pip install -r requirements.txt
```

Start command (Render web service):
```
gunicorn app:app --workers 1
```

Notes:
- `database.init_db()` and the background poller (`APScheduler` job) both run
  at module import time in `app.py`, not inside `if __name__ == "__main__"` —
  so they run under both `python app.py` (local dev) and `gunicorn app:app`
  (Render). This matters because gunicorn imports the module and calls the
  `app` WSGI object directly; it never executes the `__main__` block, so
  anything that only lived there (as both of these originally did) silently
  never ran on Render — including table creation, which is why a fresh
  deploy could hit `sqlite3.OperationalError: no such table: readings`.
- The Procfile pins `gunicorn app:app --workers 1` deliberately — the
  scheduler starts once per worker process, so more than 1 worker means
  more than one poller hitting ThingSpeak and duplicate DB inserts/Telegram
  alerts every interval. Don't raise `--workers` without first moving the
  scheduler to a separate process (e.g. a Render background worker).

- The `/api/download-csv` endpoint always includes seeded/demo rows; the
  dashboard and `/api/history` exclude seeded rows by default.

- Ensure you do NOT commit `.env`, `ac_readings.db`, or `.venv` to the repo.

## Persistent storage: SQLite locally, PostgreSQL on Render

Render's filesystem is ephemeral — anything written to disk (including the
`ac_readings.db` SQLite file) is wiped on every redeploy. `database.py`
auto-detects a `DATABASE_URL` env var and switches from SQLite to
PostgreSQL when it's set, with identical behavior either way — locally,
where `DATABASE_URL` is never set, nothing changes.

To set this up:

1. In the Render dashboard: **New +** → **PostgreSQL**. Pick the Free
   plan. Give it a name (e.g. `ac-maintain-db`) and create it.
2. Open your **web service** → **Environment** tab → **Add Environment
   Variable**. Render offers a way to link a variable to a database's
   connection string directly (rather than pasting it by hand) — use that
   to set `DATABASE_URL` to this database's **Internal Database URL**
   (same-region traffic, no SSL required, lower latency than the External
   URL). If your Render UI doesn't offer that picker, copy the Internal
   Database URL from the Postgres instance's **Info** page and paste it in
   manually.
3. Redeploy the web service so it picks up the new env var. On next boot,
   `database.init_db()` (which now runs at import time — see the note
   above about gunicorn) creates the `readings` table in Postgres
   automatically, same as it would for a fresh SQLite file.

**Know the free-tier limit:** Render's free PostgreSQL databases expire
30 days after creation, with a 14-day grace period to upgrade before
Render deletes the database and all its data. This still solves the
original problem (data surviving a *redeploy*), but not indefinitely on
the free plan — either upgrade to a paid instance before the 30-day mark,
or budget for recreating the free database periodically (you'd lose
history at that point, same as today). See Render's docs/changelog for
current specifics.

*** End of file
