"""
Loads the trained model/scaler/label encoder once, and reproduces the exact
feature engineering from the training notebook's reference predict_status()
(22_ac_maintenanceprediction.ipynb, cell 3) for a single live reading plus
its 2 most recent predecessors.

Not part of the file list requested for this phase, but app.py needs a
predict_status() to call — this keeps that logic out of app.py and in one
place that matches the notebook exactly.
"""

from pathlib import Path

import joblib
import pandas as pd

MODEL_DIR = Path(__file__).parent

_model = joblib.load(MODEL_DIR / "ac_model.pkl")
_scaler = joblib.load(MODEL_DIR / "scaler.pkl")
_label_encoder = joblib.load(MODEL_DIR / "label_encoder.pkl")

# Must match the column order the model was trained on.
FEATURE_COLUMNS = [
    "Temperature", "Humidity", "Vibration",
    "temp_prev1", "temp_prev2", "hum_prev1",
    "vib_prev1", "vib_prev2", "temp_trend",
    "vib_trend", "temp_roll_mean", "vib_roll_mean",
]


def predict_status(temp, hum, vib, prev1, prev2):
    """
    Predict AC status for one live reading.

    temp, hum, vib: current reading values.
    prev1: dict with keys "temp", "hum", "vib" — the most recent prior reading.
    prev2: dict with keys "temp", "hum", "vib" — the reading before that.

    Returns one of "NORMAL", "WARNING", "CRITICAL".
    """
    features = pd.DataFrame(
        [[
            temp, hum, vib,
            prev1["temp"], prev2["temp"],
            prev1["hum"],
            prev1["vib"], prev2["vib"],
            temp - prev1["temp"], vib - prev1["vib"],
            (temp + prev1["temp"] + prev2["temp"]) / 3,
            (vib + prev1["vib"] + prev2["vib"]) / 3,
        ]],
        columns=FEATURE_COLUMNS,
    )

    pred = _model.predict(_scaler.transform(features))
    return _label_encoder.inverse_transform(pred)[0]
