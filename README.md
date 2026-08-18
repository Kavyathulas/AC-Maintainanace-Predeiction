# AC Maintain — AC Unit Monitoring & Chatbot

Overview
- Predicts AC health (`NORMAL` / `WARNING` / `CRITICAL`) from Temperature,
  Humidity, and Vibration readings using a trained RandomForest model.
- Logs predictions to SQLite, serves a dashboard (Flask + Chart.js), sends
  Telegram alerts for WARNING/CRITICAL, and exposes a Gemini-powered chatbot
  (`/api/chat`) grounded in aggregated recent history.

Quick start
1. Copy `.env.example` to `.env` and fill in keys: `THINGSPEAK_*`,
   `TELEGRAM_*` (optional), and `GEMINI_API_KEY` (for `/api/chat`).
2. Run the app (preferably inside WSL2 if using Windows):

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt  # create if missing; see project files that require flask, google-genai
python app.py
```

What changed (chatbot)
- `chatbot.py` now provides the assistant with a compact, aggregated
  context: latest reading, 7-day status counts and min/max/avg for each
  sensor, the most recent WARNING/CRITICAL event (searched across full
  history), and counts of total vs real vs seeded rows. This keeps prompts
  compact while letting the assistant answer questions like "when was the
  last time it was critical" and "how much real history do we have?".

Testing the chatbot context locally
- A helper script `test_chatbot_context.py` creates a temporary test DB,
  inserts example readings (real + seeded), and prints the context that would
  be sent to Gemini. Run it with:

```bash
python test_chatbot_context.py
```

Sample prompts to try with `/api/chat` (when `GEMINI_API_KEY` is set):
- "What's the current AC status and what should I check first?"
- "When was the last time it was critical?"
- "How many WARNINGs have occurred in the past 7 days?"
- "What's the highest temperature recorded in the last 7 days?"
- "Is the logged data real sensor history or just demo/seed data?"

If you want, I can add a unit test that asserts specific fields in the
generated context rather than just printing it.
