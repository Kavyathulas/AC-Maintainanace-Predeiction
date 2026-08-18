"""
seed_test_data.py — inserts a handful of FAKE demo readings into ac_readings.db
so the dashboard (status card, 7-day charts, chatbot) has something to show
while waiting for real ThingSpeak activity.

*** This is test/demo data, not real sensor data. ***
Every row inserted by this script is marked is_seed=1 in the database (see
database.py's `readings` schema) so it's always possible to tell seeded rows
apart from real logged ones later — e.g.:

    SELECT * FROM readings WHERE is_seed = 1;   -- seeded/demo rows only
    SELECT * FROM readings WHERE is_seed = 0;   -- real ThingSpeak-derived rows only

--- Why the values below look the way they do ---
An earlier version of this script used a handful of widely-spaced points
(one every ~6 hours, big jumps between them). That exposed a real
calibration problem: with prev1/prev2 that far from the current reading,
the trained model jumped straight from NORMAL to CRITICAL and skipped
WARNING almost entirely — even for values that are clearly WARNING-range
by the documented thresholds (see CLAUDE.md). Verified directly against
predictor.predict_status() before writing this file: a *gradual* ramp,
where each step is a small delta from the last (matching the trend/
roll_mean magnitude the model actually saw in training), reproduces the
correct NORMAL -> WARNING -> CRITICAL -> WARNING -> NORMAL arc. So the
sequence below is deliberately dense/gradual, not because that's the only
way to write realistic data, but because it's what this specific trained
model needs to classify correctly. This is also a symptom of
synthetic_critical.csv being tiny (9 rows) — see the "Known data gap" note
in CLAUDE.md.

Safe to run more than once (it just appends more seed rows) and safe to
clean up later — see "To remove seeded rows" at the bottom of this file.

Run with: python seed_test_data.py
"""

from datetime import datetime, timedelta

import database
from predictor import predict_status

# (temp, hum, vib) — a gradual rise from a stable NORMAL baseline, through
# WARNING, up to a CRITICAL peak (simulated compressor/vibration event),
# then back down through WARNING to NORMAL. Verified against predict_status()
# before committing to this file — see module docstring.
RAMP = [
    (33.0, 88.0, 0.5),
    (33.3, 88.3, 0.6),
    (33.6, 88.6, 0.7),
    (34.0, 89.0, 0.9),
    (34.4, 89.4, 1.1),
    (34.8, 89.8, 1.3),
    (35.2, 90.2, 1.5),
    (35.6, 90.6, 1.7),
    (36.0, 91.0, 2.0),
    (36.5, 91.5, 2.4),
    (37.0, 92.0, 2.8),
    (37.5, 92.5, 3.2),
    (38.0, 93.0, 3.6),
    (38.5, 93.5, 4.0),
    (39.0, 94.0, 4.5),
    (39.5, 94.5, 5.0),
    (40.0, 95.0, 5.5),
    (41.0, 95.5, 7.0),
    (42.0, 96.0, 8.5),
    (43.0, 96.5, 10.0),
    (44.0, 97.0, 12.0),  # peak of the simulated critical event
    (43.0, 96.5, 10.0),
    (41.0, 95.5, 7.0),
    (39.0, 94.0, 4.5),
    (37.0, 92.0, 2.8),
    (35.5, 90.5, 1.6),
    (34.0, 89.0, 0.9),
    (33.0, 88.0, 0.5),  # back to the same NORMAL baseline it started at
]

HOURS_BETWEEN_READINGS = 5  # 28 points * 5h = ~5.8 days, fits the dashboard's 7-day window


def main():
    database.init_db()
    now = datetime.utcnow()
    total_points = len(RAMP)

    prev1 = prev2 = None
    inserted = 0

    for i, (temp, hum, vib) in enumerate(RAMP):
        # Oldest point first, most recent point lands at "now".
        hours_ago = (total_points - 1 - i) * HOURS_BETWEEN_READINGS
        timestamp = now - timedelta(hours=hours_ago)
        current = {"temp": temp, "hum": hum, "vib": vib}

        # First point has no real prior context — self-reference so
        # predict_status() has something to compute trend/roll_mean from.
        p1 = prev1 or current
        p2 = prev2 or p1

        status = predict_status(temp=temp, hum=hum, vib=vib, prev1=p1, prev2=p2)

        database.insert_reading(
            timestamp=timestamp.isoformat(),
            temperature=temp,
            humidity=hum,
            vibration=vib,
            status=status,
            device_status=None,  # no real device-reported label for fake data
            is_seed=True,
        )
        inserted += 1
        print(f"  {timestamp.isoformat()}  T={temp} H={hum} V={vib}  -> {status}  [SEED]")

        prev2 = prev1 or current
        prev1 = current

    print(f"\nInserted {inserted} seed rows (is_seed=1) into {database.DB_PATH.name}.")


if __name__ == "__main__":
    main()

# --- To remove seeded rows later, without touching real logged data ---
# Open ac_readings.db in any SQLite tool (or `sqlite3 ac_readings.db`) and run:
#   DELETE FROM readings WHERE is_seed = 1;
