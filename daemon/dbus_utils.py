# dbus_utils.py

import dbus
import dbus.service
import subprocess
import logging
import time
from gi.repository import GLib
import dbus.mainloop.glib

from constants import (
    DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE,
    HID_APP_PATH, HID_SERVICE_BASE, DAEMON_OBJ_PATH, AGENT_PATH, ADAPTER_PATH,
    BLUEZ_SERVICE_NAME, GATT_MANAGER_IFACE, LE_ADVERTISEMENT_IFACE, LE_ADVERTISING_MANAGER_IFACE, HCI_DISCONNECT_REASONS,
    DEVICE_IFACE, ADAPTER_IFACE, AGENT_IFACE, DBUS_OBJMGR_IFACE, AGENT_MANAGER_IFACE, BLUEZ_SERVICE_PATH,
    AUTHORIZATION, ADVERTISEMENT_PATH_BASE, LOG_LEVEL, LOG_FORMAT
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


class Agent(dbus.service.Object):
    """
    BlueZ Agent implementation (org.bluez.Agent1).
    Handles pairing and authorization requests from BlueZ.
    """

    def __init__(self, bus):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        super().__init__(bus, AGENT_PATH)

    # ------------------------------------------------------------------
    # BlueZ Agent1 interface methods
    # ------------------------------------------------------------------

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        """Called when the agent is unregistered or released by BlueZ."""
        self.logger.info("Agent released")

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        """Authorize a service connection request."""
        self.logger.info(f"AuthorizeService: {device} {uuid}")
        # Accept by returning normally
        # To reject: raise dbus.exceptions.DBusException("org.bluez.Error.Rejected", "Unauthorized")

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        """Request a PIN code (legacy pairing)."""
        self.logger.info(f"RequestPinCode: {device}")
        return dbus.String("0000")

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        """Request a numeric passkey (for SSP pairing)."""
        self.logger.info(f"RequestPasskey: {device}")
        return dbus.UInt32(123456)

    @dbus.service.method(AGENT_IFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        """Display a passkey with number of entered digits (for SSP)."""
        self.logger.info(f"DisplayPasskey: {device} passkey={passkey} entered={entered}")

    @dbus.service.method(AGENT_IFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        """Request confirmation of a displayed passkey."""
        self.logger.info(f"RequestConfirmation: {device} passkey={passkey}")
        # Accept by returning normally

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        """Request authorization for a device before pairing completes."""
        self.logger.info(f"RequestAuthorization: {device}")

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Cancel(self):
        """Called when the agent request is canceled by BlueZ."""
        self.logger.info("Agent request canceled")

    # ------------------------------------------------------------------
    # Additional methods for KeyboardDisplay capability
    # ------------------------------------------------------------------

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        """Display a PIN code to the user (KeyboardDisplay capability)."""
        self.logger.info(f"DisplayPinCode: {device} pincode={pincode}")

class Advertisement(dbus.service.Object):
    """
    LE Advertisement object (org.bluez.LEAdvertisement1).
    Exposes advertising data to BlueZ.
    """

    def __init__(self, bus, index, config, advertising_type="peripheral"):
        # --- Internal state ---
        self.path = ADVERTISEMENT_PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = [svc["uuid"] for svc in config["peripheral"]["services"]]
        self.local_name = config["peripheral"].get("localName", "HID Peripheral")
        self.manufacturer_data = {}
        self.solicit_uuids = None
        self.service_data = {}
        self.include_tx_power = True
        self.appearance = config["peripheral"].get("appearance", 960)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        super().__init__(bus, self.path)

        self.logger.debug(
            f"Advertisement initialized at {self.path} "
            f"with services={self.service_uuids}, local_name={self.local_name}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def get_properties(self):
        """
        Return the advertisement properties as expected by BlueZ.
        """
        props = {
            "Type": dbus.String(self.ad_type),
            "ServiceUUIDs": dbus.Array([dbus.String(u) for u in self.service_uuids], signature="s"),
            "LocalName": dbus.String(self.local_name),
            "IncludeTxPower": dbus.Boolean(self.include_tx_power),
            "Appearance": dbus.UInt16(self.appearance),
        }

        if self.manufacturer_data:
            props["ManufacturerData"] = dbus.Dictionary(self.manufacturer_data, signature="qv")
        if self.service_data:
            props["ServiceData"] = dbus.Dictionary(self.service_data, signature="sv")
        if self.solicit_uuids:
            props["SolicitUUIDs"] = dbus.Array([dbus.String(u) for u in self.solicit_uuids], signature="s")

        return {LE_ADVERTISEMENT_IFACE: props}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    # ------------------------------------------------------------------
    # BlueZ-facing D-Bus methods (org.freedesktop.DBus.Properties + LEAdvertisement1)
    # ------------------------------------------------------------------

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(
                f"org.freedesktop.DBus.Error.InvalidArgs: Invalid interface {interface}"
            )
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        """Called when the advertisement is released by BlueZ."""
        self.logger.info(f"Advertisement released at {self.path}")

class PeripheralController:
    """
    PeripheralController manages the lifecycle of a Bluetooth LE HID peripheral.
    Responsibilities:
      - Powering adapter on/off
      - Making adapter discoverable/pairable
      - Registering Agent, GATT Application, and Advertisement
      - Handling device property changes (connect/disconnect, trust, pairing)
      - Tracking connected devices
    """

    def __init__(self, bus, services, config, app_path=HID_APP_PATH):
        self.bus = bus
        self.services = services
        self.app_path = app_path
        self.adapter_path = ADAPTER_PATH
        self.agent = Agent(bus)
        self.config = config
        self.advertisement = Advertisement(bus, 0, config)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.connected_devices = {}


        # New flags
        self._ready_cb = None
        self._failed_cb = None
        self._ready_emitted = False
        self._starting = False
        self.is_on = False

        # Subscribe to BlueZ signals
        mngr = dbus.Interface(
            self.bus.get_object("org.bluez", "/"),
            "org.freedesktop.DBus.ObjectManager"
        )
        mngr.connect_to_signal("InterfacesAdded", self._on_interface_added)
        mngr.connect_to_signal("InterfacesRemoved", self._on_interface_removed)

        self.bus.add_signal_receiver(
            self._on_properties_changed,
            bus_name="org.bluez",
            signal_name="PropertiesChanged",
            dbus_interface="org.freedesktop.DBus.Properties",
            path_keyword="path"
        )

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_interface_added(self, path, ifaces):
        if "org.bluez.Device1" in ifaces:
            props = ifaces["org.bluez.Device1"]
            addr = str(props.get("Address"))
            self.logger.info(f"📡 Device discovered: {addr} ({path})")

    def _on_interface_removed(self, path, ifaces):
        if "org.bluez.Device1" in ifaces:
            addr = path.split("dev_")[-1].replace("_", ":")
            self.logger.info(f"🗑️ Device removed: {addr} ({path})")
            self.connected_devices.pop(addr, None)

    def _on_properties_changed(self, interface, changed, invalidated, path):
        if interface != "org.bluez.Device1":
            return
        addr = path.split("dev_")[-1].replace("_", ":")
        if "Connected" in changed:
            if changed["Connected"]:
                self.logger.info(f"🔗 Device connected: {addr} ({path})")
                self.connected_devices[addr] = path
            else:
                self.logger.info(f"❌ Device disconnected: {addr} ({path})")
                self.connected_devices.pop(addr, None)


    # ----------------------------------------------------------------------
    # Adapter control
    # ----------------------------------------------------------------------

    def power_on_adapter(self):
        adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
        props = dbus.Interface(adapter, DBUS_PROP_IFACE)
        props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))
        self.logger.info("✅ Bluetooth adapter powered on.")

    def power_off_adapter(self):
        adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
        props = dbus.Interface(adapter, DBUS_PROP_IFACE)
        props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(False))
        self.logger.info("✅ Bluetooth adapter powered off.")

    def set_discoverable_pairable(self):
        adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
        props = dbus.Interface(adapter, DBUS_PROP_IFACE)
        props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(True))
        props.Set(ADAPTER_IFACE, "Pairable", dbus.Boolean(True))
        self.logger.info("✅ Adapter set to discoverable and pairable.")

    # ----------------------------------------------------------------------
    # Agent registration
    # ----------------------------------------------------------------------

    def register_agent(self):
        manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, BLUEZ_SERVICE_PATH),
            AGENT_MANAGER_IFACE
        )
        try:
            manager.RegisterAgent(AGENT_PATH, AUTHORIZATION)
            manager.RequestDefaultAgent(AGENT_PATH)
            self.logger.info("✅ Agent registered and set as default.")
        except dbus.exceptions.DBusException as e:
            if "AlreadyExists" in str(e):
                self.logger.warning("⚠️ Agent already exists, reusing.")
            else:
                raise

    # ----------------------------------------------------------------------
    # GATT + Advertisement
    # ----------------------------------------------------------------------

    def register_gatt_application_and_advertisement(self):
        manager = dbus.Interface(
            self.bus.get_object("org.bluez", self.adapter_path),
            "org.bluez.GattManager1"
        )
        manager.RegisterApplication(
            self.app_path,
            {},
            reply_handler=self._on_app_registered,
            error_handler=self._on_app_error
        )
        self.logger.debug("RegisterApplication call sent...")

    def _on_app_registered(self, *args):
        self.logger.info("✅ Application registered, now registering advertisement...")
        adv = dbus.Interface(
            self.bus.get_object("org.bluez", self.adapter_path),
            "org.bluez.LEAdvertisingManager1"
        )
        adv.RegisterAdvertisement(
            self.advertisement.get_path(),
            {},
            reply_handler=self._on_adv_registered,
            error_handler=self._on_adv_error
        )

    def _on_app_error(self, error):
        msg = str(error)
        if "AlreadyExists" in msg:
            self.logger.warning("⚠️ Application already registered, continuing...")
            self._on_app_registered()
        else:
            self.logger.error(f"❌ Application registration failed: {error}")
            self._emit_failed(msg)

    def _on_adv_registered(self, *args):
        self.logger.info("✅ Advertisement registered successfully.")
        self._emit_ready()

    def _on_adv_error(self, error):
        msg = str(error)
        if "NoReply" in msg:
            self.logger.warning("⚠️ Advertisement registration timed out, retrying...")
            GLib.timeout_add_seconds(2, self._retry_advertisement)
        elif "AlreadyExists" in msg:
            self.logger.warning("⚠️ Advertisement already exists, continuing...")
            if not self._ready_emitted:
                self._emit_ready()
        else:
            self.logger.error(f"❌ Advertisement registration failed: {error}")
            self._emit_failed(msg)

    def _retry_advertisement(self):
        adv = dbus.Interface(
            self.bus.get_object("org.bluez", self.adapter_path),
            "org.bluez.LEAdvertisingManager1"
        )
        adv.RegisterAdvertisement(
            self.advertisement.get_path(),
            {},
            reply_handler=self._on_adv_registered,
            error_handler=self._on_adv_error
        )
        return False

    # ----------------------------------------------------------------------
    # Ready/failed signaling
    # ----------------------------------------------------------------------

    def on_ready(self, cb): self._ready_cb = cb
    def on_failed(self, cb): self._failed_cb = cb

    def _emit_ready(self):
        if self._ready_emitted:
            return
        self._ready_emitted = True
        self.is_on = True
        if self._ready_cb:
            self._ready_cb()

    def _emit_failed(self, reason):
        self._starting = False
        if self._failed_cb:
            self._failed_cb(reason)

    # ----------------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------------

    def start(self):
        if self._starting:
            self.logger.debug("Start requested while already starting; ignoring.")
            return True
        self._starting = True
        self._ready_emitted = False
        self.is_on = False
        self.logger.info("🚀 Starting peripheral controller...")
        try:
            self.power_on_adapter()
            self.set_discoverable_pairable()
            self.register_agent()
            self.register_gatt_application_and_advertisement()
            return True
        except Exception as e:
            self.logger.exception(f"❌ Peripheral failed to start synchronously: {e}")
            self._emit_failed(str(e))
            return False

    def stop(self):
        self._starting = False
        self._ready_emitted = False
        try:
            adv = dbus.Interface(
                self.bus.get_object("org.bluez", self.adapter_path),
                "org.bluez.LEAdvertisingManager1"
            )
            adv.UnregisterAdvertisement(self.advertisement.get_path())
            self.logger.info("🛑 Advertisement unregistered.")
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to unregister advertisement: {e}")
        try:
            self.power_off_adapter()
        finally:
            self.is_on = False
            self.logger.info("🛑 Peripheral stopped.")
        return True
    
    # ----------------------------------------------------------------------
    # Diagnostics
    # ----------------------------------------------------------------------

    def _check_adapter(self):
        try:
            adapter = self.bus.get_object("org.bluez", self.adapter_path)
            props = dbus.Interface(adapter, "org.freedesktop.DBus.Properties")
            powered = props.Get("org.bluez.Adapter1", "Powered")
            discoverable = props.Get("org.bluez.Adapter1", "Discoverable")
            pairable = props.Get("org.bluez.Adapter1", "Pairable")
            return f"Adapter powered={powered}, discoverable={discoverable}, pairable={pairable}"
        except Exception as e:
            return f"Adapter check failed: {e}"

    def _check_devices(self):
        try:
            mngr = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
            objs = mngr.GetManagedObjects()
            devices = [path for path, ifaces in objs.items() if "org.bluez.Device1" in ifaces]
            return f"Devices seen: {devices}"
        except Exception as e:
            return f"Device check failed: {e}"
    
    def remove_cached_device(self, mac_address):
        """
        Remove a cached Bluetooth device from BlueZ by MAC address.
        Example: remove_cached_device("AA:BB:CC:DD:EE:FF")
        """
        try:
            # Build the device object path
            dev_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            adapter_iface = dbus.Interface(adapter, "org.bluez.Adapter1")

            adapter_iface.RemoveDevice(dev_path)
            self.logger.info(f"🗑️ Removed cached device {mac_address} ({dev_path})")
            return True
        except dbus.exceptions.DBusException as e:
            self.logger.error(f"❌ Failed to remove cached device {mac_address}: {e}")
            return False

    def list_cached_devices(self):
        """
        List all cached Bluetooth devices known to BlueZ.
        Returns a list of dicts with plain Python types.
        """
        devices = []
        try:
            mngr = dbus.Interface(
                self.bus.get_object("org.bluez", "/"),
                "org.freedesktop.DBus.ObjectManager"
            )
            objs = mngr.GetManagedObjects()
            for path, ifaces in objs.items():
                if "org.bluez.Device1" in ifaces:
                    props = ifaces["org.bluez.Device1"]
                    # Cast dbus types to native Python
                    addr = str(props.get("Address"))
                    name = str(props.get("Name")) if "Name" in props else None
                    paired = bool(props.get("Paired"))
                    trusted = bool(props.get("Trusted"))
                    connected = bool(props.get("Connected"))
                    devices.append({
                        "path": str(path),
                        "address": addr,
                        "name": name,
                        "paired": paired,
                        "trusted": trusted,
                        "connected": connected
                    })
            return devices
        except Exception as e:
            self.logger.error(f"❌ Failed to list cached devices: {e}")
            return []

