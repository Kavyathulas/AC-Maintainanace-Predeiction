"""
SQLite (local dev) / PostgreSQL (Render production) storage for logged AC
readings + predictions.

Backend is chosen automatically: if the DATABASE_URL environment variable is
set — Render sets this once a PostgreSQL database is created and linked to
this service in its dashboard, see DEPLOYMENT.md — every function below
talks to that Postgres database instead of the local ac_readings.db SQLite
file, so data survives redeploys (the local SQLite file lives on Render's
ephemeral disk and is wiped on every deploy). Locally, DATABASE_URL is
unset, so nothing changes: same file, same behavior as before.

Every function is written once against get_connection() + the _q()
placeholder adapter below, rather than duplicated per-backend, so callers
(app.py, chatbot.py, seed_test_data.py, etc.) don't need to know or care
which database is actually active.
"""

import contextlib
import os
import sqlite3
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

DB_PATH = Path(__file__).parent / "ac_readings.db"

# Render sets this automatically once a PostgreSQL database is created and
# linked to this web service in the dashboard (see DEPLOYMENT.md). Unset
# locally, so local dev keeps using the SQLite file above untouched.
DATABASE_URL = os.environ.get("DATABASE_URL")

# One IntegrityError name that works no matter which backend is active, so
# callers (e.g. app.py's poll_and_process) can catch it without needing to
# know whether SQLite or Postgres is behind it.
IntegrityError = (sqlite3.IntegrityError, psycopg2.IntegrityError)


@contextlib.contextmanager
def get_connection():
    """Yield a connection for whichever backend is active, and commit (or
    roll back, on an exception) and close it automatically.

    Same call pattern as before this changed — `with get_connection() as
    conn:` — so no caller needs to know or care which backend it got.
    """
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _q(sql):
    """Every query below is written once, with '?' placeholders (sqlite3
    style) — translate to '%s' (psycopg2/Postgres style) on the fly when
    Postgres is the active backend, instead of maintaining two near-
    identical copies of every query.
    """
    return sql.replace("?", "%s") if DATABASE_URL else sql


def init_db():
    """Create the readings table (and its index) if they don't exist yet."""
    with get_connection() as conn:
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    id SERIAL PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    humidity REAL NOT NULL,
                    vibration REAL NOT NULL,
                    status TEXT NOT NULL,
                    device_status TEXT,
                    is_seed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    humidity REAL NOT NULL,
                    vibration REAL NOT NULL,
                    status TEXT NOT NULL,
                    device_status TEXT,
                    is_seed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON readings(timestamp)")

        if not DATABASE_URL:
            # SQLite-only migration: is_seed was added after some
            # ac_readings.db files already existed on disk. A Render
            # Postgres database is always freshly provisioned and empty,
            # so there's nothing to migrate there — the CREATE TABLE above
            # already includes is_seed from the start.
            cur.execute("PRAGMA table_info(readings)")
            existing_columns = {row["name"] for row in cur.fetchall()}
            if "is_seed" not in existing_columns:
                cur.execute("ALTER TABLE readings ADD COLUMN is_seed INTEGER NOT NULL DEFAULT 0")


def insert_reading(timestamp, temperature, humidity, vibration, status, device_status=None, is_seed=False):
    """
    Log one processed reading + its predicted status.

    device_status is the AC channel's own self-reported status (ThingSpeak
    field4), stored only for comparison against our model's prediction —
    it is never used as a model input.

    is_seed marks rows inserted by seed_test_data.py (demo/test data) rather
    than real ThingSpeak polling — defaults to False, so the normal app.py
    poll path never has to think about it.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            _q(
                """
                INSERT INTO readings (timestamp, temperature, humidity, vibration, status, device_status, is_seed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
            ),
            (timestamp, temperature, humidity, vibration, status, device_status, int(is_seed)),
        )


def get_latest_reading():
    """Most recently logged reading, or None if the table is empty."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM readings ORDER BY timestamp DESC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None


def get_latest_real_reading():
    """Most recent reading with `is_seed=0`, or None if none exist."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM readings WHERE is_seed = 0 ORDER BY timestamp DESC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None


def get_readings_since(since_timestamp):
    """All readings with timestamp >= since_timestamp, oldest first."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            _q("SELECT * FROM readings WHERE timestamp >= ? ORDER BY timestamp ASC"),
            (since_timestamp,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_readings_since_real(since_timestamp):
    """All readings with timestamp >= since_timestamp and is_seed=0, oldest first."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            _q("SELECT * FROM readings WHERE timestamp >= ? AND is_seed = 0 ORDER BY timestamp ASC"),
            (since_timestamp,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_all_readings():
    """Every logged reading, oldest first — used for the full CSV export."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM readings ORDER BY timestamp ASC")
        return [dict(row) for row in cur.fetchall()]


def get_status_counts_since(since_timestamp):
    """{status: count} of logged readings with timestamp >= since_timestamp.

    Used by the chatbot to answer trend questions ("how many WARNINGs today?").
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            _q("SELECT status, COUNT(*) as count FROM readings WHERE timestamp >= ? GROUP BY status"),
            (since_timestamp,),
        )
        return {row["status"]: row["count"] for row in cur.fetchall()}


def get_stats_since(since_timestamp):
    """
    Min/max/avg temperature, humidity, vibration for readings with
    timestamp >= since_timestamp. Returns None if there are no readings in
    that window, otherwise:

        {
            "count": N,
            "temperature": {"min": ..., "max": ..., "avg": ...},
            "humidity":    {"min": ..., "max": ..., "avg": ...},
            "vibration":   {"min": ..., "max": ..., "avg": ...},
        }

    Computed with SQL aggregates rather than pulling every row into Python —
    used by the chatbot to answer questions like "what's the highest
    temperature logged".
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            _q(
                """
                SELECT COUNT(*) as count,
                       MIN(temperature) as temp_min, MAX(temperature) as temp_max, AVG(temperature) as temp_avg,
                       MIN(humidity) as hum_min, MAX(humidity) as hum_max, AVG(humidity) as hum_avg,
                       MIN(vibration) as vib_min, MAX(vibration) as vib_max, AVG(vibration) as vib_avg
                FROM readings
                WHERE timestamp >= ?
                """
            ),
            (since_timestamp,),
        )
        row = cur.fetchone()

    if not row or row["count"] == 0:
        return None

    return {
        "count": row["count"],
        "temperature": {"min": row["temp_min"], "max": row["temp_max"], "avg": row["temp_avg"]},
        "humidity": {"min": row["hum_min"], "max": row["hum_max"], "avg": row["hum_avg"]},
        "vibration": {"min": row["vib_min"], "max": row["vib_max"], "avg": row["vib_avg"]},
    }


def get_last_alert_reading():
    """Most recently logged WARNING or CRITICAL reading, or None if there's
    never been one. Searches the full history (not windowed) so questions
    like "when was the last time it was critical" can reach further back
    than the 7-day stats window.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM readings
            WHERE status IN ('WARNING', 'CRITICAL')
            ORDER BY timestamp DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_reading_counts():
    """
    Total logged readings, split into real (is_seed=0) vs seeded/test
    (is_seed=1) — lets the chatbot honestly distinguish real sensor history
    from demo data rather than presenting seeded rows as real readings.

    Returns {"total": N, "real": N, "seed": N}.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN is_seed = 0 THEN 1 ELSE 0 END) as real_count,
                   SUM(CASE WHEN is_seed = 1 THEN 1 ELSE 0 END) as seed_count
            FROM readings
            """
        )
        row = cur.fetchone()

    return {
        "total": row["total"] or 0,
        "real": row["real_count"] or 0,
        "seed": row["seed_count"] or 0,
    }
