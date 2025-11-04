# evdev_tracker.py

from evdev import InputDevice, categorize, ecodes
from gi.repository import GLib, GObject
import select
import logging
from constants import LOG_LEVEL, LOG_FORMAT
import fcntl
import os


logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

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
        self.scroll_v = 0  # vertical scroll
        self.code = -1
        self.flush = False
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # ensure non-blocking at OS level
        try:
            fd = self.device.fd
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        except Exception:
            pass

        
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
                # ensure accumulators exist
                if not hasattr(self, 'rel_x'):
                    self.rel_x = 0
                if not hasattr(self, 'rel_y'):
                    self.rel_y = 0
                if not hasattr(self, 'rel_wheel'):
                    self.rel_wheel = 0
                # ensure last_pos exists so we can produce absolute outputs
                if not hasattr(self, '_last_pos') or self._last_pos is None:
                    # (x, y, wheel_cumulative)
                    self._last_pos = (0, 0, 0)

                for event in self.device.read():
                    self.flush = False

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
                        if event.value != 0:
                            if event.code == ecodes.REL_X:
                                self.rel_x += event.value
                            elif event.code == ecodes.REL_Y:
                                self.rel_y += event.value
                            elif event.code == ecodes.REL_WHEEL or event.code == ecodes.REL_HWHEEL:
                                self.rel_wheel += event.value
                            updated = True

                    elif event.type == ecodes.EV_SYN:
                        # Commit accumulated relative deltas into absolute last_pos so
                        # external callers that expect absolute positions keep working.
                        lx, ly, lw = self._last_pos
                        lx_new = lx + getattr(self, 'rel_x', 0)
                        ly_new = ly + getattr(self, 'rel_y', 0)
                        lw_new = lw + getattr(self, 'rel_wheel', 0)
                        self._last_pos = (int(lx_new), int(ly_new), int(lw_new))

                        # Export fields for report building: rel_* still hold deltas;
                        # callers can use self._last_pos to read absolute position if needed.
                        self.rel_x_report = getattr(self, 'rel_x', 0)
                        self.rel_y_report = getattr(self, 'rel_y', 0)
                        self.scroll_v = getattr(self, 'rel_wheel', 0)

                        # clear accumulators for next frame
                        self.rel_x = 0
                        self.rel_y = 0
                        self.rel_wheel = 0

                        self.flush = True
                        updated = True

        except Exception as e:
            logger.error("Error reading %s: %s", self.device_path, e)
        return updated



from gi.repository import GObject, GLib

class AdapterEvdevWatcher(GObject.GObject):
    __gsignals__ = {
        'changed': (GObject.SIGNAL_RUN_LAST, None, (object,)),
        'error': (GObject.SIGNAL_RUN_LAST, None, (str,)),
    }

    def __init__(self, tracker):
        super().__init__()
        self.tracker = tracker
        self._watch_id = None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def start(self):
        if self._watch_id is not None:
            return
        fd = getattr(self.tracker, 'device', None)
        if fd is None or getattr(self.tracker.device, 'fd', None) is None:
            raise RuntimeError("tracker has no device.fd")
        fd = self.tracker.device.fd
        cond = GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP
        self._watch_id = GLib.io_add_watch(fd, cond, self._on_io)
        self.logger.debug(f"Watching device: {self.tracker.device_path}")

    def stop(self):
        if self._watch_id is not None:
            GLib.source_remove(self._watch_id)
            self._watch_id = None

    def _on_io(self, source, condition):
        if condition & (GLib.IO_ERR | GLib.IO_HUP):
            msg = f"Device fd {source} error/closed"
            self.emit('error', msg)
            self.stop()
            try:
                if hasattr(self.tracker.device, 'close'):
                    self.tracker.device.close()
            except Exception:
                logger.exception("Error closing device")
            return False

        try:
            updated = self.tracker.poll()
            if updated:
                payload = {
                    'pressed_keys': getattr(self.tracker, 'pressed_keys', set()).copy(),
                    'buttons': getattr(self.tracker, 'buttons', set()).copy(),
                    'rel_x': getattr(self.tracker, 'rel_x', 0),
                    'rel_y': getattr(self.tracker, 'rel_y', 0),
                    'scroll_v': getattr(self.tracker, 'scroll_v', 0),
                    'last_code': getattr(self.tracker, 'code', -1),
                    'flush': getattr(self.tracker, 'flush', False),
                }
                self.emit('changed', payload)
        except Exception as e:
            logger.exception("Error in AdapterEvdevWatcher._on_io: %s", e)
            self.emit('error', str(e))
            self.stop()
            return False

        return True
    
