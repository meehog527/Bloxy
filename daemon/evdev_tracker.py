# evdev_tracker.py

from evdev import InputDevice, categorize, ecodes
from gi.repository import GLib
import select
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hid_daemon")

BTN_MAP = {
    'BTN_LEFT': 0,
    'BTN_RIGHT': 1,
    'BTN_MIDDLE': 2,
}

def to_signed_byte(val):
    return (val + 256) % 256

class EvdevTracker:
    def __init__(self, device_path):
        self.device_path = device_path
        self.device = InputDevice(device_path)
        self.pressed_keys = set()
        self.buttons = set()
        self.rel_x = 0
        self.rel_y = 0

    def poll(self):
        updated = False
        try:
            r, _, _ = select.select([self.device.fd], [], [], 0)
            if self.device.fd in r:
                for event in self.device.read():
                    if event.type == ecodes.EV_KEY:
                        key_event = categorize(event)
                        keycode = key_event.keycode

                        if isinstance(keycode, list):
                            keycode = keycode[0]
                        if key_event.keystate == key_event.key_down:
                            print(event.code)
                            if 271 <= event.code <= 274:
                                self.buttons.add(keycode)
                            else:
                                self.pressed_keys.add(keycode)

                        elif key_event.keystate == key_event.key_up:
                            if str(keycode).startswith('BTN_'):
                                self.buttons.discard(keycode)
                            else:
                                self.pressed_keys.discard(keycode)
                        updated = True

                    elif event.type == ecodes.EV_REL:
                        if event.code == ecodes.REL_X:
                            self.rel_x += event.value
                        elif event.code == ecodes.REL_Y:
                            self.rel_y += event.value
                        updated = True

                    elif event.type == ecodes.EV_SYN:
                        pass
        except Exception as e:
            logger.error("Error reading %s: %s", self.device_path, e)
        return updated


class HIDMouseService:
    def __init__(self, device_path, mouse_char):
        self.tracker = EvdevTracker(device_path)
        self.mouse_char = mouse_char
        GLib.timeout_add(20, self.poll)

    def poll(self):
        if self.tracker.poll():
            buttons, dx, dy = self.consume_report()
            report = [
                0x02,                 # Report ID
                buttons & 0xFF,       # Button bitmask
                to_signed_byte(dx),   # X delta (signed 8-bit)
                to_signed_byte(dy),   # Y delta (signed 8-bit)
            ]
            # Emit PropertiesChanged so notification subscribers get the update
            self.mouse_char.update_value(report)

            if not self.mouse_char.notifying:
                logger.debug("Host not subscribed")
            else:
                logger.debug(f"Mouse char ({self.mouse_char.name}) updated: {report}")

        return True

    def consume_report(self):
        mask = 0
        for btn in self.tracker.buttons:
            if btn in BTN_MAP:
                mask |= (1 << BTN_MAP[btn])

        dx, dy = self.tracker.rel_x, self.tracker.rel_y
        self.tracker.rel_x = 0
        self.tracker.rel_y = 0
        return mask, dx, dy