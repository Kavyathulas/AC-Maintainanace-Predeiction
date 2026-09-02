"""
Sends a Telegram alert via the Bot API when AC status becomes WARNING or
CRITICAL. Bot token and chat ID are read from environment variables with
placeholder fallbacks — set them before this can actually send anything.
"""

import os

import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

# Same cut points the training labels were generated from (see CLAUDE.md) —
# used only to make a reasonable guess at *which* sensor is driving the
# alert, for the message text. The status itself always comes from the model.
SUGGESTED_ACTIONS = {
    "vibration": "Vibration elevated — check compressor mounting and bolts.",
    "temperature": "Temperature elevated — check refrigerant level and airflow/filters.",
    "humidity": "Humidity elevated — check drainage and condensate pump.",
}


def _suggested_action(temp, hum, vib):
    if vib > 2:
        return SUGGESTED_ACTIONS["vibration"]
    if temp > 36:
        return SUGGESTED_ACTIONS["temperature"]
    if hum > 95:
        return SUGGESTED_ACTIONS["humidity"]
    return "Reading trending abnormal — inspect unit."


def notify_status_change(status, temp, hum, vib):
    """
    Send a Telegram message for a WARNING/CRITICAL reading.

    status: "WARNING" or "CRITICAL".
    temp, hum, vib: the reading that triggered this status.
    """
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN" or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID":
        print(
            f"[notifier] Telegram not configured yet — would have sent: "
            f"{status} T={temp} H={hum} V={vib}"
        )
        return

    emoji = "\U0001F7E0" if status == "WARNING" else "\U0001F534"  # orange/red circle
    message = (
        f"{emoji} AC status: {status}\n"
        f"Temperature: {temp}°C | Humidity: {hum}% | Vibration: {vib}\n"
        f"Suggested action: {_suggested_action(temp, hum, vib)}"
    )

    try:
        resp = requests.post(
            TELEGRAM_API_URL,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[notifier] Failed to send Telegram alert: {e}")
