/*
  IoE-Based Fall Detection System for Elderly Care
  ---------------------------------------------------
  Real-hardware firmware (ESP32 + MPU6050 clone + buzzer + LEDs + SOS button)

  Hardware:
    - ESP32 Dev Kit v1
    - MPU6050 / MPU6500 (accelerometer + gyroscope) -> I2C (SDA=21, SCL=22)
    - Buzzer                                -> GPIO25
    - SOS pushbutton                        -> GPIO4  (INPUT_PULLUP)
    - Red LED  (fall alert indicator)       -> GPIO27
    - Green LED (system / WiFi OK)          -> GPIO26

  Algorithm:
    1. FREE FALL - total acceleration magnitude drops below ~0.4 g
    2. IMPACT    - shortly after, magnitude spikes above ~1.8 g
    If both occur in sequence, the device starts a grace period
    (CONFIRM_WINDOW_MS) during which the wearer can cancel a false alarm.
    If they don't respond, the fall is confirmed and an alert is published
    over MQTT.

  HOW THE SOS BUTTON WORKS (what you hear tells you what to press):
    Silent, green LED on     : HOLD the button for 1 second -> manual SOS alert
                               (red LED lights while you hold)
    FAST BEEPING + red flash : fall suspected, 8 s grace period
                               -> CLICK once to cancel ("I'm OK")
    SOLID LOUD TONE          : alert has been sent
                               -> CLICK once to acknowledge and silence it
    After any click that cancels/acknowledges, the button is ignored for
    1.5 seconds so a double tap or contact bounce can never create a new SOS.
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
// const char* WIFI_SSID     = "vivo V30 Pro";
const char* WIFI_SSID     = "Yoyo";   // Wokwi's built-in internet-connected network
// const char* WIFI_PASSWORD = "Sandhya@2246";
const char* WIFI_PASSWORD = "Keshav911";
const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* MQTT_TOPIC_ALERT = "ioe-lab/fall-detection/team41/alert";
const char* MQTT_TOPIC_DATA  = "ioe-lab/fall-detection/team41/sensor_data";
const char* DEVICE_ID     = "wearable-01";

WiFiClient   espClient;
PubSubClient mqtt(espClient);

// ---------------- Sensor Buffer (ML Integration) ----------------
const int WINDOW_SIZE = 30; // 3 seconds at 10Hz
float window_ax[WINDOW_SIZE];
float window_ay[WINDOW_SIZE];
float window_az[WINDOW_SIZE];
int buffer_idx = 0;

// ---------------- Sensor ----------------
Adafruit_MPU6050 mpu;

// ---------------- Fall Detection Tuning ----------------
const float FREE_FALL_G   = 0.4;               // below this  -> possible free fall
const float IMPACT_G      = 1.8;               // above this  -> impact
const unsigned long FALL_WINDOW_MS    = 4000;  // max time between free fall and impact
const unsigned long CONFIRM_WINDOW_MS = 8000;  // grace period to cancel a false alarm
const unsigned long SAMPLE_INTERVAL_MS = 100;  // sensor sampling: 10 Hz

// ---------------- Button Tuning ----------------
const unsigned long DEBOUNCE_MS       = 40;    // contact must be stable this long to count
const unsigned long SOS_HOLD_MS       = 1000;  // hold time for manual SOS (set to 0 for instant SOS)
const unsigned long BUTTON_LOCKOUT_MS = 1500;  // button ignored this long after cancel/acknowledge/alert

enum State { NORMAL, FREE_FALL, IMPACT_PENDING_CONFIRM, ALERT_ACTIVE };
State state = NORMAL;

unsigned long freeFallTime     = 0;
unsigned long alertPendingTime = 0;
unsigned long lastSampleTime   = 0;

// ---------------- Button state ----------------
bool btnRaw = false;                  // last raw reading (true = pressed)
bool btnStable = false;               // debounced state (true = pressed)
unsigned long btnRawChangedAt = 0;    // when the raw reading last changed
unsigned long btnPressStart = 0;      // when the current debounced press began
bool pressEvent = false;              // true for one loop when a new press is confirmed
bool holdHandled = true;              // this press was already used (or must be ignored)
unsigned long ignoreButtonUntil = 0;  // button lockout deadline

// ---------------- Buzzer state ----------------
int buzzerFreq = 0;                   // 0 = off

// ---------------- Setup ----------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== IoE Fall Detection System booting ===");

  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(SOS_BUTTON_PIN, INPUT_PULLUP);

  // Start with the real button state; a press that is already held at boot is ignored.
  btnRaw = btnStable = (digitalRead(SOS_BUTTON_PIN) == LOW);
  holdHandled = true;

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
  mqtt.setBufferSize(1024); // Increase buffer size for large JSON arrays
  connectMQTT();

  Serial.println("System armed. Monitoring for falls...");
  Serial.println("  Hold SOS 1 s = manual alert | Click = cancel / acknowledge\n");
}

// ---------------- Main Loop ----------------
// The loop runs about every 10 ms so button presses are never missed.
// Sensor sampling still happens at 10 Hz (every SAMPLE_INTERVAL_MS).
void loop() {
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  updateButton();
  if (pressEvent) {
    Serial.println("[BUTTON] press detected");
  }

  unsigned long now = millis();
  bool sampleTick = (now - lastSampleTime >= SAMPLE_INTERVAL_MS);
  float magnitude = 1.0;

  if (sampleTick) {
    lastSampleTime = now;

    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);

    // Convert m/s^2 -> g, then take the magnitude of the 3-axis vector
    float ax = a.acceleration.x / 9.81;
    float ay = a.acceleration.y / 9.81;
    float az = a.acceleration.z / 9.81;
    magnitude = sqrt(ax * ax + ay * ay + az * az);

    // Store in circular buffer
    window_ax[buffer_idx] = ax;
    window_ay[buffer_idx] = ay;
    window_az[buffer_idx] = az;
    buffer_idx = (buffer_idx + 1) % WINDOW_SIZE;
  }

  switch (state) {

    case NORMAL:
      digitalWrite(GREEN_LED_PIN, HIGH);
      setBuzzer(0);
      // Red LED lights while a valid SOS hold is in progress (visual feedback)
      digitalWrite(RED_LED_PIN,
                   (btnStable && !holdHandled && btnPressStart >= ignoreButtonUntil) ? HIGH : LOW);

      if (sampleTick && magnitude < FREE_FALL_G) {
        state = FREE_FALL;
        freeFallTime = millis();
        digitalWrite(RED_LED_PIN, LOW);
        Serial.println("[STATE] Free-fall signature detected, watching for impact...");
      } else if (manualSosRequested()) {
        triggerAlert("Manual SOS button pressed");
      }
      break;

    case FREE_FALL:
      if (sampleTick) {
        if (magnitude > IMPACT_G) {
          Serial.println("[STATE] Impact detected right after free-fall -> possible fall!");
          state = IMPACT_PENDING_CONFIRM;
          alertPendingTime = millis();
          // Tier 2 ML: Stream the buffered window to the cloud for confirmation
          publishWindowData();
        } else if (millis() - freeFallTime > FALL_WINDOW_MS) {
          state = NORMAL; // no impact followed -> false alarm, ignore
        }
      }
      if (state == FREE_FALL && manualSosRequested()) {
        triggerAlert("Manual SOS button pressed");
      }
      break;

    case IMPACT_PENDING_CONFIRM: {
      // Grace period: FAST BEEPING + flashing red LED. CLICK the button to cancel.
      bool on = ((millis() / 250) % 2) == 0;
      digitalWrite(RED_LED_PIN, on ? HIGH : LOW);
      setBuzzer(on ? 1000 : 0);

      if (buttonClicked()) {
        Serial.println("[STATE] User cancelled the alert - they're OK.");
        state = NORMAL;
        setBuzzer(0);
        digitalWrite(RED_LED_PIN, LOW);
        lockButton();
      } else if (millis() - alertPendingTime > CONFIRM_WINDOW_MS) {
        triggerAlert("Fall confirmed - no response from wearer");
      }
      break;
    }

    case ALERT_ACTIVE:
      // Alert already sent: SOLID LOUD TONE. CLICK the button to acknowledge and silence.
      digitalWrite(RED_LED_PIN, HIGH);
      setBuzzer(2000);

      if (buttonClicked()) {
        Serial.println("[STATE] Alert acknowledged. Resetting to normal.");
        state = NORMAL;
        setBuzzer(0);
        digitalWrite(RED_LED_PIN, LOW);
        lockButton();
      }
      break;
  }

  delay(10);
}

// ---------------- Button Helpers ----------------

// Reads the button and updates the debounced state. Call once per loop.
void updateButton() {
  unsigned long now = millis();
  bool raw = (digitalRead(SOS_BUTTON_PIN) == LOW);

  if (raw != btnRaw) {            // reading changed -> restart the stability timer
    btnRaw = raw;
    btnRawChangedAt = now;
  }

  pressEvent = false;
  if (raw != btnStable && (now - btnRawChangedAt) >= DEBOUNCE_MS) {
    btnStable = raw;              // reading has been stable long enough -> accept it
    if (btnStable) {
      pressEvent = true;          // a brand-new press
      btnPressStart = now;
      holdHandled = false;
    }
  }
}

// True once per press, but only when the button is not locked out.
// Used to cancel (grace period) and to acknowledge (active alert).
bool buttonClicked() {
  return pressEvent && millis() >= ignoreButtonUntil;
}

// True once when the button has been held for SOS_HOLD_MS (manual SOS).
// The press must have started after any lockout, and fires only once per press.
bool manualSosRequested() {
  if (!btnStable || holdHandled) return false;
  if (btnPressStart < ignoreButtonUntil) return false;
  if (millis() - btnPressStart < SOS_HOLD_MS) return false;
  holdHandled = true;
  return true;
}

// Ignore the button for a short time and mark the current press as used.
void lockButton() {
  ignoreButtonUntil = millis() + BUTTON_LOCKOUT_MS;
  holdHandled = true;
}

// ---------------- Buzzer Helper ----------------
// Only talks to the tone driver when the requested sound actually changes.
void setBuzzer(int freq) {
  if (freq == buzzerFreq) return;
  buzzerFreq = freq;
  if (freq > 0) {
    tone(BUZZER_PIN, freq);
  } else {
    noTone(BUZZER_PIN);
  }
}

// ---------------- Helper Functions ----------------
void triggerAlert(const char* reason) {
  state = ALERT_ACTIVE;
  lockButton();   // the press/bounce that caused this must not instantly acknowledge it
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
  mqtt.publish(MQTT_TOPIC_ALERT, payload.c_str());
  Serial.print("[MQTT] Published to ");
  Serial.print(MQTT_TOPIC_ALERT);
  Serial.print(": ");
  Serial.println(payload);
}

void publishWindowData() {
  if (!mqtt.connected()) connectMQTT();
  Serial.println("[MQTT] Publishing sensor window to ML service...");

  // Construct JSON array string manually to save memory
  String payload = "{\"device\":\"" + String(DEVICE_ID) + "\",\"window\":[";
  for (int i = 0; i < WINDOW_SIZE; i++) {
    // Read from oldest to newest in circular buffer
    int idx = (buffer_idx + i) % WINDOW_SIZE;
    payload += "[" + String(window_ax[idx], 2) + "," +
                     String(window_ay[idx], 2) + "," +
                     String(window_az[idx], 2) + "]";
    if (i < WINDOW_SIZE - 1) payload += ",";
  }
  payload += "]}";

  mqtt.publish(MQTT_TOPIC_DATA, payload.c_str());
  Serial.println("[MQTT] Window data sent.");
}
