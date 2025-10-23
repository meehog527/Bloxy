# Bloxy

**Bloxy** is a Bluetooth HID proxy that turns a Raspberry Pi into a wireless keyboard and mouse bridge. It listens to input events from USB-connected devices (keyboard and mouse), then translates and forwards those events over Bluetooth to a paired central device (e.g., laptop, tablet, or phone).

---

## 🧠 Features

- Bluetooth Low Energy (BLE) HID peripheral using `bluezero`
- USB input event handling via `evdev`
- HID-compliant report generation for keyboard and mouse
- Real-time BLE notifications to connected central device
- Auto-detection of input devices
- Connection lifecycle logging and monitoring (RSSI, MTU, pairing)
- Modular design with separate handlers for keyboard, mouse, and HID setup

---

## 🛠 Requirements

- Raspberry Pi with Bluetooth support
- Python 3.7+
- Required Python packages:
  - `evdev`
  - `bluezero`
  - `asyncio`
  - `struct`
  - `logging`

---

## 📦 Installation

```bash
git clone https://github.com/meehog527/Bloxy.git
cd Bloxy
python3 -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
