"""
Manual smoke test: feeds a deliberately extreme reading into predict_status()
and confirms it comes back CRITICAL, then exercises notifier.notify_status_change()
with it.

Not a pytest suite — just a standalone script, run directly:
    python test_alerts.py

Safe to run before Telegram credentials are set: notify_status_change()
already falls back to a print-only dry run when TELEGRAM_BOT_TOKEN /
TELEGRAM_CHAT_ID are still the placeholder values (see notifier.py).
"""

from notifier import notify_status_change
from predictor import predict_status


def test_critical_prediction():
    # Well past the CRITICAL cut points the training labels were built from
    # (temp > 42, vibration > 10 — see CLAUDE.md) and far from the mild
    # prior readings, so temp_trend/vib_trend are extreme too.
    prev2 = {"temp": 30.0, "hum": 60.0, "vib": 0.5}
    prev1 = {"temp": 32.0, "hum": 62.0, "vib": 0.7}

    status = predict_status(temp=55.0, hum=99.0, vib=25.0, prev1=prev1, prev2=prev2)
    print(f"Predicted status for extreme reading: {status}")
    assert status == "CRITICAL", f"Expected CRITICAL, got {status}"
    print("OK: predict_status() returns CRITICAL for an extreme reading.")
    return status


def test_notifier(status):
    print("\nExercising notifier.notify_status_change() ...")
    notify_status_change(status, temp=55.0, hum=99.0, vib=25.0)
    print("OK: notifier ran without raising.")


if __name__ == "__main__":
    critical_status = test_critical_prediction()
    test_notifier(critical_status)
