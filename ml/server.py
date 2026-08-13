import json
import numpy as np
import paho.mqtt.client as mqtt
import joblib
from train import extract_features  # Import the feature extraction logic

# --- Configuration ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_DATA = "ioe-lab/fall-detection/team41/sensor_data"
MQTT_TOPIC_ALERT = "ioe-lab/fall-detection/team41/alert"
MODEL_FILE = "fall_detection_model.joblib"

# --- Global State ---
print(f"Loading ML model from {MODEL_FILE}...")
try:
    model = joblib.load(MODEL_FILE)
    print("Model loaded successfully!")
except Exception as e:
    print(f"Error loading model: {e}")
    print("Please run train.py first to generate the model.")
    exit(1)

# --- MQTT Callbacks ---
def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT broker with result code {rc}")
    client.subscribe(MQTT_TOPIC_DATA)
    print(f"Subscribed to {MQTT_TOPIC_DATA}")

def on_message(client, userdata, msg):
    try:
        # Expecting JSON payload: {"device": "wearable-01", "window": [[ax,ay,az], [ax,ay,az], ...]}
        payload = json.loads(msg.payload.decode())
        device_id = payload.get("device", "unknown")
        window_data = payload.get("window", [])
        
        if not window_data:
            return
            
        print(f"\n[INFO] Received {len(window_data)} sensor readings from {device_id}")
        
        # Convert to numpy array (N x 3)
        window_acc = np.array(window_data)
        
        # 1. Extract features using the exact same logic as training
        features = extract_features(window_acc)
        
        # 2. Run Inference
        features_reshaped = np.array(features).reshape(1, -1)
        prediction = model.predict(features_reshaped)[0]
        
        # Fall = 1, ADL = 0
        is_fall = bool(prediction == 1)
        
        print(f"[{'🚨 FALL DETECTED' if is_fall else '✅ ADL (Normal)'}] Model classification complete.")
        
        # 3. Publish confirmation back if it's a fall
        if is_fall:
            alert_payload = json.dumps({
                "device": device_id,
                "event": "ML_CONFIRMED_FALL",
                "reason": "Machine Learning model confirmed the fall event"
            })
            client.publish(MQTT_TOPIC_ALERT, alert_payload)
            print(f"[MQTT] Published confirmed alert to {MQTT_TOPIC_ALERT}")
            
    except Exception as e:
        print(f"[ERROR] Failed to process message: {e}")

# --- Main ---
if __name__ == "__main__":
    print("Starting Fall Detection ML Service...")
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    
    # Blocking loop to the network, will not return until client calls disconnect()
    client.loop_forever()
