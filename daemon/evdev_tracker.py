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
        self.code = -1
        
        self.MOUSE_BTN = [
            ecodes.BTN_LEFT,
            ecodes.BTN_RIGHT,
            ecodes.BTN_MIDDLE
            ]

    def poll(self):
        updated = False
        try:
            r, _, _ = select.select([self.device.fd], [], [], 0)
            if self.device.fd in r:
                for event in self.device.read():
                    if event.type == ecodes.EV_KEY:
                        key_event = categorize(event)
                        keycode = key_event.keycode

                        if key_event.keystate == key_event.key_down:
                            if event.code in self.MOUSE_BTN:
                                self.buttons.add(keycode)
                                self.code = event.code
                            else:
                                self.pressed_keys.add(keycode)

                        elif key_event.keystate == key_event.key_up:
                            if event.code in self.MOUSE_BTN:
                                self.buttons.discard(keycode)
                                self.code = -1
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
                        print(event)
                        pass
        except Exception as e:
            logger.error("Error reading %s: %s", self.device_path, e)
        return updated
