# IoE-Based Fall Detection System for Elderly Care — Project Overview

**Repo:** https://github.com/kpcode11/FallDetection (branch: `feat/ML`)
**Course:** IoE Lab — Final Year Major Project
**Purpose of this document:** Single source of truth on project scope, current state, and next tasks. Written for both human reviewers and an AI coding agent picking up work on this repo.

---

## 1. Project Overview

**Problem:** Elderly people living alone are at high risk after a fall — the danger is often the delay before anyone finds out, not just the fall itself.

**Solution:** A wrist/pendant-worn ESP32 + accelerometer detects the physical signature of a fall (free-fall dip → impact spike → inactivity), gives the wearer a grace period to cancel a false alarm, confirms the event two ways (on-device threshold logic + a cloud-side ML classifier), and pushes a live alert to a caregiver-facing dashboard.

---

## 2. Hardware Components

| Component | Role |
|---|---|
| ESP32 Dev Board | Main processor — sensor reading, detection logic, WiFi, MQTT publish |
| MPU6050 (I2C: SDA=21, SCL=22) | Accelerometer + gyroscope — motion data source |
| Buzzer (GPIO25) | Audible alarm during grace period / confirmed fall |
| Red LED (GPIO27) | Fall-alert visual indicator |
| Green LED (GPIO26) | System health / WiFi status indicator |
| Pushbutton — SOS/Cancel (GPIO4) | Cancel false alarm during grace period, or manual panic trigger |
| Li-ion battery + charging module | *(pending)* — makes the device untethered/wearable |

Deliberately minimal sensor set (no GPS/GSM) to keep the core build low-cost while still demonstrating the full IoE loop.

---

## 3. Tech Stack

**Firmware** — `FallDetection.ino`
- Arduino IDE / C++
- Libraries: `Adafruit_MPU6050`, `Adafruit_Sensor`, `Wire.h`, `PubSubClient`
- Developed/tested in Wokwi simulator (VS Code extension), config in `wokwi.toml`

**Connectivity**
- MQTT over WiFi, broker: `broker.hivemq.com` (public, for prototyping)
- Topics: `ioe-lab/fall-detection/team41/sensor_data`, `ioe-lab/fall-detection/team41/alert`

**ML layer** — `ml/train.py`, `ml/server.py`
- Python: `scikit-learn` (RandomForestClassifier), `numpy`, `pandas`, `scipy` (Butterworth low-pass filter), `joblib`, `paho-mqtt`
- Features per 3-second window @ 200Hz: mean, std, min, max, range, SMA, peak jerk of acceleration magnitude
- Validation method: Leave-One-Subject-Out cross-validation
- `server.py` subscribes to the sensor-data topic, runs inference, republishes `ML_CONFIRMED_FALL` alerts

**Dashboard** — `dashboard/`
- React + Vite
- `mqtt.js` (WebSocket subscription), `recharts` (live accelerometer graph), `lucide-react` (icons)
- Custom design tokens defined in `DESIGN.md`

---

## 4. Features

1. On-device two-stage fall detection: free-fall (<~0.4g) followed by impact spike (>~2.2g) within 1 second
2. 8-second grace period with buzzer + flashing red LED, cancellable via SOS button
3. Manual SOS/panic button — instant alert regardless of sensor state
4. Real-time MQTT alert publishing on confirmed fall
5. Live caregiver dashboard — connection status + real-time accelerometer graph
6. ML confirmation layer — Random Forest re-verifies the fall from motion-window features, reducing false positives from a single hardcoded threshold
7. Green LED system/WiFi health indicator

---

## 5. Why This Qualifies as an IoE Project

| Pillar | How it's implemented |
|---|---|
| **Things** | ESP32, MPU6050, buzzer, LEDs, SOS button |
| **Data** | Raw accelerometer windows + fall events captured and transmitted live via MQTT, not just processed and discarded locally |
| **Process** | Two independent automated decision layers — on-device threshold algorithm + cloud ML classifier — plus grace-period/cancel logic governing escalation |
| **People** | Caregiver dashboard turns sensor data into a real-time, human-readable alert, closing the loop between physical event and human response |

This People-Process-Data-Things loop is what distinguishes the project from a plain embedded-systems build.

---

## 6. Current Status (as of `feat/ML` branch)

### Phase 1 update — real-data ML validation complete

The ML pipeline now parses real SisFall recordings, decimates their native
200 Hz samples by 20, and trains on exactly 30 samples per three-second window
to match the current ESP32 MQTT payload. The model was trained in WSL on 4,505
recordings, producing 47,927 windows across 38 Leave-One-Subject-Out folds.

| Metric | Result |
|---|---:|
| Accuracy | 76.16% |
| Fall precision | 64.95% |
| Fall recall (sensitivity) | 63.83% |
| Fall F1 | 64.39% |
| Specificity | 82.45% |
| ROC-AUC | 81.37% |

Confusion-matrix counts are TN=26,173, FP=5,573, FN=5,852, and TP=10,329.
These are offline SisFall results only; the dataset uses a waist-mounted sensor
and performed falls, so they are not wrist/pendant or real-world accuracy
claims. The generated model and evaluation artifacts live in the WSL project
copy and are intentionally gitignored.

### Done
- [x] `FallDetection.ino` — complete firmware: two-stage detection, grace period, SOS override, buzzer/LED feedback, MQTT publishing
- [x] Wokwi simulation fully configured — system demoable without physical hardware
- [x] MQTT integration working end-to-end (publish + subscribe tested in simulation)
- [x] React dashboard built and connected — live status + sensor graph via WebSocket
- [x] `ml/train.py` — feature extraction + Random Forest training pipeline with Leave-One-Subject-Out CV
- [x] `ml/server.py` — live MQTT inference service producing `ML_CONFIRMED_FALL` alerts

### Not done yet
- [ ] `ml/train.py` currently trains on **synthetic/mock fall data** (fallback path in `load_data()`), not a real dataset — model is unvalidated on real falls
- [ ] No physical hardware assembled or tested — everything so far is Wokwi-simulation only
- [ ] No battery/enclosure — wearable only in concept, not physical form
- [ ] No full end-to-end test with real hardware → real MQTT → real ML server → real dashboard

---

## 7. Next Tasks

### Phase 1 — Real data & model validation — complete

- [x] Parsed the real SisFall text recordings; synthetic data is now explicit smoke-test mode only
- [x] Aligned model input to the firmware's 10 Hz / 30-sample MQTT window
- [x] Added parser, decimation, SMA, model-artifact, and MQTT-window tests (7 passed in WSL)
- [x] Generated a metadata-bearing real-data model and evaluation report

### Phase 1 — Real data & model validation
- [ ] Download the public **SisFall** dataset (real subject fall + ADL recordings)
- [ ] Update `load_data()` in `ml/train.py` to parse SisFall's actual file format instead of falling back to synthetic data
- [ ] Retrain the model; record confusion matrix, accuracy, precision/recall for the results section
- [ ] Re-save `fall_detection_model.joblib` with the real-data-trained model

### Phase 2 — Physical hardware build
- [ ] Procure ESP32, MPU6050, buzzer, 2x LED, pushbutton
- [ ] Wire per existing pin mapping in `FallDetection.ino` (SDA=21, SCL=22, buzzer=25, button=4, red LED=27, green LED=26) — no firmware changes needed for basic bring-up
- [ ] Flash firmware to real ESP32; verify accelerometer readings against simulated thresholds — recalibrate `0.4g` / `2.2g` constants if real-world sensor noise differs from Wokwi's simulated values

### Phase 3 — End-to-end integration test
- [ ] Run `ml/server.py` continuously against the live device
- [ ] Simulate falls safely (drop sensor onto a cushion — never test on a person) and confirm the full chain: detect → grace period → MQTT alert → ML confirmation → dashboard update
- [ ] Measure and document time from fall event to dashboard alert appearing

### Phase 4 — Wearable packaging
- [ ] Add Li-ion battery + charging module (e.g. TP4056) for untethered operation
- [ ] Build/print a small wrist or pendant enclosure for the demo

### Phase 5 — Documentation & evaluation
- [ ] Write up the algorithm explanation (threshold + ML) with actual confusion matrix results from Phase 1
- [ ] Prepare a short comparison against commercial fall-detection products (expected accuracy, cost)
- [ ] Finalize presentation: Introduction → Architecture (People-Process-Data-Things mapping) → Results → Live Demo → Conclusion

---

## Notes for whoever picks this up next
- Existing firmware, dashboard, and ML scaffolding all work in simulation — don't rewrite what already works. The highest-value next step is Phase 1 (real dataset), since it's the only piece currently running on fake data.
- MQTT topic names are hardcoded with `team41` — fine to keep as-is unless there's a naming collision with another team on the same public broker.
- Public HiveMQ broker is acceptable for a lab demo; if asked, the known limitation is that it's unauthenticated/public, so anyone who knows the topic name can read the data.
