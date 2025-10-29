# constants.py

# BlueZ well-known service and adapter
BLUEZ_SERVICE_NAME = "org.bluez"
ADAPTER_PATH       = "/org/bluez/hci0"

# BlueZ GATT interfaces
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE    = "org.bluez.GattCharacteristic1"
GATT_DESC_IFACE    = "org.bluez.GattDescriptor1"

# Standard D-Bus properties interface
DBUS_PROP_IFACE    = "org.freedesktop.DBus.Properties"

# Your agent
AGENT_PATH         = "/org/example/hid_agent"

# Your daemon’s own bus name, object path, and interface
DAEMON_BUS_NAME    = "org.example.HIDPeripheral"
DAEMON_IFACE       = "org.example.HIDPeripheral"
# Daemon control object path (separate from app root!)
DAEMON_OBJ_PATH    = "/org/example/HIDPeripheral/daemon"



# Application root path for your HID GATT application
HID_APP_PATH       = "/org/example/HIDPeripheral"

# Base path for services under your app
HID_SERVICE_BASE   = f"{HID_APP_PATH}/service"