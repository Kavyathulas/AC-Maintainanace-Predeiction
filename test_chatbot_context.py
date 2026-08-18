from pathlib import Path
import os
from datetime import datetime, timedelta
import types as _types
import sys

# Inject minimal mocks for third-party imports used at module import time
# so this test can run without installing Flask or google-genai.
_fake_flask = _types.ModuleType("flask")

class _FakeBlueprint:
    def __init__(self, *a, **k):
        pass

    def route(self, *a, **k):
        def decorator(f):
            return f
        return decorator

_fake_flask.Blueprint = _FakeBlueprint
_fake_flask.jsonify = lambda x: x
_fake_flask.request = None
sys.modules["flask"] = _fake_flask

_fake_google = _types.ModuleType("google")
_fake_genai = _types.ModuleType("google.genai")
_fake_genai.Client = lambda api_key=None: None
_fake_genai.types = _types.SimpleNamespace(GenerateContentConfig=lambda *a, **k: None)
sys.modules["google"] = _fake_google
sys.modules["google.genai"] = _fake_genai
sys.modules["google.genai.types"] = _fake_genai.types

import database

# Use a temporary DB file so we don't touch the user's real data
TMP_DB = Path(__file__).with_name("ac_test.db")
if TMP_DB.exists():
    TMP_DB.unlink()

database.DB_PATH = TMP_DB
database.init_db()

now = datetime.utcnow()

# Helper to insert rows with relative minutes offset
def add(minutes_offset, temperature, humidity, vibration, status, is_seed=0, device_status=None):
    ts = (now - timedelta(minutes=minutes_offset)).isoformat()
    database.insert_reading(ts, temperature, humidity, vibration, status, device_status=device_status, is_seed=bool(is_seed))

# Recent 7-day window readings
add(10, 30.5, 60.0, 1.2, "NORMAL", is_seed=0)
add(60, 37.0, 96.0, 2.5, "WARNING", is_seed=0)
add(60*24*2, 36.5, 94.0, 1.0, "NORMAL", is_seed=1)
add(60*24*3, 38.0, 97.0, 3.5, "WARNING", is_seed=0)

# An older critical event (8 days ago) to show last-alert searches across full history
add(60*24*8, 45.0, 99.0, 12.0, "CRITICAL", is_seed=1)

import chatbot

def main():
    ctx = chatbot._build_context()
    print("--- BUILT CONTEXT ---")
    print(ctx)


if __name__ == "__main__":
    main()
