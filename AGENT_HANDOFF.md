# Fall Detection Project — Complete Agent Handoff Guide

This document is the canonical operating guide for this repository. It exists so that a future AI agent or developer can pick up the project with minimal confusion, without re-discovering the setup, environment, commands, or simulation flow from scratch.

The project is a fall-detection system built around:
- ESP32 firmware in `FallDetection.ino`
- Wokwi simulation with `diagram.json` and `wokwi.toml`
- MQTT-based alert flow
- React dashboard in `dashboard/`
- Python ML training/inference in `ml/`
- SisFall real dataset in `SisFall_dataset/`

This guide reflects the setup and validation workflow that was actually used in this environment.

---

## 1. Project goal

This project detects a fall using a wearable-style sensor pipeline:

1. MPU6050 measures acceleration and gyroscope data.
2. ESP32 firmware monitors motion magnitude over time.
3. When a free-fall signature and impact signature occur in sequence, the firmware enters a confirmation window.
4. If the wearer does not cancel, it publishes an alert over MQTT.
5. The dashboard displays live alerts and sensor data.
6. The ML service can validate or confirm falls from a window of sensor data.

The design is intended for a lab/demo environment, not production-level security.

---

## 2. Repository layout

Important folders and files:

- `FallDetection.ino` — main ESP32 firmware
- `diagram.json` — Wokwi hardware wiring
- `wokwi.toml` — Wokwi firmware binary paths
- `.vscode/arduino.json` — Arduino board config
- `dashboard/` — Vite + React dashboard
- `ml/` — training, MQTT inference service, tests
- `SisFall_dataset/` — real extracted dataset
- `build/` — compiled firmware output
- `README.md` — project summary
- `SETUP.md` — full environment/setup guide

---

## 3. Hardware model used by the project

The firmware expects the following pins:

| Device | ESP32 Pin |
| --- | --- |
| MPU6050 SDA | GPIO21 |
| MPU6050 SCL | GPIO22 |
| Buzzer | GPIO25 |
| SOS button | GPIO4 |
| Red LED | GPIO27 |
| Green LED | GPIO26 |

The project uses:
- ESP32 DevKit V1
- MPU6050 module
- active buzzer
- push button
- red LED
- green LED
- breadboard + jumper wires

### Beginner shopping list

Buy these parts for the first breadboard demonstration:

| Item | Quantity | Recommendation |
| --- | ---: | --- |
| ESP32 DevKit V1 | 1 | Choose a board with USB and pre-soldered header pins if possible |
| MPU6050 breakout module | 1 | Prefer a module with clearly labelled `VCC`, `GND`, `SDA`, and `SCL` pins |
| Full-size solderless breadboard | 1 | 830-point board is easiest for a beginner |
| Active 3.3 V buzzer module | 1 | Use a low-current module; do not buy a high-power siren |
| Momentary push button | 1 | 6 mm tactile button is suitable |
| Red 5 mm LED | 1 | Fall-alert indicator |
| Green 5 mm LED | 1 | System-status indicator |
| 220 ohm resistors | 2 | One for each LED; buy a 10-pack or resistor assortment |
| 330 ohm resistors | 2 optional | Safe alternatives if 220 ohm is unavailable |
| Male-to-male Dupont jumper wires | 1 bundle | Buy at least 40 wires, preferably 65 or 120 assorted pieces |
| Male-to-female Dupont wires | 1 small bundle | Buy 10-20 in case the sensor or buzzer has female sockets |
| Female-to-female Dupont wires | 1 small bundle | Optional, useful for modules with male pins |
| USB data cable | 1 | Match the ESP32 connector: micro-USB or USB-C; ensure it supports data |
| USB power bank | 1 optional | Easiest safe battery-style power source for a later demo |

Buy one spare ESP32, MPU6050, button, and buzzer only if the budget allows. LEDs and resistors are inexpensive, so buying an assortment avoids delays.

Do not buy a bare lithium cell for the first build. A USB power bank is safer and simpler for the later standalone demonstration.

### Breadboard wiring procedure

Power off and disconnect the USB cable while wiring. The ESP32 uses 3.3 V logic.

1. Place the ESP32 across the center gap of the breadboard so the two pin rows are on opposite sides.
2. Connect ESP32 `GND` to the breadboard ground rail.
3. Connect the MPU6050 `VCC` to ESP32 `3V3`, not `5V`.
4. Connect MPU6050 `GND` to the ground rail.
5. Connect MPU6050 `SDA` to ESP32 `GPIO21`.
6. Connect MPU6050 `SCL` to ESP32 `GPIO22`.
7. Connect the buzzer negative pin to ground and its signal/positive pin to `GPIO25`. Use only a low-current 3.3 V buzzer module. If the buzzer is marked `S`, connect `S` to GPIO25, `+` to 3.3 V, and `-` to GND; follow the module label.
8. Place the push button across the breadboard center gap. Connect one side to `GPIO4` and the opposite side to ground. The firmware already enables `INPUT_PULLUP`, so no external button resistor is required.
9. For the red LED, connect `GPIO27` to a 220 ohm resistor, the resistor to the LED long leg/anode, and the LED short leg/cathode to ground.
10. For the green LED, connect `GPIO26` to a second 220 ohm resistor, the resistor to the LED long leg/anode, and the LED short leg/cathode to ground.

The final wiring table is:

| ESP32 pin | Connect to |
| --- | --- |
| `3V3` | MPU6050 `VCC` |
| `GND` | MPU6050 `GND`, buzzer `-`, button side, both LED cathodes |
| `GPIO21` | MPU6050 `SDA` |
| `GPIO22` | MPU6050 `SCL` |
| `GPIO25` | buzzer signal/input |
| `GPIO4` | push-button side; other button side goes to GND |
| `GPIO27` | 220 ohm resistor, then red LED anode |
| `GPIO26` | 220 ohm resistor, then green LED anode |

### First hardware test

1. Leave the sensor and LEDs visible on the breadboard.
2. Connect the ESP32 to the laptop with the USB data cable.
3. Upload or otherwise run the compiled firmware using the Arduino environment you choose.
4. Open Serial Monitor at `115200` baud.
5. Confirm `MPU6050 ready.` and Wi-Fi/MQTT connection messages.
6. Press the button briefly. This should produce a manual SOS alert.
7. Confirm the red LED and buzzer behavior.
8. Test motion only after the basic button test works.

### Later battery operation

For the first battery-style demonstration, use a USB power bank connected through the ESP32 USB port. This avoids exposing the board to an unknown lithium-cell voltage.

Never connect a raw 3.7 V lithium battery directly to the ESP32 `3V3` pin. A raw cell needs a suitable charger, protection circuit, switch, and regulated power converter. If using a battery module later, use a regulated 5 V output into the ESP32 USB/`VIN` input and verify its polarity before connecting it.

---

## 4. Verified working environment

The working environment used here was:

- Windows 11 host
- WSL2 with Ubuntu
- VS Code + Wokwi extension on Windows
- Arduino CLI installed inside WSL

The firmware was compiled successfully using the following path and board:

```bash
wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection ; mkdir -p build ; arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 --build-path build FallDetection.ino'
```

Verified result:
- exit code 0
- program storage used: 943078 bytes / 1310720 bytes
- dynamic memory used: 49312 bytes / 327680 bytes

This proves the firmware is compiling correctly.

---

## 5. The correct WSL path to the project

Use WSL in Ubuntu and then cd to:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
```

This is the correct repo path in the Linux environment. Do not attempt to use `/mnt/c/...` from a normal Windows PowerShell shell unless you are explicitly invoking a WSL command.

If you are already in PowerShell, use:

```powershell
wsl.exe
```

Then inside the WSL prompt:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
```

---

## 6. Required tools and installation order

### 6.1 Install WSL2

From PowerShell:

```powershell
wsl.exe --list --verbose
```

If Ubuntu is not installed, install it from the Microsoft Store or via WSL setup.

### 6.2 Install base Linux tools in WSL

```bash
sudo apt-get update
sudo apt-get install -y nodejs npm python3-venv build-essential unzip curl
```

### 6.3 Install Arduino CLI in WSL

This is the reliable installation route used for the project:

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
arduino-cli version
arduino-cli core update-index
arduino-cli core install esp32:esp32
arduino-cli lib install 'PubSubClient'
arduino-cli lib install 'Adafruit MPU6050'
```

Use these exact libraries with this board family:

```text
Board: esp32:esp32:esp32doit-devkit-v1
Libraries: PubSubClient, Adafruit MPU6050
```

### 6.4 Install Node dashboard dependencies

From the repo root in WSL:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
npm install
cd dashboard
npm install
```

### 6.5 Install Python ML dependencies

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
python3 -m venv ~/.venvs/falldetection
source ~/.venvs/falldetection/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ml/requirements.txt
```

---

## 7. Project build and run sequence

### 7.1 Compile firmware

From WSL:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
mkdir -p build
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 --build-path build FallDetection.ino
ls -l build
```

Expected files include:

```text
build/FallDetection.ino.bin
build/FallDetection.ino.elf
```

### 7.2 Run Wokwi simulator

In VS Code on Windows:

1. Open the repository in VS Code.
2. Press Ctrl+Shift+P.
3. Run: `Wokwi: Start Simulator`
4. The simulator reads the firmware binary from `build/` as configured in `wokwi.toml`.
5. Open the serial monitor in the Wokwi terminal.

The simulator does not need a physical ESP32 connected.

### 7.3 Run the dashboard

Open a second WSL terminal and run:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection/dashboard
npm run dev -- --host 0.0.0.0
```

Open the browser to:

```text
http://localhost:5173/
```

The dashboard browser client connects to HiveMQ over secure WebSockets at:

```text
wss://broker.hivemq.com:8884/mqtt
```

Wait for `Connected to HiveMQ` in the dashboard before triggering SOS or simulating a fall.

### 7.4 Run the ML service

Open a third WSL terminal:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection/ml
source ~/.venvs/falldetection/bin/activate
python server.py
```

Expected MQTT topics:

- sensor data topic: `ioe-lab/fall-detection/team41/sensor_data`
- alert topic: `ioe-lab/fall-detection/team41/alert`

---

## 8. How to simulate a fall in Wokwi

This is the key behavior to demonstrate.

### Method 1: Use the MPU6050 controls

1. Start the simulation.
2. Click the MPU6050 sensor component in Wokwi.
3. A popup with X/Y/Z values appears.
4. Drag the values to create a low-acceleration sequence first.
5. Then quickly set a large spike in acceleration.

The firmware logic does:

```cpp
float magnitude = sqrt(ax * ax + ay * ay + az * az);
```

Then it checks:
- below about 0.4 g = possible free fall
- above about 1.8 g shortly after = possible impact

A valid test sequence is:

- first: very low values close to 0
- then: sudden large values such as 2.0–3.0 g on one or more axes

This creates the sequence the firmware expects.

### Method 2: Press the SOS button

The red SOS button triggers a manual alert immediately. This is the fastest demonstration path if you only want to show the alert system working.

For dashboard verification, open the dashboard first and wait for `Connected to HiveMQ`, then press SOS again. The live graph and alert feed use separate MQTT topics, so a working graph does not by itself mean that an alert has been published. Alerts sent before the dashboard connected are not replayed because this demo does not use retained MQTT messages.

---

## 9. How the firmware logic works

The core logic in `FallDetection.ino` is:

- measure acceleration magnitude
- maintain a circular sensor buffer window
- if magnitude falls below threshold, transition to FREE_FALL state
- if a large impact follows, enter IMPACT_PENDING_CONFIRM state
- buzzer and red LED activate
- if no cancellation occurs before timeout, publish a fall alert via MQTT
- SOS button can cancel or trigger alert immediately

The firmware intentionally uses a grace window so false positives can be cancelled.

---

## 10. Real dataset installation

The project expects the actual SisFall dataset to exist under:

```text
SisFall_dataset/
```

The dataset is usually downloaded as `SisFall.zip` in the Windows Downloads folder. Extract it from WSL with:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
mkdir -p ~/sisfall-archive
unzip -q /mnt/c/Users/KESHAV/Downloads/SisFall.zip -d ~/sisfall-archive
unzip -q ~/sisfall-archive/SisFall_dataset.zip -d .
```

Then verify the dataset:

```bash
find SisFall_dataset -type f -name '*.txt' | wc -l
find SisFall_dataset -type f -name 'D*.txt' | wc -l
find SisFall_dataset -type f -name 'F*.txt' | wc -l
```

---

## 11. ML training

To train using the real dataset:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
source ~/.venvs/falldetection/bin/activate
python ml/train.py \
  --data-dir SisFall_dataset \
  --model-output ml/fall_detection_model.joblib \
  --artifacts-dir ml/artifacts
```

This creates:
- `ml/fall_detection_model.joblib`
- `ml/artifacts/evaluation.json`
- `ml/artifacts/evaluation.md`

The model and artifacts should remain ignored and not be committed.

---

## 12. ML tests

Run the unit tests with:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
source ~/.venvs/falldetection/bin/activate
python -m unittest discover -s ml/tests -v
```

The project was designed around a test suite that checks the training pipeline and expected outputs.

---

## 13. Dashboard checks

Run:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection/dashboard
npm run lint
npm run build
```

---

## 14. Wokwi binary status and what it means

The build directory now contains the compiled firmware output. The presence of:

```text
build/FallDetection.ino.bin
build/FallDetection.ino.elf
```

means the firmware is generated and ready for Wokwi.

This is the key checkpoint. Once these files are present, you do not need to recompile unless the code changes.

---

## 15. Demo strategy for a professor / presentation

### Best low-risk demo option
Use Wokwi, because it is stable and does not require a physical ESP32 board.

Demo flow:

1. Start Wokwi
2. Open Serial Monitor
3. Click MPU6050 and manipulate acceleration values
4. Show free-fall + impact sequence
5. Watch the serial logs and state transitions
6. Show SOS button trigger or alert publication
7. Explain the MQTT and dashboard architecture

### If you want to show the physical prototype
You can also use a real ESP32 connected by USB. However, the presentation is usually smoother with Wokwi because it removes hardware debugging risk.

---

## 16. Troubleshooting guide

### WSL path issue

This fails:

```powershell
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
```

when run in PowerShell directly. Use WSL first:

```powershell
wsl.exe
```

Then inside Linux:

```bash
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
```

### Arduino CLI compile hangs or takes long

This is normal on the first ESP32 build. The compile is doing real toolchain work, not trying to talk to hardware.

### Wokwi says no binary found

Check that `build/FallDetection.ino.bin` and `.elf` exist. If they do not, compile again.

### MQTT not showing data

Check that the firmware and dashboard are both running, and that the MQTT topics match exactly.

### Dashboard shows nothing

Ensure the browser can access the HiveMQ broker over WebSockets and that the firmware or publisher is active.

---

## 17. Important constraints for future agents

Do not do the following unless required:

- Do not change the project logic in `FallDetection.ino` unless clearly requested.
- Do not remove the validated board config or Wokwi path.
- Do not commit the dataset, model, build output, or dependency folders.
- Do not switch away from the proven WSL + Arduino CLI path unless you have a clear reason.
- Keep the project portable between Windows VS Code and WSL.

---

## 18. Final status of the project

As of this handoff:
- the firmware build was completed successfully using Arduino CLI in WSL
- the generated binary exists in `build/`
- Wokwi is the correct simulator path for the project
- documentation and environment flow are in place for a future agent to continue quickly

This project is effectively ready for simulation and presentation without needing to rediscover the setup from scratch.

---

## 19. Quick command summary

Use this short sequence when restarting:

```bash
wsl.exe
cd /mnt/c/Users/KESHAV/Documents/IOEProject/FallDetection
mkdir -p build
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 --build-path build FallDetection.ino
ls -l build
```

Then in VS Code:

- `Wokwi: Start Simulator`

Then simulate fall by changing MPU6050 values or pressing SOS.

---

## 20. One-line reminder

If the binary exists in `build/` and Wokwi is started from the repo root, the project is in the correct working state for simulation and professor/demo use.
