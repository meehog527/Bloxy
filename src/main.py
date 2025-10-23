#!/usr/bin/env python3
import asyncio
import logging
import struct
import sys
import time
from typing import Optional
from evdev import InputDevice, ecodes
from bluezero import peripheral, adapter, device, tools

# -------------------------
# Configuration
# -------------------------
# If you know your device paths, set them here.
# Otherwise, the script will auto-detect typical keyboard/mouse devices.
KEYBOARD_EVENT: Optional[str] = None  # e.g., "/dev/input/event0"
MOUSE_EVENT: Optional[str] = None     # e.g., "/dev/input/event1"
LOCAL_NAME = "Pi HID Proxy"

# -------------------------
# Logging setup
# -------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("hid-proxy")

# -------------------------
# HID Report Map: Keyboard (ID=1) + Mouse (ID=2)
# Keyboard: 8-byte input (modifiers, reserved, 6 keys)
# Mouse: 3-byte input (buttons, x, y)
# -------------------------
REPORT_MAP = bytes([
    # Keyboard
    0x05, 0x01,       # Usage Page (Generic Desktop)
    0x09, 0x06,       # Usage (Keyboard)
    0xA1, 0x01,       # Collection (Application)
    0x85, 0x01,       #   Report ID (1)
    0x05, 0x07,       #   Usage Page (Keyboard/Keypad)
    0x19, 0xE0,       #   Usage Minimum (224)
    0x29, 0xE7,       #   Usage Maximum (231)
    0x15, 0x00,       #   Logical Minimum (0)
    0x25, 0x01,       #   Logical Maximum (1)
    0x75, 0x01,       #   Report Size (1)
    0x95, 0x08,       #   Report Count (8)
    0x81, 0x02,       #   Input (Data,Var,Abs) ; Modifier
    0x75, 0x08,       #   Report Size (8)
    0x95, 0x01,       #   Report Count (1)
    0x81, 0x01,       #   Input (Const,Array,Abs) ; Reserved
    0x75, 0x08,       #   Report Size (8)
    0x95, 0x06,       #   Report Count (6)
    0x15, 0x00,       #   Logical Minimum (0)
    0x25, 0x65,       #   Logical Maximum (101)
    0x05, 0x07,       #   Usage Page (Keyboard/Keypad)
    0x19, 0x00,       #   Usage Minimum (0)
    0x29, 0x65,       #   Usage Maximum (101)
    0x81, 0x00,       #   Input (Data,Array,Abs)
    0xC0,             # End Collection
    # Mouse
    0x05, 0x01,       # Usage Page (Generic Desktop)
    0x09, 0x02,       # Usage (Mouse)
    0xA1, 0x01,       # Collection (Application)
    0x85, 0x02,       #   Report ID (2)
    0x09, 0x01,       #   Usage (Pointer)
    0xA1, 0x00,       #   Collection (Physical)
    0x05, 0x09,       #     Usage Page (Buttons)
    0x19, 0x01,       #     Usage Minimum (1)
    0x29, 0x03,       #     Usage Maximum (3)
    0x15, 0x00,       #     Logical Minimum (0)
    0x25, 0x01,       #     Logical Maximum (1)
    0x75, 0x01,       #     Report Size (1)
    0x95, 0x03,       #     Report Count (3)
    0x81, 0x02,       #     Input (Data,Var,Abs)
    0x75, 0x05,       #     Report Size (5)
    0x95, 0x01,       #     Report Count (1)
    0x81, 0x01,       #     Input (Const,Array,Abs) ; padding
    0x05, 0x01,       #     Usage Page (Generic Desktop)
    0x09, 0x30,       #     Usage (X)
    0x09, 0x31,       #     Usage (Y)
    0x15, 0x81,       #     Logical Minimum (-127)
    0x25, 0x7F,       #     Logical Maximum (127)
    0x75, 0x08,       #     Report Size (8)
    0x95, 0x02,       #     Report Count (2)
    0x81, 0x06,       #     Input (Data,Var,Rel)
    0xC0,             #   End Collection
    0xC0              # End Collection
])
# -------------------------
# UUIDs
# -------------------------
UUID_HID_SERVICE       = '00001812-0000-1000-8000-00805f9b34fb'
UUID_HID_INFORMATION   = '00002a4a-0000-1000-8000-00805f9b34fb'
UUID_HID_REPORT_MAP    = '00002a4b-0000-1000-8000-00805f9b34fb'
UUID_HID_CONTROL_POINT = '00002a4c-0000-1000-8000-00805f9b34fb'
UUID_HID_PROTOCOL_MODE = '00002a4e-0000-1000-8000-00805f9b34fb'
UUID_REPORT            = '00002a4d-0000-1000-8000-00805f9b34fb'
# -------------------------
# Bluezero objects
# -------------------------
hid_service = peripheral.Service(UUID_HID_SERVICE, True)
# HID Information: bcdHID=0x0111, bCountryCode=0, flags=0x02 (normally connectable)
hid_information_char = peripheral.Characteristic(
    UUID_HID_INFORMATION,
    ['read'],
    hid_service,
    value=bytes([0x11, 0x01, 0x00, 0x02])
)
# HID Report Map
report_map_char = peripheral.Characteristic(
    UUID_HID_REPORT_MAP,
    ['read'],
    hid_service,
    value=REPORT_MAP
)
# Protocol Mode (Report Mode = 1)
protocol_mode_char = peripheral.Characteristic(
    UUID_HID_PROTOCOL_MODE,
    ['read', 'write-without-response'],
    hid_service,
    value=bytes([0x01])
)
# HID Control Point
control_point_char = peripheral.Characteristic(
    UUID_HID_CONTROL_POINT,
    ['write-without-response'],
    hid_service,
    value=b'\x00'
)
# Report characteristics: Keyboard (ID=1) and Mouse (ID=2)
keyboard_input_char = peripheral.Characteristic(
    UUID_REPORT,
    ['read', 'notify'],
    hid_service,
    value=bytes([0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])  # ID=1 + 8-byte kb
)
mouse_input_char = peripheral.Characteristic(
    UUID_REPORT,
    ['read', 'notify'],
    hid_service,
    value=bytes([0x02, 0x00, 0x00, 0x00])  # ID=2 + 3-byte mouse
)
# Assemble the peripheral
ble_periph = peripheral.Peripheral(
    adapter_addr=None,       # Use default adapter
    local_name=LOCAL_NAME,
    services=[hid_service]
)
# -------------------------
# GATT operation logging
# -------------------------
def log_read_value(uuid: str, current_value: bytes):
    logger.info(f"Characteristic read: uuid={uuid}, value={list(current_value)}")
def log_write_value(uuid: str, new_value: bytes):
    logger.info(f"Characteristic write: uuid={uuid}, value={list(new_value)}")
# Override handlers: Bluezero Characteristic supports read/write handlers via callbacks
# We attach simple wrappers for logging where relevant
def protocol_mode_write_callback(value, options=None):
    log_write_value(UUID_HID_PROTOCOL_MODE, bytes(value))
    # Accept only 0 (Boot) or 1 (Report) — we stick with Report Mode
    if len(value) == 1 and value[0] in (0, 1):
        protocol_mode_char.set_value(bytes([value[0]]))
def control_point_write_callback(value, options=None):
    log_write_value(UUID_HID_CONTROL_POINT, bytes(value))
    # Value 0x00: suspend; 0x01: exit suspend — many hosts send 0x00/0x01
    control_point_char.set_value(bytes(value))
def report_map_read_callback(options=None):
    v = report_map_char.get_value()
    log_read_value(UUID_HID_REPORT_MAP, v)
    return v
def hid_information_read_callback(options=None):
    v = hid_information_char.get_value()
    log_read_value(UUID_HID_INFORMATION, v)
    return v
def protocol_mode_read_callback(options=None):
    v = protocol_mode_char.get_value()
    log_read_value(UUID_HID_PROTOCOL_MODE, v)
    return v
# Attach callbacks
protocol_mode_char.on_write = protocol_mode_write_callback
control_point_char.on_write = control_point_write_callback
report_map_char.on_read = report_map_read_callback
hid_information_char.on_read = hid_information_read_callback
protocol_mode_char.on_read = protocol_mode_read_callback
# -------------------------
# Connection lifecycle logging
# -------------------------
def on_connect(device_addr):
    logger.info(f"Central connected: {device_addr}")
def on_disconnect(device_addr):
    logger.warning(f"Central disconnected: {device_addr}")
ble_periph.on_connect = on_connect
ble_periph.on_disconnect = on_disconnect
# -------------------------
# Pairing, services, MTU, RSSI monitoring
# -------------------------
def monitor_devices():
    """Subscribe to Device1 property changes and log key events."""
    ad = adapter.Adapter()
    for dev_addr in ad.devices:
        dev = device.Device(dev_addr)
        # Log current state
        try:
            logger.debug(f"Monitor start: {dev.Address} Connected={dev.Connected} Paired={dev.Paired} "
                        f"ServicesResolved={dev.ServicesResolved} RSSI={getattr(dev, 'RSSI', 'n/a')} "
                        f"MTU={getattr(dev, 'MTU', 'n/a')}")
        except Exception as e:
            logger.debug(f"Initial device state read failed for {dev_addr}: {e}")
        def prop_changed(iface, changed, invalidated, path=dev.path):
            if 'Connected' in changed:
                logger.info(f"Device {dev.Address} Connected={changed['Connected']}")
            if 'Paired' in changed:
                logger.info(f"Device {dev.Address} Paired={changed['Paired']}")
            if 'ServicesResolved' in changed:
                logger.info(f"Device {dev.Address} ServicesResolved={changed['ServicesResolved']}")
            if 'RSSI' in changed:
                logger.debug(f"Device {dev.Address} RSSI={changed['RSSI']}")
            if 'MTU' in changed:
                logger.info(f"Device {dev.Address} MTU={changed['MTU']}")
        dev.on_properties_changed = prop_changed
# -------------------------
# Advertising lifecycle logging
# -------------------------
def start_advertising():
    logger.info(f"Starting advertising as '{LOCAL_NAME}'")
    ble_periph.publish()
    logger.info("Advertising published")
def stop_advertising():
    try:
        ble_periph.unpublish()
        logger.info("Advertising stopped")
    except Exception as e:
        logger.warning(f"Stopping advertising failed: {e}")
# -------------------------
# Keyboard state and report generation
# -------------------------
pressed_keys = set()
modifier_mask = 0
MODIFIERS = {
    ecodes.KEY_LEFTCTRL: 0x01,
    ecodes.KEY_LEFTSHIFT: 0x02,
    ecodes.KEY_LEFTALT: 0x04,
    ecodes.KEY_LEFTMETA: 0x08,
    ecodes.KEY_RIGHTCTRL: 0x10,
    ecodes.KEY_RIGHTSHIFT: 0x20,
    ecodes.KEY_RIGHTALT: 0x40,
    ecodes.KEY_RIGHTMETA: 0x80,
}
# Minimal Linux keycode -> HID usage mapping for common keys
KEY_TO_HID = {
    ecodes.KEY_A: 0x04, ecodes.KEY_B: 0x05, ecodes.KEY_C: 0x06, ecodes.KEY_D: 0x07,
    ecodes.KEY_E: 0x08, ecodes.KEY_F: 0x09, ecodes.KEY_G: 0x0A, ecodes.KEY_H: 0x0B,
    ecodes.KEY_I: 0x0C, ecodes.KEY_J: 0x0D, ecodes.KEY_K: 0x0E, ecodes.KEY_L: 0x0F,
    ecodes.KEY_M: 0x10, ecodes.KEY_N: 0x11, ecodes.KEY_O: 0x12, ecodes.KEY_P: 0x13,
    ecodes.KEY_Q: 0x14, ecodes.KEY_R: 0x15, ecodes.KEY_S: 0x16, ecodes.KEY_T: 0x17,
    ecodes.KEY_U: 0x18, ecodes.KEY_V: 0x19, ecodes.KEY_W: 0x1A, ecodes.KEY_X: 0x1B,
    ecodes.KEY_Y: 0x1C, ecodes.KEY_Z: 0x1D,
    ecodes.KEY_1: 0x1E, ecodes.KEY_2: 0x1F, ecodes.KEY_3: 0x20, ecodes.KEY_4: 0x21,
    ecodes.KEY_5: 0x22, ecodes.KEY_6: 0x23, ecodes.KEY_7: 0x24, ecodes.KEY_8: 0x25,
    ecodes.KEY_9: 0x26, ecodes.KEY_0: 0x27,
    ecodes.KEY_ENTER: 0x28, ecodes.KEY_ESC: 0x29, ecodes.KEY_BACKSPACE: 0x2A,
    ecodes.KEY_TAB: 0x2B, ecodes.KEY_SPACE: 0x2C,
    ecodes.KEY_MINUS: 0x2D, ecodes.KEY_EQUAL: 0x2E,
    ecodes.KEY_LEFTBRACE: 0x2F, ecodes.KEY_RIGHTBRACE: 0x30,
    ecodes.KEY_BACKSLASH: 0x31, ecodes.KEY_SEMICOLON: 0x33,
    ecodes.KEY_APOSTROPHE: 0x34, ecodes.KEY_GRAVE: 0x35,
    ecodes.KEY_COMMA: 0x36, ecodes.KEY_DOT: 0x37, ecodes.KEY_SLASH: 0x38,
    ecodes.KEY_CAPSLOCK: 0x39,
    ecodes.KEY_RIGHT: 0x4F, ecodes.KEY_LEFT: 0x50, ecodes.KEY_DOWN: 0x51, ecodes.KEY_UP: 0x52,
}
def make_keyboard_report():
    keys = list(pressed_keys)[:6]
    keys += [0x00] * (6 - len(keys))
    report_body = bytes([modifier_mask, 0x00] + keys)
    report = bytes([0x01]) + report_body
    logger.debug(f"Keyboard report: mod=0x{modifier_mask:02X}, keys={keys} -> {list(report)}")
    return report
# -------------------------
# Mouse state and report generation
# -------------------------
mouse_buttons = 0
dx, dy = 0, 0
def make_mouse_report():
    global dx, dy
    # Clamp to -127..127
    cdx = max(-127, min(127, dx))
    cdy = max(-127, min(127, dy))
    report = struct.pack("bbbb", 0x02, mouse_buttons, cdx, cdy)
    logger.debug(f"Mouse report: buttons=0x{mouse_buttons:02X}, dx={cdx}, dy={cdy} -> {list(report)}")
    dx, dy = 0, 0
    return report
# -------------------------
# Notifications
# -------------------------
def send_keyboard_report():
    report = make_keyboard_report()
    keyboard_input_char.set_value(report)
    keyboard_input_char.notify(report)
    logger.info(f"Keyboard HID notify: {list(report)}")
def send_mouse_report():
    report = make_mouse_report()
    mouse_input_char.set_value(report)
    mouse_input_char.notify(report)
    logger.info(f"Mouse HID notify: {list(report)}")
# -------------------------
# Input loops (async)
# -------------------------
async def keyboard_loop(path: str):
    logger.info(f"Opening keyboard device: {path}")
    dev = InputDevice(path)
    async for ev in dev.async_read_loop():
        if ev.type == ecodes.EV_KEY:
            logger.debug(f"Keyboard event: code={ev.code}, value={ev.value}")
            # modifier handling
            if ev.code in MODIFIERS:
                bit = MODIFIERS[ev.code]
                if ev.value == 1:  # press
                    global modifier_mask
                    modifier_mask |= bit
                elif ev.value == 0:  # release
                    modifier_mask &= ~bit
                send_keyboard_report()
                continue
            # normal key handling
            if ev.code in KEY_TO_HID:
                hid_code = KEY_TO_HID[ev.code]
                if ev.value == 1:   # press
                    pressed_keys.add(hid_code)
                elif ev.value == 0: # release
                    if hid_code in pressed_keys:
                        pressed_keys.remove(hid_code)
                send_keyboard_report()
            else:
                logger.debug(f"Unmapped key code: {ev.code}")
async def mouse_loop(path: str):
    global dx, dy, mouse_buttons
    logger.info(f"Opening mouse device: {path}")
    dev = InputDevice(path)
    async for ev in dev.async_read_loop():
        if ev.type == ecodes.EV_KEY:
            logger.debug(f"Mouse button event: code={ev.code}, value={ev.value}")
            if ev.code == ecodes.BTN_LEFT:
                mouse_buttons = (mouse_buttons | 0x01) if ev.value else (mouse_buttons & ~0x01)
            elif ev.code == ecodes.BTN_RIGHT:
                mouse_buttons = (mouse_buttons | 0x02) if ev.value else (mouse_buttons & ~0x02)
            elif ev.code == ecodes.BTN_MIDDLE:
                mouse_buttons = (mouse_buttons | 0x04) if ev.value else (mouse_buttons & ~0x04)
            send_mouse_report()
        elif ev.type == ecodes.EV_REL:
            logger.debug(f"Mouse move event: code={ev.code}, value={ev.value}")
            if ev.code == ecodes.REL_X:
                dx += ev.value
            elif ev.code == ecodes.REL_Y:
                dy += ev.value
            send_mouse_report()
# -------------------------
# Auto-detect input devices if not set
# -------------------------
def autodetect_inputs():
    global KEYBOARD_EVENT, MOUSE_EVENT
    if KEYBOARD_EVENT and MOUSE_EVENT:
        logger.info(f"Using configured input devices: keyboard={KEYBOARD_EVENT}, mouse={MOUSE_EVENT}")
        return
    # Attempt to find keyboard/mouse under /dev/input/by-id
    import os
    base = "/dev/input/by-id"
    if not os.path.isdir(base):
        logger.warning(f"{base} not found. Set KEYBOARD_EVENT/MOUSE_EVENT explicitly.")
        return
    kb = None
    ms = None
    for name in os.listdir(base):
        path = os.path.join(base, name)
        try:
            # Resolve symlinks to /dev/input/eventX
            real = os.path.realpath(path)
        except Exception:
            continue
        lname = name.lower()
        if ("keyboard" in lname or "kbd" in lname) and real.startswith("/dev/input/event"):
            kb = real
        if ("mouse" in lname) and real.startswith("/dev/input/event"):
            ms = real
    if kb:
        KEYBOARD_EVENT = kb
    if ms:
        MOUSE_EVENT = ms
    logger.info(f"Auto-detected keyboard={KEYBOARD_EVENT}, mouse={MOUSE_EVENT}")
# -------------------------
# Main
# -------------------------
def main():
    logger.info("Starting Pi HID Proxy (keyboard + mouse)")
    autodetect_inputs()
    if not KEYBOARD_EVENT or not MOUSE_EVENT:
        logger.error("Keyboard/mouse event devices not set. Plug them in or set KEYBOARD_EVENT/MOUSE_EVENT.")
        sys.exit(1)
    # Monitor Bluetooth device properties (pairing, services, RSSI, MTU)
    try:
        monitor_devices()
    except Exception as e:
        logger.warning(f"Device monitoring init failed: {e}")
    # Advertise peripheral
    start_advertising()
    # Optional: set appearance (keyboard+mouse) using BlueZ mgmt via tools (if available)
    try:
        # Appearance 0x03C4 (962) for Mouse, 0x03C1 (961) for Keyboard; combo devices vary.
        # Not all stacks need this; we log instead of enforcing.
        logger.info("Advertising parameters: local_name='%s' (appearance set via system tools if needed)", LOCAL_NAME)
    except Exception as e:
        logger.debug(f"Appearance setup skipped: {e}")
    # Async loops
    loop = asyncio.get_event_loop()
    loop.create_task(keyboard_loop(KEYBOARD_EVENT))
    loop.create_task(mouse_loop(MOUSE_EVENT))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt — stopping advertising and exiting.")
        stop_advertising()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        stop_advertising()

if __name__ == "__main__":
    main()
