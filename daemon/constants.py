# ================================
# Your Daemon Identity
# ================================
DAEMON_BUS_NAME    = "org.example.HIDPeripheral"          # well-known bus name
DAEMON_IFACE       = "org.example.HIDPeripheral.Control"  # control API interface

# Application (GATT hierarchy root)
HID_APP_PATH       = "/org/example/HIDPeripheral"         # root path BlueZ will introspect
HID_SERVICE_BASE   = f"{HID_APP_PATH}/service"            # base path for services/characteristics

# Daemon Control API (separate object)
DAEMON_OBJ_PATH    = "/org/example/HIDPeripheral/daemon"  # where your control API lives