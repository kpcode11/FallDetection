import json
import paho.mqtt.client as mqtt

# --- Configuration ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_DATA = "ioe-lab/fall-detection/team41/sensor_data"

# Create a synthetic 30-sample window representing a fall
window = []
# 10 samples normal (1g)
for _ in range(10):
    window.append([0.0, 0.0, 1.0])
# 5 samples free fall (dip)
for _ in range(5):
    window.append([0.1, 0.1, 0.1])
# 5 samples impact (spike)
for _ in range(5):
    window.append([2.0, 2.0, 2.0])
# 10 samples normal
for _ in range(10):
    window.append([0.0, 0.0, 1.0])

payload = {
    "device": "wearable-01-simulator-test",
    "window": window
}

def on_publish(client, userdata, mid):
    print("Test MQTT payload successfully sent!")
    client.disconnect()

client = mqtt.Client()
client.on_publish = on_publish
client.connect(MQTT_BROKER, MQTT_PORT, 60)

print(f"Publishing simulated fall event to {MQTT_TOPIC_DATA}...")
client.publish(MQTT_TOPIC_DATA, json.dumps(payload))
client.loop_forever()
