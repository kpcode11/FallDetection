# IoE-Based Fall Detection System for Elderly Care

This repository contains the prototype firmware and simulation environment for an Internet-of-Everything (IoE) wearable fall detection system. The project uses an ESP32 microcontroller, an MPU6050 accelerometer/gyroscope, and a cloud MQTT broker to instantly alert caregivers in the event of a fall.

It is fully configured to run inside **Visual Studio Code** using the **Wokwi Simulator**.

---

## 🛠 Features & Algorithm

The system employs a classic **two-stage wearable fall-detection approach**:

1. **Free Fall Detection:** The system continuously monitors the total acceleration magnitude. If it drops below `~0.4 g`, a free fall is registered.
2. **Impact Detection:** If an impact spike (`> 2.2 g`) is detected within 1 second of the free fall, the system flags a potential fall.

**Grace Period & SOS Override:**
Upon detecting a fall, the device enters an 8-second grace period. The buzzer sounds and the red LED flashes. 
- If the wearer is okay, they can press the physical **SOS Button** to cancel the false alarm.
- If they do not respond within 8 seconds, the system confirms the fall and publishes a live MQTT alert to a cloud dashboard. 
- The **SOS Button** also acts as a manual panic button that can instantly trigger an alert at any time.

---

## 💻 Hardware Components (Simulated)
- **ESP32 Dev Kit v1** (Core Processor & WiFi)
- **MPU6050** (Accelerometer + Gyroscope via I2C: SDA=21, SCL=22)
- **Buzzer** (Audio feedback on GPIO25)
- **Pushbutton (Red)** (Manual SOS / Cancel alarm on GPIO4)
- **Red LED** (Fall alert indicator on GPIO27)
- **Green LED** (System health & WiFi indicator on GPIO26)

---

## ⚙️ Prerequisites & Setup

To run this simulation on your PC, you need to set up the VS Code Arduino environment.

### 1. Install Required Software
1. Download and install [Visual Studio Code](https://code.visualstudio.com/).
2. In VS Code, install the following extensions:
   - **Arduino** (by Microsoft)
   - **Wokwi Simulator** (by Wokwi)

### 2. Install Arduino Libraries
The project requires three specific libraries to compile.
1. Open the VS Code Command Palette (`Ctrl+Shift+P`).
2. Search for and open **`Arduino: Library Manager`**.
3. Install the following libraries:
   - **`Adafruit MPU6050`** *(Note: If prompted, click "Install All" to also install its dependencies like `Adafruit Unified Sensor` and `Adafruit BusIO`)*
   - **`PubSubClient`** (by Nick O'Leary)

---

## 🚀 Running the Simulation

This workspace is already pre-configured with `.vscode/arduino.json` and `wokwi.toml` to ensure the binaries compile to the correct `/build` folder.

### Step 1: Compile the Firmware
1. Open the `FallDetection.ino` file in your editor.
2. Click the **Verify** button (the `✓` icon in the top right corner of the editor) OR press `Ctrl+Alt+R`.
3. Wait for the terminal to display `"Done compiling."` 
   *(You will notice a `build/` folder appears in your workspace containing `FallDetection.ino.bin`).*

### Step 2: Start Wokwi
1. Open the Command Palette (`Ctrl+Shift+P`).
2. Select **`Wokwi: Start Simulator`**.
   *(If this is your first time using Wokwi in VS Code, you may be prompted to select `Wokwi: Request License` first to activate your free license).*

### Step 3: Test the System
- **View Output:** The Serial Monitor will open at the bottom. You will see the ESP32 connect to the Wokwi-GUEST WiFi and connect to the public MQTT broker (`broker.hivemq.com`).
- **Simulate a Fall:** Click on the MPU6050 module in the simulation window. A popup will appear with X/Y/Z acceleration sliders. Rapidly drag a slider to simulate a drop (Free Fall) and a sudden stop (Impact).
- **Trigger SOS:** Click the red pushbutton to manually trigger an MQTT alert.

---

## 🔧 Troubleshooting

- **`Wokwi: firmware binary build/FallDetection.ino.bin not found`**
  This happens if you haven't compiled the code yet. Make sure you open `FallDetection.ino` and click **Verify** first.

- **`fatal error: Adafruit_MPU6050.h: No such file or directory`**
  You forgot to install the libraries! See the **Install Arduino Libraries** section above.

- **Wrong Board Selected Error**
  This workspace is hardcoded to use the `DOIT ESP32 DEVKIT V1` board. If the Arduino extension complains about FQBN mismatch, open the Command Palette, select `Arduino: Board Config`, and choose `DOIT ESP32 DEVKIT V1`.
