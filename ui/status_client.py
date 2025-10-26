import json
import dbus

DAEMON_BUS_NAME = 'org.example.HIDPeripheral'
DAEMON_OBJ_PATH = '/org/example/HIDPeripheral'
DAEMON_IFACE = 'org.example.HIDPeripheral'

class StatusClient:
    """
    D-Bus client to query/control the HID daemon.
    """
    def __init__(self):
        self.bus = dbus.SystemBus()
        self.proxy = self.bus.get_object(DAEMON_BUS_NAME, DAEMON_OBJ_PATH)
        self.iface = dbus.Interface(self.proxy, DAEMON_IFACE)
        self.latest_status = None

        # Subscribe to push updates (optional)
        self.bus.add_signal_receiver(self._on_status_updated,
                                     dbus_interface=DAEMON_IFACE,
                                     signal_name='StatusUpdated')

    def _on_status_updated(self, status_json):
        try:
            self.latest_status = json.loads(status_json)
        except Exception:
            pass

    def get_status(self):
        # Prefer latest push; fallback to direct call
        if self.latest_status is not None:
            return self.latest_status
        raw = self.iface.GetStatus()
        return json.loads(raw)

    def toggle(self):
        self.iface.Toggle()

    def set_notify(self, characteristic_uuid, enable: bool):
        self.iface.SetNotify(characteristic_uuid, bool(enable))
