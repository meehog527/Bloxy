#input_handler.py

import struct
from logger import get_logger
from evdev import InputDevice, ecodes
from config import UUID_REPORT

logger = get_logger("InputHandler")

# Modifier and key mappings
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

pressed_keys = set()
modifier_mask = 0
mouse_buttons = 0
dx, dy = 0, 0

def make_keyboard_report():
    global pressed_keys

    keys = list(pressed_keys)[:6] + [0x00] * (6 - len(pressed_keys))
    return bytes([0x01, modifier_mask, 0x00] + keys)

def make_mouse_report():
    global dx, dy
    cdx = max(-127, min(127, dx))
    cdy = max(-127, min(127, dy))
    dx, dy = 0, 0
    return struct.pack("bbbb", 0x02, mouse_buttons, cdx, cdy)

def get_keyboard_characteristic(ble):
    for char in ble.characteristics:
        props = getattr(char, 'props', {})
        uuid = props.get('org.bluez.GattCharacteristic1', {}).get('UUID')
        if uuid == UUID_REPORT:  # UUID_REPORT
            value = props.get('org.bluez.GattCharacteristic1', {}).get('Value', [])
            if value and value[0] == 0x01:  # Report ID 1
                return char
    return None


def get_mouse_characteristic(ble):
    for char in ble.characteristics:
        props = getattr(char, 'props', {})
        uuid = props.get('org.bluez.GattCharacteristic1', {}).get('UUID')
        value = props.get('org.bluez.GattCharacteristic1', {}).get('Value', [])
        if uuid == UUID_REPORT and value and value[0] == 0x02:  # Report ID 2
            return char
    return None


# Async loops
async def keyboard_loop(path, ble):
    global modifier_mask
    global pressed_keys

    try:
        dev = InputDevice(path)
        async for ev in dev.async_read_loop():
            if ev.type == ecodes.EV_KEY:
                keycode = ev.code
                value = ev.value  # 1 = press, 0 = release

                if keycode in MODIFIERS:
                    if value:
                        modifier_mask |= MODIFIERS[keycode]
                    else:
                        modifier_mask &= ~MODIFIERS[keycode]
                elif keycode in KEY_TO_HID:
                    hid_code = KEY_TO_HID[keycode]
                    if value:
                        pressed_keys.add(hid_code)
                    else:
                        pressed_keys.discard(hid_code)

                report = make_keyboard_report()
                logger.debug(f"Keyboard event: code={keycode}, value={value}, report={report}")
                
                keyboard_input_char = get_keyboard_characteristic(ble)
                keyboard_input_char.set_value(report)

    except Exception as e:
        logger.error(f"Keyboard loop error: {e}")

async def mouse_loop(path, ble):
    global dx, dy, mouse_buttons
    try:
        dev = InputDevice(path)
        async for ev in dev.async_read_loop():
            if ev.type == ecodes.EV_REL:
                if ev.code == ecodes.REL_X:
                    dx += ev.value
                elif ev.code == ecodes.REL_Y:
                    dy += ev.value
            elif ev.type == ecodes.EV_KEY:
                if ev.code == ecodes.BTN_LEFT:
                    mouse_buttons = mouse_buttons | 0x01 if ev.value else mouse_buttons & ~0x01
                elif ev.code == ecodes.BTN_RIGHT:
                    mouse_buttons = mouse_buttons | 0x02 if ev.value else mouse_buttons & ~0x02
                elif ev.code == ecodes.BTN_MIDDLE:
                    mouse_buttons = mouse_buttons | 0x04 if ev.value else mouse_buttons & ~0x04

            report = make_mouse_report()
            logger.debug(f"Mouse event: code={ev.code}, value={ev.value}, report={report}")

            # Explicitly set value instead of notify
            mouse_char = get_mouse_characteristic(ble)
            if mouse_char:
                mouse_char.set_value(report)

    except Exception as e:
        logger.error(f"Mouse loop error: {e}")
    global dx, dy, mouse_buttons
    try:
        dev = InputDevice(path)
        async for ev in dev.async_read_loop():
            if ev.type == ecodes.EV_REL:
                if ev.code == ecodes.REL_X:
                    dx += ev.value
                elif ev.code == ecodes.REL_Y:
                    dy += ev.value
            elif ev.type == ecodes.EV_KEY:
                if ev.code == ecodes.BTN_LEFT:
                    mouse_buttons = mouse_buttons | 0x01 if ev.value else mouse_buttons & ~0x01
                elif ev.code == ecodes.BTN_RIGHT:
                    mouse_buttons = mouse_buttons | 0x02 if ev.value else mouse_buttons & ~0x02
                elif ev.code == ecodes.BTN_MIDDLE:
                    mouse_buttons = mouse_buttons | 0x04 if ev.value else mouse_buttons & ~0x04

            report = make_mouse_report()
            logger.debug(f"Mouse event: code={ev.code}, value={ev.value}, report={report}")
            ble.update_characteristic_value(1, 6, report)
            ble.notify(1, 6)
    except Exception as e:
        logger.error(f"Mouse loop error: {e}")