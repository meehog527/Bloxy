# ================================
# BlueZ Core Constants
# ================================
BLUEZ_SERVICE_NAME = "org.bluez"
ADAPTER_PATH       = "/org/bluez/hci0"

# BlueZ GATT Interfaces
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE    = "org.bluez.GattCharacteristic1"
GATT_DESC_IFACE    = "org.bluez.GattDescriptor1"

# Standard D-Bus Properties Interface
DBUS_PROP_IFACE    = "org.freedesktop.DBus.Properties"


# ================================
# Agent (for pairing/authorization)
# ================================
AGENT_PATH         = "/org/example/hid_agent"


# ================================
# Your Daemon Identity
# ================================
DAEMON_BUS_NAME    = "org.example.HIDPeripheral"   # well-known bus name
DAEMON_IFACE       = "org.example.HIDPeripheral.Control"   # control interface


# ================================
# Application (GATT hierarchy root)
# ================================
HID_APP_PATH       = "/org/example/HIDPeripheral"  # root path BlueZ will introspect
HID_SERVICE_BASE   = f"{HID_APP_PATH}/service"     # base path for services/characteristics


# ================================
# Daemon Control API (separate object)
# ================================
DAEMON_OBJ_PATH    = "/org/example/HIDPeripheral/daemon"