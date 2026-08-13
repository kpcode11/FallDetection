/*
  IoE-Based Fall Detection System for Elderly Care
  ---------------------------------------------------
  Wokwi prototype firmware

  Hardware simulated:
    - ESP32 Dev Kit v1
    - MPU6050 (accelerometer + gyroscope)  -> I2C (SDA=21, SCL=22)
    - Buzzer                                -> GPIO25
    - SOS pushbutton                        -> GPIO4  (INPUT_PULLUP)
    - Red LED  (fall alert indicator)       -> GPIO27
    - Green LED (system / WiFi OK)          -> GPIO26

  Algorithm:
    A classic two-stage wearable fall-detection approach:
      1. FREE FALL   - total acceleration magnitude drops below ~0.4 g
      2. IMPACT      - within a short window, magnitude spikes above ~2.2 g
    If both stages occur in sequence, the device enters a short grace period
    (CONFIRM_WINDOW_MS) during which the wearer can cancel a false alarm by
    pressing the SOS button. If they don't respond, the fall is confirmed and
    an alert is published over MQTT (simulating the cloud/caregiver dashboard
    alert described in the project report). The SOS button also works as a
    manual, instant panic button at any time.

  Note on WiFi in Wokwi:
    Wokwi's ESP32 simulation has real internet access via the "Wokwi-GUEST"
    open network, so this sketch can genuinely publish to a public MQTT
    broker (broker.hivemq.com) from inside the simulator - no real hardware
    needed to test the cloud-alert path end to end.
*/

#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <WiFi.h>
#include <PubSubClient.h>

// ---------------- Pin Definitions ----------------
#define BUZZER_PIN     25
#define SOS_BUTTON_PIN 4
#define RED_LED_PIN    27
#define GREEN_LED_PIN  26

// ---------------- WiFi / MQTT ----------------
const char* WIFI_SSID     = "Wokwi-GUEST";   // Wokwi's built-in internet-connected network
const char* WIFI_PASSWORD = "";
const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* MQTT_TOPIC    = "ioe-lab/fall-detection/team41/alert";
const char* DEVICE_ID     = "wearable-01";

WiFiClient   espClient;
PubSubClient mqtt(espClient);

// ---------------- Sensor ----------------
Adafruit_MPU6050 mpu;

// ---------------- Fall Detection Tuning ----------------
const float FREE_FALL_G   = 0.4;              // below this  -> possible free fall
const float IMPACT_G      = 2.2;              // above this  -> impact
const unsigned long FALL_WINDOW_MS    = 1000;  // must see impact within this time
const unsigned long CONFIRM_WINDOW_MS = 8000;  // grace period to cancel a false alarm

enum State { NORMAL, FREE_FALL, IMPACT_PENDING_CONFIRM, ALERT_ACTIVE };
State state = NORMAL;

unsigned long freeFallTime    = 0;
unsigned long alertPendingTime = 0;

// ---------------- Setup ----------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== IoE Fall Detection System booting ===");

  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(SOS_BUTTON_PIN, INPUT_PULLUP);

  Wire.begin();
  if (!mpu.begin()) {
    Serial.println("MPU6050 not found - check wiring!");
    while (1) delay(10);
  }
  mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  Serial.println("MPU6050 ready.");

  connectWiFi();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  connectMQTT();

  Serial.println("System armed. Monitoring for falls...\n");
}

// ---------------- Main Loop ----------------
void loop() {
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  // Convert m/s^2 -> g, then take the magnitude of the 3-axis vector
  float ax = a.acceleration.x / 9.81;
  float ay = a.acceleration.y / 9.81;
  float az = a.acceleration.z / 9.81;
  float magnitude = sqrt(ax * ax + ay * ay + az * az);

  bool sosPressed = (digitalRead(SOS_BUTTON_PIN) == LOW);

  switch (state) {

    case NORMAL:
      digitalWrite(GREEN_LED_PIN, HIGH);
      digitalWrite(RED_LED_PIN, LOW);
      noTone(BUZZER_PIN);

      if (magnitude < FREE_FALL_G) {
        state = FREE_FALL;
        freeFallTime = millis();
        Serial.println("[STATE] Free-fall signature detected, watching for impact...");
      }
      if (sosPressed) {
        triggerAlert("Manual SOS button pressed");
      }
      break;

    case FREE_FALL:
      if (magnitude > IMPACT_G) {
        Serial.println("[STATE] Impact detected right after free-fall -> possible fall!");
        state = IMPACT_PENDING_CONFIRM;
        alertPendingTime = millis();
      } else if (millis() - freeFallTime > FALL_WINDOW_MS) {
        state = NORMAL; // no impact followed -> false alarm, ignore
      }
      if (sosPressed) {
        triggerAlert("Manual SOS button pressed");
      }
      break;

    case IMPACT_PENDING_CONFIRM:
      // Grace period: flash red LED + gentle beep, user can cancel with SOS button
      digitalWrite(RED_LED_PIN, (millis() / 200) % 2);
      tone(BUZZER_PIN, 1000);

      if (sosPressed) {
        Serial.println("[STATE] User cancelled the alert - they're OK.");
        state = NORMAL;
        noTone(BUZZER_PIN);
      } else if (millis() - alertPendingTime > CONFIRM_WINDOW_MS) {
        triggerAlert("Fall confirmed - no response from wearer");
      }
      break;

    case ALERT_ACTIVE:
      digitalWrite(RED_LED_PIN, HIGH);
      tone(BUZZER_PIN, 2000);
      if (sosPressed) {
        Serial.println("[STATE] Alert acknowledged. Resetting to normal.");
        state = NORMAL;
        noTone(BUZZER_PIN);
      }
      break;
  }

  delay(100); // ~10 Hz sampling, plenty for fall detection
}

// ---------------- Helper Functions ----------------
void triggerAlert(const char* reason) {
  state = ALERT_ACTIVE;
  Serial.print("[ALERT] ");
  Serial.println(reason);
  publishAlert(reason);
}

void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println(" connected!");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());
}

void connectMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Connecting to MQTT broker...");
    String clientId = String(DEVICE_ID) + "-" + String(random(0xffff), HEX);
    if (mqtt.connect(clientId.c_str())) {
      Serial.println(" connected.");
    } else {
      Serial.print(" failed, rc=");
      Serial.print(mqtt.state());
      Serial.println(" retrying in 2s");
      delay(2000);
    }
  }
}

void publishAlert(const char* reason) {
  if (!mqtt.connected()) connectMQTT();
  String payload = String("{\"device\":\"") + DEVICE_ID +
                    "\",\"event\":\"FALL_ALERT\",\"reason\":\"" + reason +
                    "\",\"timestamp\":" + String(millis()) + "}";
  mqtt.publish(MQTT_TOPIC, payload.c_str());
  Serial.print("[MQTT] Published to ");
  Serial.print(MQTT_TOPIC);
  Serial.print(": ");
  Serial.println(payload);
}
