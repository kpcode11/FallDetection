"""MQTT inference service for a model produced by train.py."""
from __future__ import annotations

import json
from pathlib import Path
import joblib
import numpy as np
import paho.mqtt.client as mqtt
from train import FEATURE_NAMES, WINDOW_SIZE, extract_features

MQTT_BROKER, MQTT_PORT = "broker.hivemq.com", 1883
MQTT_TOPIC_DATA = "ioe-lab/fall-detection/team41/sensor_data"
MQTT_TOPIC_ALERT = "ioe-lab/fall-detection/team41/alert"
MODEL_FILE = Path(__file__).resolve().parent / "fall_detection_model.joblib"
model, model_metadata = None, {}


def load_model_bundle(model_file: Path = MODEL_FILE):
    loaded = joblib.load(model_file)
    if isinstance(loaded, dict) and "model" in loaded:
        metadata = loaded.get("metadata", {})
        if metadata.get("feature_names") not in (None, FEATURE_NAMES):
            raise ValueError("Model feature schema does not match this inference service.")
        trained_window = metadata.get("window_size_samples")
        if trained_window not in (None, WINDOW_SIZE):
            raise ValueError(f"Model window size {trained_window} does not match inference WINDOW_SIZE={WINDOW_SIZE}.")
        return loaded["model"], metadata
    return loaded, {"format_version": 0, "warning": "Legacy model without feature metadata."}


def validate_sensor_window(window_data) -> np.ndarray:
    values = np.asarray(window_data, dtype=float)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"Expected MQTT window with N x 3 numeric values; got {values.shape}.")
    if len(values) != WINDOW_SIZE:
        raise ValueError(f"Expected exactly {WINDOW_SIZE} samples (3 s at 10 Hz); got {len(values)}.")
    if not np.isfinite(values).all():
        raise ValueError("MQTT window contains non-finite values.")
    return values


def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT broker with result code {rc}"); client.subscribe(MQTT_TOPIC_DATA); print(f"Subscribed to {MQTT_TOPIC_DATA}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode()); device_id = payload.get("device", "unknown")
        window = validate_sensor_window(payload.get("window", []))
        features = np.asarray(extract_features(window), dtype=float).reshape(1, -1)
        is_fall = bool(model.predict(features)[0] == 1)
        print(f"[{'FALL DETECTED' if is_fall else 'ADL (Normal)'}] Model classification complete for {device_id}.")
        if is_fall:
            client.publish(MQTT_TOPIC_ALERT, json.dumps({"device": device_id, "event": "ML_CONFIRMED_FALL", "reason": "Machine Learning model confirmed the fall event"}))
            print(f"[MQTT] Published confirmed alert to {MQTT_TOPIC_ALERT}")
    except Exception as exc: print(f"[ERROR] Rejected sensor message: {exc}")


def main() -> None:
    global model, model_metadata
    try: model, model_metadata = load_model_bundle()
    except Exception as exc: raise SystemExit(f"Cannot load model at {MODEL_FILE}: {exc}") from exc
    print(f"Loaded model from {MODEL_FILE} (format {model_metadata.get('format_version', 0)}).")
    client = mqtt.Client(); client.on_connect = on_connect; client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60); client.loop_forever()


if __name__ == "__main__": main()
