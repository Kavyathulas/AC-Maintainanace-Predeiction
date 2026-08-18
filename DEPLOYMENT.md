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

Build command:
```
pip install -r requirements.txt
```

Start command (Render web service):
```
gunicorn app:app
```

Notes:
- The background poller (`APScheduler` job) starts only when running `python
  app.py` directly (the scheduler is started in the `if __name__ == "__main__"` block).
  When using `gunicorn app:app` Render will import the module but not run the
  `__main__` block, so if you want the scheduler to run under Render you should
  either add a Render background worker or adjust the deployment to run the
  scheduler in the main process (be careful with multiple gunicorn workers).

- The `/api/download-csv` endpoint always includes seeded/demo rows; the
  dashboard and `/api/history` exclude seeded rows by default.

- Ensure you do NOT commit `.env`, `ac_readings.db`, or `.venv` to the repo.

*** End of file
