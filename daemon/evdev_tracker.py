#evdev_tracker.py

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



# Assume you already have a D-Bus object for your HID Report characteristic
# e.g. self.mouse_input_char with a .PropertiesChanged() or .SendNotify() method

class HIDMouseService:
    def __init__(self, device_path, mouse_char):
        self.tracker = EvdevTracker(device_path)
        self.mouse_char = mouse_char  # your GATT characteristic object

        # Run periodic polling
        GLib.timeout_add(20, self.poll)  # every 20ms (~50Hz)

    def poll(self):
        if self.tracker.poll():
            buttons, dx, dy = self.consume_report()

            # HID Input Report for mouse (Report ID 2)
            report = [
                0x02,          # Report ID (must match Report Map)
                buttons & 0xFF,  # Button bitmask
                dx & 0xFF,       # X delta (signed 8-bit)
                dy & 0xFF        # Y delta (signed 8-bit)
            ]

            # Update characteristic value
            self.mouse_char.value = report

            # Notify host if subscribed
            if not self.mouse_char.notifying:
                logger.debug("Host not subscribed")
            else:
                logger.debug("Sent mouse report: %s", report)

        return True  # keep GLib timeout active
    
    def consume_report(self):
        """
        Build a HID-style mouse report and reset deltas.
        Returns (buttons_bitmask, dx, dy).
        """
        # Build button bitmask
        mask = 0
        for btn in self.tracker.buttons:
            if btn in BTN_MAP:
                mask |= (1 << BTN_MAP[btn])

        dx, dy = self.tracker.rel_x, self.tracker.rel_y
        # Reset deltas after consuming
        self.tracker.rel_x = 0
        self.tracker.rel_y = 0

        return mask, dx, dy