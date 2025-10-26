Here’s the raw Markdown text of the full README we built together — you can copy‑paste this directly into a README.md file in your GitHub repo:

---

Bloxy HID Peripheral

This project implements a Bluetooth HID peripheral (keyboard + mouse) using BlueZ and D‑Bus on Linux.
It is split into two main components:

• Daemon (daemon/): Runs headless, registers the HID GATT service with BlueZ, tracks evdev input, builds HID reports, and exposes a custom D‑Bus API.
• UI Client (ui/): A curses‑based console interface that connects to the daemon over D‑Bus. It lets you inspect services, characteristics, descriptors, and toggle features in real time.


---

🚀 Getting Started

Requirements

• Linux with BlueZ and D‑Bus
• Python 3.9+
• Root/sudo access (for BLE + evdev input devices)


Installation

sudo apt update
sudo apt install -y bluetooth bluez python3-dbus python3-gi python3-evdev python3-yaml python3-venv


Clone the repository:

git clone https://github.com/meehog527/Bloxy.git
cd Bloxy


Create a virtual environment and install dependencies:

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt


Configuration

• Edit peripheral.yaml to define your GATT services/characteristics.
• Edit report_map.yaml to map evdev key codes to HID usage IDs.
• Update /etc/bluetooth/main.conf similar to bluez/main.conf.


Running the Daemon

Foreground run:

sudo -E env PYTHONPATH=. python3 daemon/hid_daemon.py


As a systemd service:

sudo cp systemd/hid-peripheral.service /etc/systemd/system/
sudo cp systemd/env /etc/default/hid-peripheral
sudo systemctl daemon-reload
sudo systemctl enable --now hid-peripheral


Running the UI

SSH into the device and run:

python3 ui/console_ui.py


The curses UI will show live HID state, let you toggle the peripheral, and drill into services/characteristics.

---

🧩 Architecture Overview

Module Responsibilities

• daemon/hid_daemon.py
Entry point. Loads configs, builds services, polls evdev, updates HID reports, and exposes the custom D‑Bus API.
• daemon/ble_peripheral.py
Implements BlueZ GATT objects (HIDService, HIDCharacteristic, HIDDescriptor).
• daemon/hid_reports.py
Builds HID keyboard/mouse reports from evdev events using report_map.yaml.
• daemon/evdev_tracker.py
Tracks pressed keys, mouse buttons, and relative movement from /dev/input/eventX.
• daemon/dbus_utils.py
Constants and helpers for BlueZ D‑Bus registration.
• ui/status_client.py
Connects to the daemon’s D‑Bus API, fetches status JSON, sends control commands.
• ui/console_ui.py
Curses‑based dashboard. Navigates services/characteristics, shows live values, toggles notifications.


---

🔄 Data Flow

1. Input: evdev devices → evdev_tracker.py → pressed keys/buttons.
2. Report Building: hid_reports.py → HID reports.
3. Peripheral: ble_peripheral.py → updates GATT characteristics.
4. Daemon: hid_daemon.py → orchestrates, exposes D‑Bus API.
5. BlueZ: sends notifications to connected Bluetooth host.
6. UI: console_ui.py connects via status_client.py to daemon’s D‑Bus API for inspection and control.


---

## 📊 Architecture Diagram

```mermaid
flowchart TD
    subgraph Kernel["Linux Kernel"]
        EVDEV["/dev/input/eventX"]
    end

    subgraph Daemon["Daemon (daemon/)"]
        ET["evdev_tracker.py"]
        HR["hid_reports.py"]
        BP["ble_peripheral.py"]
        HD["hid_daemon.py"]
        DU["dbus_utils.py"]
    end

    subgraph BlueZ["BlueZ (system)"]
        GM["GattManager1"]
        GS["GattService1 / GattCharacteristic1"]
    end

    subgraph UI["UI Client (ui/)"]
        SC["status_client.py"]
        CU["console_ui.py"]
    end

    EVDEV --> ET --> HR --> BP --> HD
    HD -->|register_app| GM
    BP --> GS
    HD -->|exposes| DU
    HD -->|D-Bus API| SC --> CU
    GS -->|notifications| Host["Bluetooth Host (PC/Phone)"]


---

🖥️ Typical Workflow

• Daemon runs headless as a systemd service.
• You SSH into the Pi and run ui/console_ui.py.
• The UI shows live HID state (e.g., pressing A updates the keyboard report value).
• You can drill into services/characteristics, toggle notifications, or stop/start the peripheral.


---

That’s the raw Markdown text — ready to paste into GitHub as README.md. Would you like me to also append a “Updating the Project” section that documents the update script (full vs partial update) so it’s all in one place?