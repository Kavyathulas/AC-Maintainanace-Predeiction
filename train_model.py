"""
Regenerates ac_model.pkl, scaler.pkl, label_encoder.pkl locally.

This is a straight port of the training cell from
22_ac_maintenanceprediction.ipynb (cell-2), just swapped from the
Colab /content/ path to a local relative path. Logic is unchanged, plus one
addition: the real dataset (thingspeak_full_data (1).csv) never crosses the
CRITICAL thresholds (max observed: Temp 37.8, Hum 95.0, Vib 6.25), so a model
trained on it alone can never predict CRITICAL at all. synthetic_critical.csv
supplies a handful of synthetic extreme readings so the model at least learns
that class exists.

synthetic_critical.csv is loaded and concatenated IN MEMORY ONLY — the
original CSV on disk is never modified. The synthetic file is optional; if
it's missing, training proceeds on the real data alone (2 classes only).
"""

import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report

# --- LOAD DATA ---
real_path = Path(__file__).parent / "thingspeak_full_data (1).csv"
synthetic_path = Path(__file__).parent / "synthetic_critical.csv"

df_real = pd.read_csv(real_path)[["Date", "Temperature", "Humidity", "Vibration"]]
df_real["source"] = "real"

if synthetic_path.exists():
    df_synth = pd.read_csv(synthetic_path)[["Date", "Temperature", "Humidity", "Vibration"]]
    df_synth["source"] = "synthetic"
    print(f"Adding {len(df_synth)} synthetic rows from {synthetic_path.name} (in-memory only, "
          f"'{real_path.name}' is not touched).")
    df = pd.concat([df_real, df_synth], ignore_index=True)
else:
    print(f"No {synthetic_path.name} found — training on real data only "
          f"(model will not learn a CRITICAL class).")
    df = df_real

df["Date"] = pd.to_datetime(df["Date"], format="mixed")
df = df.sort_values("Date").ffill()
df = df[df["Vibration"] < 50]

# --- CREATE STATUS USING PROJECT THRESHOLDS ---
def parameter_status(value, normal_limit, warning_limit):
    if value > warning_limit:
        return 2
    elif value > normal_limit:
        return 1
    else:
        return 0

def generate_status(row):
    temp_l = parameter_status(row["Temperature"], 36, 42)
    hum_l = parameter_status(row["Humidity"], 95, 98)
    vib_l = parameter_status(row["Vibration"], 2, 10)
    highest = max(temp_l, hum_l, vib_l)
    if highest == 2:
        return "CRITICAL"
    elif highest == 1:
        return "WARNING"
    else:
        return "NORMAL"

df["Status"] = df.apply(generate_status, axis=1)

print("\nStatus counts by source:")
print(df.groupby(["source", "Status"]).size().unstack(fill_value=0))

# --- FEATURE ENGINEERING ---
df["temp_prev1"] = df["Temperature"].shift(1)
df["temp_prev2"] = df["Temperature"].shift(2)
df["hum_prev1"] = df["Humidity"].shift(1)
df["vib_prev1"] = df["Vibration"].shift(1)
df["vib_prev2"] = df["Vibration"].shift(2)
df["temp_trend"] = df["Temperature"] - df["temp_prev1"]
df["vib_trend"] = df["Vibration"] - df["vib_prev1"]
df["temp_roll_mean"] = df["Temperature"].rolling(3).mean()
df["vib_roll_mean"] = df["Vibration"].rolling(3).mean()
df = df.dropna()

# --- FEATURES & TARGET ---
features = [
    "Temperature", "Humidity", "Vibration",
    "temp_prev1", "temp_prev2", "hum_prev1",
    "vib_prev1", "vib_prev2", "temp_trend",
    "vib_trend", "temp_roll_mean", "vib_roll_mean",
]
X = df[features]
le = LabelEncoder()
y = le.fit_transform(df["Status"])

# --- MODEL TRAINING ---
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.20, random_state=42, stratify=y
)
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)
model = RandomForestClassifier(
    n_estimators=100, max_depth=7, min_samples_leaf=5,
    random_state=42, class_weight="balanced",
)
model.fit(X_train_scaled, y_train)

# --- EVALUATION & SAVE ---
y_pred = model.predict(X_test_scaled)
print(f"\nTraining Complete. Accuracy: {accuracy_score(y_test, y_pred):.4f}")
print("\nClassification Report:\n", classification_report(y_test, y_pred, target_names=le.classes_))

out_dir = Path(__file__).parent
joblib.dump(model, out_dir / "ac_model.pkl")
joblib.dump(scaler, out_dir / "scaler.pkl")
joblib.dump(le, out_dir / "label_encoder.pkl")
print("Model Saved Successfully!")
print("Classes:", list(le.classes_))
