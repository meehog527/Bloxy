import logging

# ================================
# Logging
# ================================
LOG_LEVEL = logging.DEBUG
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s(%(funcName)s): %(message)s"

# ================================
# BlueZ Core Constants
# ================================
BLUEZ_SERVICE_NAME = "org.bluez"
BLUEZ_SERVICE_PATH = "/org/bluez"
ADAPTER_PATH       = "/org/bluez/hci0"
ADAPTER_IFACE      = "org.bluez.Adapter1"
AGENT_IFACE        = "org.bluez.Agent1"
AGENT_MANAGER_IFACE= "org.bluez.AgentManager1"
#DBUS
DBUS_ERROR_INVARG = 'org.freedesktop.DBus.Error.InvalidArgs'
DBUS_ERROR_PROPRO = 'org.freedesktop.DBus.Error.PropertyReadOnly'

# BlueZ GATT Interfaces
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE    = "org.bluez.GattCharacteristic1"
GATT_DESC_IFACE    = "org.bluez.GattDescriptor1"

# Standard D-Bus Properties Interface
DBUS_PROP_IFACE    = "org.freedesktop.DBus.Properties"
DBUS_OBJMGR_IFACE  = "org.freedesktop.DBus.ObjectManager"


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

# ================================
# Advertising Interfaces
# ================================
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"

DEVICE_IFACE = "org.bluez.Device1"
ADVERTISEMENT_PATH_BASE = "/org/example/advertisement"


#DisplayOnly, DisplayYesNo, KeyboardOnly, NoInputNoOutput, and KeyboardDisplay
AUTHORIZATION = "KeyboardDisplay"

HCI_DISCONNECT_REASONS = {
    0x00: "Success",
    0x01: "Unknown HCI Command",
    0x02: "Unknown Connection Identifier",
    0x03: "Hardware Failure",
    0x04: "Page Timeout",
    0x05: "Authentication Failure",
    0x06: "PIN or Key Missing",
    0x07: "Memory Capacity Exceeded",
    0x08: "Connection Timeout",
    0x09: "Connection Limit Exceeded",
    0x0C: "Command Disallowed",
    0x13: "Remote User Terminated Connection",
    0x14: "Remote Device Terminated Connection (Low Resources)",
    0x15: "Remote Device Terminated Connection (Power Off)",
    0x16: "Connection Terminated by Local Host",
    0x1A: "Unsupported Remote Feature",
    0x1F: "Unspecified Error",
    0x29: "Pairing With Unit Key Not Supported",
    0x3B: "Unacceptable Connection Parameters",
}