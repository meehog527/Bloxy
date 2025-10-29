import json
import dbus
from dbus.mainloop.glib import DBusGMainLoop

from constants import DAEMON_BUS_NAME, DAEMON_OBJ_PATH, DAEMON_IFACE, HID_APP_PATH

class StatusClient:
    """
    D-Bus client to query/control the HID daemon.
    """

    def __init__(self):
        # Ensure D-Bus connections are attached to a GLib main loop
        DBusGMainLoop(set_as_default=True)

        # Connect to the system bus (or SessionBus if you switched)
        self.bus = dbus.SystemBus()

        # Get proxy object and interface
        self.proxy = self.bus.get_object(DAEMON_BUS_NAME, HID_APP_PATH)
        self.iface = dbus.Interface(self.proxy, DAEMON_IFACE)

        self.latest_status = None

        # Subscribe to push updates (optional)
        try:
            self.bus.add_signal_receiver(
                self._on_status_updated,
                dbus_interface=DAEMON_IFACE,
                signal_name='StatusUpdated'
            )
        except Exception as e:
            # If signals aren’t available, just log or ignore
            print(f"Warning: could not subscribe to StatusUpdated signal: {e}")

    def _on_status_updated(self, status_json):
        try:
            self.latest_status = json.loads(status_json)
        except Exception:
            # Ignore malformed updates
            pass

    def get_status(self):
        # Prefer latest push; fallback to direct call
        if self.latest_status is not None:
            return self.latest_status
        try:
            raw = self.iface.GetStatus()
            return json.loads(raw)
        except Exception as e:
            # Return empty dict if daemon is unavailable
            return {"error": str(e)}

    def toggle(self):
        try:
            self.iface.Toggle()
        except Exception as e:
            raise RuntimeError(f"Toggle failed: {e}")

    def set_notify(self, characteristic_uuid, enable: bool):
        try:
            self.iface.SetNotify(characteristic_uuid, bool(enable))
        except Exception as e:
            raise RuntimeError(f"SetNotify failed: {e}")