"""
Flask app for the AC maintenance prediction dashboard.

Serves the live status dashboard, exposes JSON endpoints for the current
reading and recent history (used by the dashboard's charts), and runs a
background APScheduler job that polls ThingSpeak every 30s, runs the trained
model on each new reading, logs the result to SQLite, and sends a Telegram
alert on WARNING/CRITICAL.
"""

import csv
import io
import os
from datetime import datetime, timedelta

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template

# Must run BEFORE the local imports below — chatbot.py and notifier.py read
# their API keys from os.environ at module import time (so a missing key can
# fail fast/gracefully right there), so .env has to be loaded into the
# environment first. Don't move these imports back above load_dotenv(), and
# don't move load_dotenv() below them — either would silently break config
# loading (no error, the modules just see the keys as unset).
load_dotenv()

import database
from chatbot import chatbot_bp
from notifier import notify_status_change
from predictor import predict_status

# --- CONFIG (placeholders — fill these in via environment variables) ---
THINGSPEAK_CHANNEL_ID = os.environ.get("THINGSPEAK_CHANNEL_ID", "YOUR_CHANNEL_ID")
THINGSPEAK_READ_API_KEY = os.environ.get("THINGSPEAK_READ_API_KEY", "YOUR_READ_API_KEY")
THINGSPEAK_URL = f"https://api.thingspeak.com/channels/{THINGSPEAK_CHANNEL_ID}/feeds.json"

POLL_INTERVAL_SECONDS = 30

app = Flask(__name__)
app.register_blueprint(chatbot_bp)
# Load secret/config from environment for production safety (Render will set these)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
# Optional admin credentials (read from env; may be unused if app has no admin UI)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

# In-memory buffer of the last 2 *processed* readings, needed to compute
# prev1/prev2/trend/roll_mean features exactly like the training notebook.
# Cleared on every restart — the first 2 polls after a restart just fill
# this buffer and don't predict yet. Each entry: {"temp", "hum", "vib"}.
_recent_readings = []

# Last raw (temp, hum, vib) seen, regardless of whether it was processed —
# used to detect a stale/duplicate feed (AC off, ThingSpeak repeating the
# last value).
_last_raw_reading = None

# Last *predicted* status, used so Telegram only fires on a change
# (NORMAL->WARNING, WARNING->CRITICAL, etc.) rather than every poll while
# it stays at the same severity.
_last_status = None


def fetch_latest_reading():
    """Pull the single most recent entry from the ThingSpeak channel feed.

    Field mapping (confirmed): field1=Temperature, field2=Humidity,
    field3=Vibration, field4=the channel's own self-reported status label.
    field4 is captured as device_status for logging/comparison only — it is
    never passed into predict_status().
    """
    params = {"api_key": THINGSPEAK_READ_API_KEY, "results": 1}
    resp = requests.get(THINGSPEAK_URL, params=params, timeout=10)
    resp.raise_for_status()
    feeds = resp.json().get("feeds", [])
    if not feeds:
        return None

    latest = feeds[-1]
    try:
        temp = float(latest["field1"])
        hum = float(latest["field2"])
        vib = float(latest["field3"])
    except (TypeError, KeyError, ValueError):
        return None

    device_status = latest.get("field4")

    return {"temp": temp, "hum": hum, "vib": vib, "device_status": device_status}


def poll_and_process():
    """APScheduler job: fetch → dedupe → predict → log → notify."""
    global _last_raw_reading, _last_status

    reading = fetch_latest_reading()
    if reading is None:
        return

    current = (reading["temp"], reading["hum"], reading["vib"])

    # Skip if identical to the last raw reading seen — AC is off / feed stale.
    if _last_raw_reading == current:
        return
    _last_raw_reading = current

    # Need 2 prior *processed* readings before we can compute prev1/prev2.
    if len(_recent_readings) < 2:
        _recent_readings.append(reading)
        return

    prev1, prev2 = _recent_readings[-1], _recent_readings[-2]

    status = predict_status(
        temp=reading["temp"], hum=reading["hum"], vib=reading["vib"],
        prev1=prev1, prev2=prev2,
    )

    database.insert_reading(
        timestamp=datetime.utcnow().isoformat(),
        temperature=reading["temp"],
        humidity=reading["hum"],
        vibration=reading["vib"],
        status=status,
        device_status=reading.get("device_status"),
    )

    # Only alert on a *change* of status, so it doesn't re-notify every
    # 30s while the AC sits at WARNING/CRITICAL.
    if status in ("WARNING", "CRITICAL") and status != _last_status:
        notify_status_change(status, reading["temp"], reading["hum"], reading["vib"])
    _last_status = status

    _recent_readings.append(reading)
    del _recent_readings[:-2]  # keep only the last 2


@app.route("/")
def dashboard():
    """Render the dashboard page (data is loaded client-side via /api/*)."""
    return render_template("dashboard.html")


@app.route("/api/current")
def api_current():
    """Latest real logged reading + predicted status, as JSON.

    Returns an object for the dashboard. If the latest real reading is
    older than twice the poll interval the `is_stale` flag is set so the
    UI can indicate data is not currently uploading.
    """
    latest = database.get_latest_real_reading()
    if not latest:
        return jsonify({})

    # determine staleness relative to now
    try:
        ts = datetime.fromisoformat(latest["timestamp"])
        age_seconds = (datetime.utcnow() - ts).total_seconds()
    except Exception:
        age_seconds = 999999

    is_stale = age_seconds > (POLL_INTERVAL_SECONDS * 2)

    payload = dict(latest)
    payload["is_stale"] = is_stale
    return jsonify(payload)


@app.route("/api/history")
def api_history():
    """Readings from the past 7 days, as JSON, for the dashboard charts."""
    since = (datetime.utcnow() - timedelta(days=7)).isoformat()
    rows = database.get_readings_since_real(since)

    # If there are no real rows in the 7-day window, but we do have a
    # latest real reading (older than 7d), return that single row so the
    # charts can still show the most recent value instead of being empty.
    if not rows:
        latest = database.get_latest_real_reading()
        if latest:
            rows = [latest]

    return jsonify(rows)


@app.route("/api/download-csv")
def download_csv():
    """
    Export the full logged history as CSV — our model's predictions
    (+ the device's own field4 status for comparison), not a raw
    ThingSpeak pull.
    """
    rows = database.get_all_readings()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["timestamp", "temperature", "humidity", "vibration", "status", "device_status", "is_seed"])
    for r in rows:
        writer.writerow([
            r.get("timestamp"), r.get("temperature"), r.get("humidity"),
            r.get("vibration"), r.get("status"), r.get("device_status"), r.get("is_seed"),
        ])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ac_readings.csv"},
    )


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        poll_and_process, "interval",
        seconds=POLL_INTERVAL_SECONDS, id="thingspeak_poll",
    )
    scheduler.start()
    return scheduler


if __name__ == "__main__":
    database.init_db()
    start_scheduler()
    # use_reloader=False: Flask's debug reloader runs the module twice in
    # two processes, which would start the scheduler (and double-poll
    # ThingSpeak) twice too.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
