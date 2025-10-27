from evdev import InputDevice, categorize, ecodes
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
    # add more if needed
}

class EvdevTracker:
    """
    Tracks a single evdev input device. Accumulates pressed keys/buttons and relative movement.
    """

    def __init__(self, device_path):
        self.device_path = device_path
        self.device = InputDevice(device_path)
        self.pressed_keys = set()
        self.buttons = set()
        self.rel_x = 0
        self.rel_y = 0

    def poll(self):
        """
        Non-blocking poll to read events and update internal state.
        Returns True if any new events were processed.
        """
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
                            if str(keycode).startswith('BTN_'):
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
                        # End of batch
                        pass
        except Exception as e:
            logger.error("Error reading %s: %s", self.device_path, e)
        return updated

    def consume_report(self):
        """
        Build a HID-style mouse report and reset deltas.
        Returns (buttons_bitmask, dx, dy).
        """
        # Build button bitmask
        mask = 0
        for btn in self.buttons:
            if btn in BTN_MAP:
                mask |= (1 << BTN_MAP[btn])

        dx, dy = self.rel_x, self.rel_y
        # Reset deltas after consuming
        self.rel_x = 0
        self.rel_y = 0

        return mask, dx, dy