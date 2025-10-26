from evdev import InputDevice, categorize, ecodes
import select

class EvdevTracker:
    def __init__(self, device_path):
        self.device_path = device_path
        self.device = InputDevice(device_path)
        self.pressed_keys = set()
        self.buttons = set()
        self.rel_x = 0
        self.rel_y = 0

    def poll(self):
        r, _, _ = select.select([self.device.fd], [], [], 0)
        if self.device.fd in r:
            for event in self.device.read():
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    keycode = key_event.keycode
                    if isinstance(keycode, list):
                        # Some keys yield lists (e.g., KEY_MINUS => ['KEY_MINUS'])
                        keycode = keycode[0]
                    if key_event.keystate == key_event.key_down:
                        # Distinguish mouse buttons vs keyboard keys
                        if keycode.startswith('BTN_'):
                            self.buttons.add(keycode)
                        else:
                            self.pressed_keys.add(keycode)
                    elif key_event.keystate == key_event.key_up:
                        if keycode.startswith('BTN_'):
                            self.buttons.discard(keycode)
                        else:
                            self.pressed_keys.discard(keycode)
                elif event.type == ecodes.EV_REL:
                    if event.code == ecodes.REL_X:
                        self.rel_x += event.value
                    elif event.code == ecodes.REL_Y:
                        self.rel_y += event.value
