import dbus
import dbus.mainloop.glib
from gi.repository import GLib

BLUEZ_SERVICE_NAME = 'org.bluez'
ADAPTER_PATH = '/org/bluez/hci0'
ADAPTER_IFACE = 'org.bluez.Adapter1'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_PROPS_IFACE = 'org.freedesktop.DBus.Properties'


class BLEPeripheral:
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, ADAPTER_PATH)
        self.adapter_props = dbus.Interface(self.adapter, DBUS_PROPS_IFACE)

    def setup_adapter(self):
        self.adapter_props.Set(ADAPTER_IFACE, 'Powered', dbus.Boolean(1))
        self.adapter_props.Set(ADAPTER_IFACE, 'Discoverable', dbus.Boolean(1))
        print("✅ Adapter powered and discoverable")

    def run(self):
        self.setup_adapter()
        print("🚀 BLE Peripheral is running. Waiting for connections...")
        GLib.MainLoop().run()

if __name__ == '__main__':
    peripheral = BLEPeripheral()
    peripheral.run()