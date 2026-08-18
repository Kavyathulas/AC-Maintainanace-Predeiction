# AC Maintenance Prediction System

College IoT project. Predicts AC unit health status (`NORMAL` / `WARNING` /
`CRITICAL`) from live Temperature, Humidity, and Vibration sensor readings,
using a trained RandomForest model, and surfaces it through a live dashboard
with Telegram alerts.

## How prediction works

- Model: `RandomForestClassifier` (100 trees, max_depth=7, min_samples_leaf=5,
  class_weight="balanced"), trained in `22_ac_maintenanceprediction.ipynb`.
- Artifacts: `ac_model.pkl`, `scaler.pkl` (`StandardScaler`), `label_encoder.pkl`
  (`LabelEncoder` over the 3 status strings). Loaded once at process start in
  `predictor.py`.
- **Feature order matters** — the model was trained on exactly this column
  order, and inference must match it:
  ```
  Temperature, Humidity, Vibration, temp_prev1, temp_prev2, hum_prev1,
  vib_prev1, vib_prev2, temp_trend, vib_trend, temp_roll_mean, vib_roll_mean
  ```
- Feature engineering, reproduced exactly from the notebook's reference
  `predict_status()` (cell 3) in `predictor.py`:
  ```
  temp_trend     = temp - prev1.temp
  vib_trend      = vib  - prev1.vib
  temp_roll_mean = (temp + prev1.temp + prev2.temp) / 3
  vib_roll_mean  = (vib  + prev1.vib  + prev2.vib)  / 3
  ```
  This needs the **previous 2 readings** in memory at prediction time — see
  `app.py`'s `_recent_readings` buffer.
- Training labels (for reference only — the deployed model predicts from
  learned patterns, not these raw cutoffs; useful context for
  `notifier.py`'s suggested-action text):
  | Parameter | Normal limit | Warning limit |
  |---|---|---|
  | Temperature | 36 | 42 |
  | Humidity | 95 | 98 |
  | Vibration | 2 | 10 |
  Status = highest severity across the 3 parameters (CRITICAL > WARNING > NORMAL).
- **Known data gap:** the real dataset never crosses the CRITICAL thresholds
  (max observed: Temp 37.8°C, Hum 95.0%, Vib 6.25 — all below the CRITICAL
  cutoffs above). A model trained on it alone only ever learns NORMAL/WARNING
  and can structurally never output CRITICAL. `synthetic_critical.csv`
  patches this with synthetic extreme rows (in-memory only, see file table
  below) so the model at least knows the class exists. If you ever log a real
  CRITICAL event from the hardware, retraining on real data alone becomes
  worth revisiting.

## Data source

ThingSpeak channel, polled every 30s. Field mapping (confirmed):

| Field | Meaning | Used for prediction? |
|---|---|---|
| `field1` | Temperature | yes |
| `field2` | Humidity | yes |
| `field3` | Vibration | yes |
| `field4` | The channel's own self-reported status label | **no** — logged as `device_status` alongside our model's prediction, for comparison only. Never passed into `predict_status()`. |

AC is off after ~1pm most days, so the feed goes stale (repeats the last
value) — duplicate readings are skipped rather than logged/predicted.

## Tech stack

- **Flask** — web app + JSON API (`app.py`)
- **APScheduler** — background 30s ThingSpeak poll job, runs inside the Flask process
- **SQLite** — reading/prediction log (`database.py`, file: `ac_readings.db`)
- **Telegram Bot API** — WARNING/CRITICAL alerts (`notifier.py`)
- **Chart.js** (CDN) — dashboard charts (`templates/dashboard.html`)
- **Google Gemini API** (`google-genai` Python SDK) — chatbot/help-desk (`chatbot.py`), model `gemini-3.5-flash` (not `-pro` — flash has the more workable free-tier limits). Switched from the Anthropic API to stay on a free tier. (Originally `gemini-2.5-flash`; that model returned 404 "no longer available to new users" as of 2026-08 — verified live against this project's own key — and was swapped for its stable-generation successor.)

## File structure

| File | Purpose |
|---|---|
| `22_ac_maintenanceprediction.ipynb` | Training notebook (source of truth for model/feature logic) |
| `thingspeak_full_data (1).csv`, `thingspeak_full_data testing.csv` | Real training/testing datasets — never contain a CRITICAL reading (see below) |
| `synthetic_critical.csv` | Small set of synthetic extreme readings (temp/hum/vib past the CRITICAL cutoffs), 3 short ramp sequences so the model sees realistic prev1/prev2/trend context. **Loaded and concatenated in memory only** by `train_model.py` — the real CSV on disk is never modified. Optional: training still runs without it (model just won't learn CRITICAL). |
| `train_model.py` | Standalone script version of the notebook's training cell; regenerates the 3 `.pkl` files. Loads real + synthetic data separately, concatenates in memory. |
| `ac_model.pkl`, `scaler.pkl`, `label_encoder.pkl` | Trained model artifacts (generated, not hand-written) |
| `predictor.py` | Loads the 3 pkl files; `predict_status(temp, hum, vib, prev1, prev2)` |
| `database.py` | SQLite schema + insert/query helpers |
| `notifier.py` | Telegram alert on WARNING/CRITICAL |
| `chatbot.py` | `/api/chat` route — Gemini-powered Q&A grounded in our logged readings. Context sent to Gemini per request: latest reading, 7-day status counts (NORMAL/WARNING/CRITICAL), 7-day min/max/avg for Temperature/Humidity/Vibration, the most recent WARNING/CRITICAL event (timestamp + values, searched over full history so it can answer "when was the last time it was critical"), and total readings logged split into real (`is_seed=0`) vs seeded/test (`is_seed=1`) so it never presents demo data as real sensor history. Aggregated in SQL (`database.py`), not raw row dumps, to stay compact in the prompt. |

Note: the chatbot intentionally sends compact aggregates (7-day counts, min/max/avg, last alert across full history, and real-vs-seed counts) rather than a full row-by-row dump, so responses stay prompt-efficient and focused on actionable summaries.
| `app.py` | Flask routes + APScheduler polling job + registers `chatbot_bp` |
| `templates/dashboard.html` | Live status card + history charts + CSV export button |
| `test_alerts.py` | Standalone script: feeds an extreme reading through `predict_status()`, confirms `CRITICAL`, exercises `notifier.py` |
| `.gitignore` | Excludes `ac_readings.db`, `.env`/secrets, Python/venv cruft |
| `.env.example` | Template listing every env var this project reads, placeholders only — copy to `.env` and fill in real values |
| `ac_readings.db` | SQLite database (created at runtime, gitignored) |

### SQLite schema (`readings` table)

`id, timestamp, temperature, humidity, vibration, status, device_status`

`status` is our model's prediction; `device_status` is the channel's own
`field4` label, stored for comparison only.

### Notable routes (`app.py`)

- `GET /` — dashboard page
- `GET /api/current` — latest logged reading, JSON
- `GET /api/history` — last 7 days, JSON (feeds the charts)
- `GET /api/download-csv` — full logged history as a CSV download (our
  predictions + `device_status`, not a raw ThingSpeak pull)

### Alerting

`notify_status_change()` is called from `poll_and_process()` only when the
predicted status is WARNING/CRITICAL **and differs from the previous poll's
status** — avoids re-alerting every 30s while the AC sits at the same
severity.

## Environment note

This machine has Windows Smart App Control enforced, which blocks the compiled
DLLs inside `numpy`/`pandas`/`scikit-learn` wheels (confirmed: blocks both pip
and conda-forge/Anaconda-signed builds). Project runs inside **WSL2 (Ubuntu)**
instead, in a venv at `~/ac-maintain/.venv`, reading/writing this project
folder via `/mnt/c/Users/Kavya Thulasidharan/Downloads/AC Maintain`. No
Windows security settings were changed to work around this.

## Config still needed (see checklist at the end of the relevant phase)

`app.py` and `notifier.py` read these from environment variables with
placeholder fallbacks — nothing is hardcoded, nothing works until these are
set:
- `THINGSPEAK_CHANNEL_ID`, `THINGSPEAK_READ_API_KEY`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `GEMINI_API_KEY` for `chatbot.py` — the app **starts fine without it**;
  `/api/chat` returns a 503 "chatbot not configured" error until it's set

All of the above are loaded from a `.env` file (via `python-dotenv`) if
present. Copy `.env.example` to `.env` and fill in real values — `.env` is
gitignored, `.env.example` (placeholders only) is committed. `app.py` calls
`load_dotenv()` **before** importing `chatbot.py`/`notifier.py`, since those
modules read their keys from `os.environ` at import time — don't reorder
those imports, it'd silently break config loading (no error, keys just read
as unset).

## Build phases

Built one at a time, tested before moving on:

1. **Phase 1 — live data + logging.** Poll ThingSpeak every 30s, keep last 2
   readings in memory, run `predict_status()`, log to SQLite, skip duplicate
   (stale/AC-off) readings. *(Superseded by Phase 2 — polling now lives inside
   `app.py` rather than a standalone script.)*
2. **Phase 2 — Flask app + dashboard.** `app.py`, `database.py`, `predictor.py`,
   `templates/dashboard.html`. Status card + history charts, background poller.
   **Written, not yet run/tested** (blocked on WSL2 setup).
3. **Phase 3 — notifications.** `notifier.py`, Telegram alerts on
   WARNING/CRITICAL. **Written, not yet run/tested.**
4. **Phase 4 — chatbot.** `chatbot.py`, `/api/chat` route. **Written, not yet run/tested.**
