# dbus_utils.py

import dbus
import dbus.service
import subprocess
import logging
import time

from constants import (
    DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE,
    HID_APP_PATH, HID_SERVICE_BASE, DAEMON_OBJ_PATH, AGENT_PATH, ADAPTER_PATH,
    BLUEZ_SERVICE_NAME, GATT_MANAGER_IFACE, LE_ADVERTISEMENT_IFACE, LE_ADVERTISING_MANAGER_IFACE
)

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("PeripheralController")

# ----------------------------
# Agent (KeyboardDisplay)
# ----------------------------
class Agent(dbus.service.Object):
    """
    Agent implementing KeyboardDisplay capability:
      - The device can display a PIN and also enter it.
    Register with capability string 'KeyboardDisplay'.
    """

    def __init__(self, bus):
        super().__init__(bus, AGENT_PATH)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        logger.info("Agent.Release")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        logger.info(f"Agent.AuthorizeService: device={device}, uuid={uuid}")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        # For legacy devices that use PIN codes (BR/EDR)
        logger.info(f"Agent.RequestPinCode: device={device}")
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        # For devices that request a numeric passkey (BLE Secure Connections, etc.)
        logger.info(f"Agent.RequestPasskey: device={device}")
        return dbus.UInt32(123456)

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        # BlueZ wants us to display passkey and track entered digits
        logger.info(f"Agent.DisplayPasskey: device={device}, passkey={passkey}, entered={entered}")

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        # For “Yes/No” confirmation pairing flows
        logger.info(f"Agent.RequestConfirmation: device={device}, passkey={passkey}")
        # If you want to auto-accept, do nothing. To reject, raise a DBusException.
        # dbus.exceptions.DBusException("org.bluez.Error.Rejected", "User rejected confirmation")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        logger.info(f"Agent.RequestAuthorization: device={device}")
        # Auto-authorize. Raise to reject if needed.

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        logger.info("Agent.Cancel")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        # Needed for KeyboardDisplay capability
        logger.info(f"Agent.DisplayPinCode: device={device}, pincode={pincode}")


# ----------------------------
# Advertisement
# ----------------------------
class Advertisement(dbus.service.Object):
    PATH_BASE = "/org/example/advertisement"

    def __init__(self, bus, index, config, advertising_type="peripheral"):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        # Expect config format: { "peripheral": { "services": [ { "uuid": "..." }, ... ], "localName": "..." } }
        self.service_uuids = [svc["uuid"] for svc in config["peripheral"]["services"]]
        self.local_name = config["peripheral"].get("localName", "HID Peripheral")
        self.manufacturer_data = {}
        self.solicit_uuids = None
        self.service_data = {}
        self.include_tx_power = True
        super().__init__(bus, self.path)

    def get_properties(self):
        return {
            LE_ADVERTISEMENT_IFACE: {
                "Type": dbus.String(self.ad_type),
                "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s"),
                "LocalName": dbus.String(self.local_name),
                "IncludeTxPower": dbus.Boolean(self.include_tx_power),
                # Flags 0x06 = LE General Discoverable Mode + BR/EDR Not Supported
                "Flags": dbus.Byte(0x06),
                # Appearance (0x0080 example or set to what your device requires)
                "Appearance": dbus.UInt16(963),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs: Invalid interface %s" % interface
            )
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        logger.info("Advertisement released")


# ----------------------------
# Peripheral Controller
# ----------------------------
class PeripheralController:
    def __init__(self, bus, services, config, app_path=HID_APP_PATH):
        self.bus = bus
        self.services = services
        self.app_path = app_path
        self.adapter_path = ADAPTER_PATH
        self.agent = Agent(bus)
        self.is_on = False
        self.config = config
        self.advertisement = None

        # ObjectManager to enumerate objects
        self.manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            "org.freedesktop.DBus.ObjectManager",
        )

    # ------------- Adapter helpers -------------
    def _get_adapter_props(self):
        adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
        return dbus.Interface(adapter, DBUS_PROP_IFACE)

    def power_on_adapter(self):
        try:
            props = self._get_adapter_props()
            props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            logger.info("Bluetooth adapter powered on.")
            return True
        except Exception as e:
            logger.error(f"Failed to power on adapter: {e}")
            return False

    def power_off_adapter(self):
        try:
            props = self._get_adapter_props()
            props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(False))
            logger.info("Bluetooth adapter powered off.")
            return True
        except Exception as e:
            logger.error(f"Failed to power off adapter: {e}")
            return False

    def set_discoverable_pairable(self, discoverable=True, pairable=True):
        try:
            props = self._get_adapter_props()
            props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(discoverable))
            props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(pairable))
            logger.info(f"Adapter discoverable={discoverable}, pairable={pairable}.")
            return True
        except Exception as e:
            logger.error(f"Failed to set discoverable/pairable: {e}")
            return False

    def _warn_if_zero_adapter_address(self):
        try:
            props = self._get_adapter_props()
            addr = props.Get("org.bluez.Adapter1", "Address")
            if isinstance(addr, str) and addr.strip() == "00:00:00:00:00:00":
                logger.warning("Adapter address is 00:00:00:00:00:00. "
                               "Connections may fail. Check firmware and kernel driver.")
        except Exception as e:
            logger.debug(f"Could not read adapter address: {e}")

    # ------------- Agent registration -------------
    def register_agent(self):
        try:
            agent_mgr = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez"),
                "org.bluez.AgentManager1",
            )
            # Align capability to implemented methods
            agent_mgr.RegisterAgent(AGENT_PATH, "KeyboardDisplay")
            agent_mgr.RequestDefaultAgent(AGENT_PATH)
            logger.info("Agent registered as default (KeyboardDisplay).")
            return True
        except Exception as e:
            logger.error(f"Failed to register agent: {e}")
            return False

    # ------------- GATT application registration -------------
    def register_gatt_application(self):
        logger.debug("Registering GATT application...")
        try:
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            gatt_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
        except dbus.DBusException as e:
            logger.error(f"GattManager1 not found on adapter: {e}")
            return False

        try:
            # Async registration (non-blocking)
            gatt_manager.RegisterApplication(
                self.app_path,
                {},
                reply_handler=lambda: logger.info("RegisterApplication succeeded."),
                error_handler=lambda e: logger.error(f"RegisterApplication failed: {e}"),
            )
            logger.debug("RegisterApplication call dispatched.")
            return True
        except dbus.DBusException as e:
            logger.error(f"Error calling RegisterApplication: {e}")
            return False

    # ------------- Advertisement registration -------------
    def register_advertisement(self):
        try:
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            ad_manager = dbus.Interface(adapter_obj, LE_ADVERTISING_MANAGER_IFACE)
        except dbus.DBusException as e:
            logger.error(f"LEAdvertisingManager1 not found on adapter: {e}")
            return False

        try:
            self.advertisement = Advertisement(self.bus, 0, self.config)
            ad_manager.RegisterAdvertisement(
                self.advertisement.get_path(),
                {},
                reply_handler=lambda: logger.info(
                    f"Advertising registered: {self.advertisement.service_uuids}"
                ),
                error_handler=lambda e: logger.error(f"Failed to register advertisement: {e}"),
            )
            logger.debug("RegisterAdvertisement call dispatched.")
            return True
        except dbus.DBusException as e:
            logger.error(f"Error registering advertisement: {e}")
            return False

    # ------------- Device enumeration (no auto-trust on connect) -------------
    def list_connected_devices(self):
        connected = []
        try:
            objects = self.manager.GetManagedObjects()
            for path, ifaces in objects.items():
                if "org.bluez.Device1" in ifaces:
                    props = ifaces["org.bluez.Device1"]
                    if props.get("Connected", False):
                        addr = props.get("Address")
                        name = props.get("Name")
                        connected.append((addr, name, path))
        except Exception as e:
            logger.error(f"Error listing connected devices: {e}")
        return connected

    # ------------- Lifecycle -------------
    def start(self):
        logger.info("Starting peripheral controller...")

        if not self.power_on_adapter():
            return False

        self._warn_if_zero_adapter_address()

        if not self.set_discoverable_pairable(True, True):
            return False

        if not self.register_agent():
            return False

        if not self.register_gatt_application():
            return False

        if not self.register_advertisement():
            return False

        # Do not auto-trust devices just because they’re connected.
        # Trust should follow a successful pairing/auth event.

        self.is_on = True
        logger.info("Peripheral controller started.")
        return True

    def stop(self):
        # Optional: unregister advertisement/GATT here if you want explicit cleanup
        # For simplicity, powering off the adapter will drop them.
        ok = self.power_off_adapter()
        self.is_on = False
        logger.info("Peripheral stopped.")
        return ok

    def get_status(self):
        return {"is_on": self.is_on}

