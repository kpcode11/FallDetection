"""MQTT inference and WhatsApp notification service for a model produced by train.py."""
from __future__ import annotations

import json
import time
from pathlib import Path
import joblib
import numpy as np
import paho.mqtt.client as mqtt
from train import FEATURE_NAMES, WINDOW_SIZE, extract_features
from whatsapp_notifier import WhatsAppNotifier

MQTT_BROKER, MQTT_PORT = "broker.hivemq.com", 1883
MQTT_TOPIC_DATA = "ioe-lab/fall-detection/team41/sensor_data"
MQTT_TOPIC_ALERT = "ioe-lab/fall-detection/team41/alert"
MODEL_FILE = Path(__file__).resolve().parent / "fall_detection_model.joblib"
ML_CACHE_TTL_SECONDS = 20.0

model, model_metadata = None, {}
notifier = WhatsAppNotifier()
recent_ml_results: dict[str, dict[str, float | bool]] = {}


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
    print(f"Connected to MQTT broker with result code {rc}")
    client.subscribe([(MQTT_TOPIC_DATA, 0), (MQTT_TOPIC_ALERT, 0)])
    print(f"Subscribed to {MQTT_TOPIC_DATA} and {MQTT_TOPIC_ALERT}")


def handle_sensor_data(
    client,
    payload: dict,
    active_model=None,
    active_notifier: WhatsAppNotifier | None = None,
    now_fn=time.time,
) -> bool:
    clf = active_model if active_model is not None else model
    wa = active_notifier if active_notifier is not None else notifier
    device_id = payload.get("device", "unknown")
    window = validate_sensor_window(payload.get("window", []))
    features = np.asarray(extract_features(window), dtype=float).reshape(1, -1)
    is_fall = bool(clf.predict(features)[0] == 1)
    recent_ml_results[device_id] = {"is_fall": is_fall, "timestamp": now_fn()}
    print(f"[{'FALL DETECTED' if is_fall else 'ADL (Normal)'}] Model classification complete for {device_id}.")
    if is_fall:
        client.publish(
            MQTT_TOPIC_ALERT,
            json.dumps(
                {
                    "device": device_id,
                    "event": "ML_CONFIRMED_FALL",
                    "reason": "Machine Learning model confirmed the fall event",
                }
            ),
        )
        print(f"[MQTT] Published confirmed alert to {MQTT_TOPIC_ALERT}")
        if wa.alert_mode == "ml_immediate":
            wa.send_alert(
                device_id=device_id,
                event_type="ML_CONFIRMED_FALL",
                reason="Machine Learning model confirmed the fall event",
                ml_status="Confirmed by Random Forest Classifier",
            )
    return is_fall


def handle_alert_message(
    payload: dict,
    active_notifier: WhatsAppNotifier | None = None,
    now_fn=time.time,
) -> bool:
    wa = active_notifier if active_notifier is not None else notifier
    event_type = payload.get("event", "")
    # Ignore our own ML_CONFIRMED_FALL echo on MQTT_TOPIC_ALERT; FALL_ALERT comes from ESP32
    # after the 8-second grace period expires without cancellation, or on Manual SOS hold.
    if event_type != "FALL_ALERT":
        return False

    device_id = payload.get("device", "unknown")
    reason = payload.get("reason", "Fall detected")
    is_manual_sos = "manual sos" in reason.lower()

    cached = recent_ml_results.get(device_id)
    has_recent_ml = cached is not None and (now_fn() - float(cached["timestamp"])) <= ML_CACHE_TTL_SECONDS
    ml_confirmed = bool(cached["is_fall"]) if has_recent_ml else None

    if is_manual_sos:
        ml_status = "N/A (Manual SOS Button Pressed)"
    elif ml_confirmed is True:
        ml_status = "Confirmed by Random Forest Classifier"
    elif ml_confirmed is False:
        if wa.alert_mode == "ml_strict":
            print(f"[WhatsApp] Suppressed FALL_ALERT for {device_id} in ml_strict mode (ML classified window as ADL).")
            return False
        ml_status = "Not confirmed by ML (On-device threshold + 8s no-response trigger)"
    else:
        if wa.alert_mode == "ml_strict":
            print(f"[WhatsApp] Suppressed FALL_ALERT for {device_id} in ml_strict mode (no recent ML window confirmation).")
            return False
        ml_status = "No recent ML window received (On-device threshold trigger)"

    return wa.send_alert(
        device_id=device_id,
        event_type=event_type,
        reason=reason,
        ml_status=ml_status,
    )


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        if msg.topic == MQTT_TOPIC_DATA:
            handle_sensor_data(client, payload)
        elif msg.topic == MQTT_TOPIC_ALERT:
            handle_alert_message(payload)
    except Exception as exc:
        print(f"[ERROR] Rejected MQTT message on {msg.topic}: {exc}")


def main() -> None:
    global model, model_metadata
    try:
        model, model_metadata = load_model_bundle()
    except Exception as exc:
        raise SystemExit(f"Cannot load model at {MODEL_FILE}: {exc}") from exc
    print(f"Loaded model from {MODEL_FILE} (format {model_metadata.get('format_version', 0)}).")
    print(
        f"WhatsApp notifier: provider={notifier.provider}, "
        f"configured={notifier.is_configured()}, mode={notifier.alert_mode}"
    )
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
