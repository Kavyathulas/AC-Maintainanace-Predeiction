"""
/api/chat — a maintenance-assistant chatbot that answers questions about the
AC's current condition and recent history, grounded in our own SQLite log
(our model's predictions, not raw ThingSpeak data), via Google's Gemini API.
"""

import os
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from google import genai
from google.genai import types

import database

# gemini-3.5-flash, not -pro — flash has the more workable free-tier limits.
# (gemini-2.5-flash, originally used here, returns 404 "no longer available
# to new users" as of 2026-08 — verified live against this project's own key.
# gemini-3.5-flash is its stable-generation successor.)
GEMINI_MODEL = "gemini-3.5-flash"

# Built lazily and guarded — a missing/bad GEMINI_API_KEY must NOT crash
# app.py at import time (app.py imports this module to register the
# blueprint). _client stays None and every /api/chat call returns a clear
# "not configured" error instead until the key is set.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
_client = None
_client_error = None
if not GEMINI_API_KEY:
    _client_error = "GEMINI_API_KEY is not set."
else:
    try:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:  # defensive: don't let a bad key crash the app at import time
        _client_error = f"Failed to initialize Gemini client: {e}"

# --- DRAFT — your message cut off right after "You're". I completed the
# sentence with a reasonable default: stay grounded in the provided data,
# explain WARNING/CRITICAL in practical terms with a concrete next step, and
# defer to a real HVAC technician for anything serious. Read this and adjust
# the tone/scope to match what you actually want before relying on it. ---
SYSTEM_PROMPT = """You are a maintenance assistant for an AC monitoring system. You
answer questions about the AC's current condition and maintenance needs in
plain, friendly language. Use only the aggregated sensor data and status
history provided below — do not invent readings or claim access to raw rows
that are not included. If the data doesn't cover what's being asked, say so
plainly. When the status is WARNING or CRITICAL, explain what that means in
practical terms and suggest one concrete thing to check first, but make clear
you're a monitoring assistant, not a substitute for a real HVAC technician.

The context provided to you contains:
- the latest logged reading (timestamp + values),
- 7-day aggregates: status counts and min/max/average for Temperature,
    Humidity, and Vibration (use these aggregates when answering trend or
    "highest/lowest" questions),
- the most recent WARNING or CRITICAL event (searched across the full history
    and included if present) — use this to answer "when was the last time it
    was critical", and
- a reading-count breakdown (total / real sensor rows / seeded/test rows) so
    you can honestly distinguish real history from demo data.

Keep answers concise and grounded in those aggregates rather than attempting
to reconstruct or list full row-by-row history. If asked for additional
detail that isn't present in the provided aggregates, state that the raw
rows are not available in the prompt and suggest how to obtain them (for
example: ask the operator to export the CSV or query the API endpoint).
"""

chatbot_bp = Blueprint("chatbot", __name__)

# Matches the dashboard's own chart window, so "highest temp logged" answers
# what the user is actually looking at on screen, not some other range.
STATS_WINDOW_DAYS = 7


def _build_context():
    """Assemble the live-status + trend summary handed to Gemini as context."""
    latest = database.get_latest_reading()

    since_window = (datetime.utcnow() - timedelta(days=STATS_WINDOW_DAYS)).isoformat()
    counts = database.get_status_counts_since(since_window)
    stats = database.get_stats_since(since_window)
    last_alert = database.get_last_alert_reading()
    reading_counts = database.get_reading_counts()

    if latest:
        current = (
            f"Current reading (as of {latest['timestamp']}): "
            f"Temperature={latest['temperature']}°C, Humidity={latest['humidity']}%, "
            f"Vibration={latest['vibration']}, Predicted status={latest['status']}"
        )
        if latest.get("device_status"):
            current += f" (device's own reported status: {latest['device_status']})"
    else:
        current = "No readings have been logged yet."

    history = (
        f"Past {STATS_WINDOW_DAYS} days: {counts.get('NORMAL', 0)} NORMAL, "
        f"{counts.get('WARNING', 0)} WARNING, {counts.get('CRITICAL', 0)} CRITICAL "
        f"readings logged."
    )

    if stats:
        t, h, v = stats["temperature"], stats["humidity"], stats["vibration"]
        stats_summary = (
            f"Past {STATS_WINDOW_DAYS} days ({stats['count']} readings, same window as the "
            f"dashboard charts) — "
            f"Temperature: min={t['min']:.1f}°C, max={t['max']:.1f}°C, avg={t['avg']:.1f}°C; "
            f"Humidity: min={h['min']:.1f}%, max={h['max']:.1f}%, avg={h['avg']:.1f}%; "
            f"Vibration: min={v['min']:.2f}, max={v['max']:.2f}, avg={v['avg']:.2f}."
        )
    else:
        stats_summary = f"No readings in the past {STATS_WINDOW_DAYS} days to compute min/max/average from."

    if last_alert:
        alert_summary = (
            f"Last WARNING/CRITICAL event: {last_alert['status']} at {last_alert['timestamp']} "
            f"(Temperature={last_alert['temperature']}°C, Humidity={last_alert['humidity']}%, "
            f"Vibration={last_alert['vibration']})."
        )
    else:
        alert_summary = "Last WARNING/CRITICAL event: none logged — every reading so far has been NORMAL."

    counts_summary = (
        f"Total readings logged: {reading_counts['total']} "
        f"({reading_counts['real']} real sensor readings, "
        f"{reading_counts['seed']} seeded/test data)."
    )

    return f"{current}\n{history}\n{stats_summary}\n{alert_summary}\n{counts_summary}"


@chatbot_bp.route("/api/chat", methods=["POST"])
def chat():
    if _client is None:
        return jsonify({"error": f"Chatbot not configured: {_client_error}"}), 503

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "Missing 'message' in request body."}), 400

    context = _build_context()

    try:
        response = _client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"Current AC status data:\n{context}\n\nQuestion: {user_message}",
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
        reply = (response.text or "").strip()
    except Exception as e:
        # google-genai's exception hierarchy isn't documented in front of me
        # in this session, so this is a deliberately broad catch rather than
        # a guessed-and-possibly-wrong specific one.
        return jsonify({"error": f"Gemini API error: {e}"}), 502

    if not reply:
        return jsonify({"error": "The assistant returned an empty response (possibly blocked)."}), 502

    return jsonify({"reply": reply})
