#dbus_utils.py

import dbus

BLUEZ_SERVICE_NAME = 'org.bluez'
ADAPTER_PATH = '/org/bluez/hci0'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
GATT_DESC_IFACE = 'org.bluez.GattDescriptor1'

DAEMON_BUS_NAME = 'org.example.HIDPeripheral'
DAEMON_OBJ_PATH = '/org/example/HIDPeripheral'
DAEMON_IFACE = 'org.example.HIDPeripheral'

def get_gatt_manager(bus):
    return dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, ADAPTER_PATH), GATT_MANAGER_IFACE)

def register_app(bus, app_path):
    mgr = get_gatt_manager(bus)
    def ok(): print("GATT application registered")
    def err(e): print(f"Failed to register application: {e}")
    mgr.RegisterApplication(app_path, {}, reply_handler=ok, error_handler=err)
