# daemon/evdev_tracker.py
#
# Device event reader and per-device adapters for keyboard and mouse.
# Enhanced to support hot-plugging: trackers will attempt to open the device
# lazily and detect disconnection, allowing the daemon to reconnect while running.
#
# Public classes:
# - EvdevTracker(device_path)
# - KeyboardDevice(tracker)
# - MouseDevice(tracker)

import os
import struct
import select
import logging
from constants import LOG_LEVEL, LOG_FORMAT

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# Evdev constants (subset)
EV_KEY = 0x01
EV_REL = 0x02

REL_X = 0x00
REL_Y = 0x01

BTN_MAP = {
    'BTN_LEFT': 0,
    'BTN_RIGHT': 1,
    'BTN_MIDDLE': 2,
}

# Minimal KEY -> HID usage mapping (subset). Extend as required.
KEYCODE_TO_HID = {
    'KEY_A': 0x04, 'KEY_B': 0x05, 'KEY_C': 0x06, 'KEY_D': 0x07, 'KEY_E': 0x08,
    'KEY_F': 0x09, 'KEY_G': 0x0A, 'KEY_H': 0x0B, 'KEY_I': 0x0C, 'KEY_J': 0x0D,
    'KEY_K': 0x0E, 'KEY_L': 0x0F, 'KEY_M': 0x10, 'KEY_N': 0x11, 'KEY_O': 0x12,
    'KEY_P': 0x13, 'KEY_Q': 0x14, 'KEY_R': 0x15, 'KEY_S': 0x16, 'KEY_T': 0x17,
    'KEY_U': 0x18, 'KEY_V': 0x19, 'KEY_W': 0x1A, 'KEY_X': 0x1B, 'KEY_Y': 0x1C,
    'KEY_Z': 0x1D,
    'KEY_1': 0x1E, 'KEY_2': 0x1F, 'KEY_3': 0x20, 'KEY_4': 0x21, 'KEY_5': 0x22,
    'KEY_6': 0x23, 'KEY_7': 0x24, 'KEY_8': 0x25, 'KEY_9': 0x26, 'KEY_0': 0x27,
    'KEY_ENTER': 0x28, 'KEY_ESC': 0x29, 'KEY_BACKSPACE': 0x2A, 'KEY_TAB': 0x2B, 'KEY_SPACE': 0x2C,
    'KEY_LEFTCTRL': 0xE0, 'KEY_LEFTSHIFT': 0xE1, 'KEY_LEFTALT': 0xE2, 'KEY_LEFTMETA': 0xE3,
    'KEY_RIGHTCTRL': 0xE4, 'KEY_RIGHTSHIFT': 0xE5, 'KEY_RIGHTALT': 0xE6, 'KEY_RIGHTMETA': 0xE7,
}

def to_u8_signed(val):
    """
    Convert integer (signed) to 8-bit unsigned representation for HID.
    Example: -1 -> 0xFF, 1 -> 0x01.
    """
    return val & 0xFF


class EvdevTracker:
    """
    Low-level evdev reader that tolerates device absence and supports hot-plug.

    Behavior summary:
    - Stores the device path (string).
    - Opens the device lazily on poll() when the path exists.
    - If the device is removed while open, errors during read cause the fd to be closed
      and the tracker goes into disconnected state; poll() will attempt to reopen
      on subsequent calls when the device file reappears.
    - Consumers can check .is_connected.
    - Keeps internal state: .buttons (BTN_* names), .key_state (KEY_* names),
      and accumulated .rel_x/.rel_y for relative motion.

    Typical usage:
      tracker = EvdevTracker('/dev/input/event1')
      while running:
          changed = tracker.poll()
          if tracker.is_connected and changed: handle update
    """

    INPUT_EVENT_FORMAT = 'llHHI'
    INPUT_EVENT_SIZE = struct.calcsize(INPUT_EVENT_FORMAT)

    def __init__(self, device_path):
        self.device_path = device_path
        self.fd = None
        self.buttons = set()
        self.key_state = set()
        self.rel_x = 0
        self.rel_y = 0
        self._connected = False
        
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @property
    def is_connected(self):
        """True when the underlying device file is currently open and usable."""
        return self._connected

    def open(self):
        """Attempt to open the device file. Non-blocking read mode."""
        if self.fd:
            return
        try:
            # Ensure the path exists first to avoid noisy errors
            if not os.path.exists(self.device_path):
                self.logger.debug("EvdevTracker.open: path not present %s", self.device_path)
                self._connected = False
                return
            self.fd = os.open(self.device_path, os.O_RDONLY | os.O_NONBLOCK)
            self._connected = True
            self.logger.info("EvdevTracker opened %s (fd=%d)", self.device_path, self.fd)
        except FileNotFoundError:
            self.fd = None
            self._connected = False
            self.logger.debug("EvdevTracker.open: FileNotFound %s", self.device_path)
        except PermissionError:
            self.fd = None
            self._connected = False
            self.logger.exception("EvdevTracker.open: Permission denied for %s", self.device_path)
        except Exception:
            self.fd = None
            self._connected = False
            self.logger.exception("EvdevTracker.open: error opening %s", self.device_path)

    def close(self):
        """Close the device if open; mark as disconnected."""
        if self.fd:
            try:
                os.close(self.fd)
            except Exception:
                self.logger.exception("EvdevTracker.close: error closing fd for %s", self.device_path)
        self.fd = None
        self._connected = False
        self.logger.info("EvdevTracker closed %s", self.device_path)

    def fileno(self):
        """Return file descriptor or -1 if not open."""
        return self.fd if self.fd else -1

    def _read_events(self):
        """
        Read raw bytes and yield parsed (ev_type, code, value) tuples.
        If read returns zero bytes (EOF) or raises an OSError indicating device removal,
        close the fd and mark disconnected.
        """
        if not self.fd:
            return

        try:
            raw = os.read(self.fd, 4096)
        except BlockingIOError:
            return
        except OSError as e:
            # Device probably removed or other IO error; treat as disconnected
            self.logger.warning("EvdevTracker._read_events: read error on %s: %s. Closing.", self.device_path, e)
            self.close()
            return
        except Exception:
            self.logger.exception("EvdevTracker._read_events: unexpected error while reading %s", self.device_path)
            self.close()
            return

        if not raw:
            # 0 bytes read can indicate EOF/device gone — close and mark disconnected
            self.logger.debug("EvdevTracker._read_events: zero bytes read, closing %s", self.device_path)
            self.close()
            return

        offset = 0
        length = len(raw)
        while offset + self.INPUT_EVENT_SIZE <= length:
            chunk = raw[offset:offset + self.INPUT_EVENT_SIZE]
            sec, usec, ev_type, code, value = struct.unpack(self.INPUT_EVENT_FORMAT, chunk)
            offset += self.INPUT_EVENT_SIZE
            yield ev_type, code, value

def poll(self):
    """
    Poll for pending events, attempting to open the device if it is not connected.

    Returns:
    - True if relevant internal state changed (buttons, keys, rel_x/rel_y)
    - False otherwise
    """
    changed = False
    events_seen = False

    self.logger.debug("poll: enter connected=%s fd=%s path=%s", self._connected, self.fileno(), self.device_path)

    # Ensure open if possible
    if not self._connected:
        self.logger.debug("poll: not connected, attempting open()")
        self.open()
        self.logger.debug("poll: after open connected=%s fd=%s", self._connected, self.fileno())
        # If we just opened, no prior data to consume — return False to indicate no change
        if not self._connected:
            self.logger.debug("poll: still not connected after open(), returning False")
            return False

    # Use select to avoid blocking read
    fdnum = self.fileno()
    if fdnum < 0:
        self.logger.debug("poll: fileno invalid (%s), returning False", fdnum)
        return False

    try:
        r, _, _ = select.select([fdnum], [], [], 0)
        self.logger.debug("poll: select returned r=%s", r)
    except Exception as e:
        self.logger.exception("poll: select.select raised exception: %s", e)
        r = []
    if not r:
        self.logger.debug("poll: no data ready on fd, returning False")
        return False

    for ev in self._read_events() or []:
        try:
            ev_type, code, value = ev
        except Exception as e:
            self.logger.exception("poll: malformed event %r, skipping: %s", ev, e)
            continue

        self.logger.debug("poll: raw event ev_type=%s code=%s value=%s", ev_type, code, value)

        if ev_type == EV_REL:
            if code == REL_X:
                if value:
                    old_rel = self.rel_x
                    self.rel_x += int(value)
                    changed = True
                    events_seen = True
                    self.logger.debug("poll: REL_X value=%s rel_x %s->%s", value, old_rel, self.rel_x)
            elif code == REL_Y:
                if value:
                    old_rel = self.rel_y
                    self.rel_y += int(value)
                    changed = True
                    events_seen = True
                    self.logger.debug("poll: REL_Y value=%s rel_y %s->%s", value, old_rel, self.rel_y)
            else:
                self.logger.debug("poll: EV_REL unknown code=%s value=%s", code, value)

        elif ev_type == EV_KEY:
            name = self._code_to_name(code)
            self.logger.debug("poll: EV_KEY code=%s -> name=%s value=%s", code, name, value)
            if not name:
                self.logger.debug("poll: unknown key code %s, skipping", code)
                continue

            # Non-zero value indicates press or autorepeat (value==1 initial, 2 repeat on many systems)
            if value:
                events_seen = True
                if name.startswith('BTN_'):
                    if name not in self.buttons:
                        self.buttons.add(name)
                        changed = True
                        self.logger.debug("poll: button pressed new=%s buttons=%s", name, list(self.buttons))
                    else:
                        # Log repeated button press
                        self.logger.debug("poll: button press repeat=%s (already in set)", name)
                        # consider repeat as event but not necessarily a state-change
                else:
                    if name not in self.key_state:
                        self.key_state.add(name)
                        changed = True
                        self.logger.debug("poll: key pressed new=%s key_state=%s", name, list(self.key_state))
                    else:
                        # Autorepeat / repeated keydown — log and treat as an event
                        self.logger.debug("poll: key press repeat=%s (already in key_state)", name)
            else:
                # value == 0 indicates release
                if name.startswith('BTN_'):
                    if name in self.buttons:
                        self.buttons.discard(name)
                        changed = True
                        events_seen = True
                        self.logger.debug("poll: button released=%s buttons=%s", name, list(self.buttons))
                    else:
                        self.logger.debug("poll: button release for absent button=%s", name)
                else:
                    if name in self.key_state:
                        self.key_state.discard(name)
                        changed = True
                        events_seen = True
                        self.logger.debug("poll: key released=%s key_state=%s", name, list(self.key_state))
                    else:
                        self.logger.debug("poll: key release for absent key=%s", name)
        else:
            self.logger.debug("poll: unhandled ev_type=%s code=%s value=%s", ev_type, code, value)

    self.logger.debug(
        "EvdevTracker.poll exit changed=%s events_seen=%s key_state=%s buttons=%s rel=(%s,%s)",
        changed, events_seen, list(self.key_state), list(self.buttons), self.rel_x, self.rel_y
    )

    return changed or events_seen
    def _code_to_name(self, code):
        """
        Minimal numeric code -> symbolic name mapping for common keys/buttons.
        If your system uses different codes, extend or replace this mapping with python-evdev.
        """
        CODE_TO_NAME = {
            272: 'BTN_LEFT', 273: 'BTN_RIGHT', 274: 'BTN_MIDDLE',
            30: 'KEY_A', 48: 'KEY_B', 46: 'KEY_C', 32: 'KEY_D', 18: 'KEY_E',
            33: 'KEY_F', 34: 'KEY_G', 35: 'KEY_H', 23: 'KEY_I', 36: 'KEY_J',
            37: 'KEY_K', 38: 'KEY_L', 50: 'KEY_M', 49: 'KEY_N', 24: 'KEY_O',
            25: 'KEY_P', 16: 'KEY_Q', 19: 'KEY_R', 31: 'KEY_S', 20: 'KEY_T',
            22: 'KEY_U', 47: 'KEY_V', 17: 'KEY_W', 45: 'KEY_X', 21: 'KEY_Y',
            44: 'KEY_Z',
            2: 'KEY_1', 3: 'KEY_2', 4: 'KEY_3', 5: 'KEY_4', 6: 'KEY_5',
            7: 'KEY_6', 8: 'KEY_7', 9: 'KEY_8', 10: 'KEY_9', 11: 'KEY_0',
            28: 'KEY_ENTER', 1: 'KEY_ESC', 14: 'KEY_BACKSPACE', 15: 'KEY_TAB', 57: 'KEY_SPACE',
            29: 'KEY_LEFTCTRL', 42: 'KEY_LEFTSHIFT', 56: 'KEY_LEFTALT', 125: 'KEY_LEFTMETA',
            97: 'KEY_RIGHTCTRL', 54: 'KEY_RIGHTSHIFT', 100: 'KEY_RIGHTALT', 126: 'KEY_RIGHTMETA',
        }
        return CODE_TO_NAME.get(code)
        

class KeyboardDevice:
    """
    High-level keyboard adapter built on an EvdevTracker.

    - Responsible for building HID keyboard reports
    - Works even if the underlying tracker is disconnected; poll() will return (False, None)
      until key_state changes after reconnection.
    """

    REPORT_ID = 0x01
    MAX_KEYS = 6

    def __init__(self, tracker: EvdevTracker):
        self.tracker = tracker
        self._last_keyset = frozenset()
        self._last_mods = 0
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _build_report(self):
        modifier_bits = 0
        keycodes = []

        for key in sorted(self.tracker.key_state):
            if key in ('KEY_LEFTCTRL', 'KEY_RIGHTCTRL'):
                modifier_bits |= 0x01
            if key in ('KEY_LEFTSHIFT', 'KEY_RIGHTSHIFT'):
                modifier_bits |= 0x02
            if key in ('KEY_LEFTALT', 'KEY_RIGHTALT'):
                modifier_bits |= 0x04
            if key in ('KEY_LEFTMETA', 'KEY_RIGHTMETA'):
                modifier_bits |= 0x08

        for key in sorted(self.tracker.key_state):
            if key.startswith('KEY_') and key not in ('KEY_LEFTCTRL', 'KEY_RIGHTCTRL',
                                                     'KEY_LEFTSHIFT', 'KEY_RIGHTSHIFT',
                                                     'KEY_LEFTALT', 'KEY_RIGHTALT',
                                                     'KEY_LEFTMETA', 'KEY_RIGHTMETA'):
                hid = KEYCODE_TO_HID.get(key)
                if hid:
                    keycodes.append(hid)
                if len(keycodes) >= self.MAX_KEYS:
                    break

        while len(keycodes) < self.MAX_KEYS:
            keycodes.append(0x00)

        report = bytes([self.REPORT_ID, modifier_bits, 0x00] + keycodes)
        return report, modifier_bits

    def poll(self):
        """
        Poll underlying tracker and return (updated, report_bytes).

        - If tracker not connected: returns (False, None)
        - If connected and state changed compared to last emitted: returns (True, bytes)
        - Otherwise (no change): (False, None)
        """

        if not self.tracker or not self.tracker.is_connected:       
            return False, None

        changed = self.tracker.poll()
        print(changed)
        if not changed:
            # No new events; still check if keyset differs (edge case)
            current_keyset = frozenset(self.tracker.key_state)
            if current_keyset == self._last_keyset:
                return False, None

        report, modifier_bits = self._build_report()
        keyset = frozenset(self.tracker.key_state)
        if keyset != self._last_keyset or modifier_bits != self._last_mods:
            self._last_keyset = keyset
            self._last_mods = modifier_bits
            self.logger.debug("KeyboardDevice: emitting report mods=%02x keys=%s", modifier_bits, list(report[3:]))
            return True, report
        return False, None


class MouseDevice:
    """
    High-level mouse adapter built on an EvdevTracker.

    - Converts tracker.buttons and rel_x/rel_y into HID mouse reports.
    - Handles tracker disconnects gracefully (no exceptions).
    - Consumes rel deltas when building a report to avoid duplicate bursts.
    """

    REPORT_ID = 0x02

    def __init__(self, tracker: EvdevTracker):
        self.tracker = tracker
        self._last_mask = 0
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _consume_motion(self):
        dx = int(self.tracker.rel_x)
        dy = int(self.tracker.rel_y)
        self.tracker.rel_x = 0
        self.tracker.rel_y = 0
        return dx, dy

    def _build_button_mask(self):
        mask = 0
        for btn in self.tracker.buttons:
            if btn in BTN_MAP:
                mask |= (1 << BTN_MAP[btn])
        return mask

    def poll(self):
        """
        Poll the underlying tracker and return (updated, report_bytes).

        If the tracker is not connected, returns (False, None) and is idle.
        If button mask changed or motion is non-zero, builds a 4-byte mouse report:
        [REPORT_ID, buttons, dx (u8), dy (u8)]
        """
        if not self.tracker or not self.tracker.is_connected:
            return False, None

        changed = self.tracker.poll()
        # Even if changed==False, there may be leftover rel_x/rel_y from earlier events;
        # but our tracker consumes deltas only on build, so only proceed when changed OR deltas present.
        dx = dy = 0
        # Check if there are pending deltas without relying solely on 'changed'
        if self.tracker.rel_x or self.tracker.rel_y:
            # don't rely on 'changed' for movement-only
            mask = self._build_button_mask()
            dx, dy = self._consume_motion()
        elif changed:
            mask = self._build_button_mask()
            dx, dy = self._consume_motion()
        else:
            return False, None

        # Clamp dx/dy to signed 8-bit
        if dx < -127:
            dx = -127
        if dx > 127:
            dx = 127
        if dy < -127:
            dy = -127
        if dy > 127:
            dy = 127

        # If no mask change and no movement, nothing to send
        if mask == self._last_mask and dx == 0 and dy == 0:
            return False, None

        self._last_mask = mask
        ux = to_u8_signed(dx)
        uy = to_u8_signed(dy)
        report = bytes([self.REPORT_ID, mask & 0xFF, ux, uy])
        self.logger.debug("MouseDevice: emitting report mask=%02x dx=%d dy=%d -> %s", mask, dx, dy, report)
        return True, report
