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
        # --- Internal state ---
        self.bus = bus
        self.manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OBJMGR_IFACE)
        self.services = services
        self.app_path = app_path
        self.adapter_path = ADAPTER_PATH
        self.agent = Agent(bus)
        self.is_on = False
        self.config = config
        self.event_log = []
        self.advertisement = Advertisement(bus, 0, config)

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        

        # Subscribe to Device1 property changes
        self.bus.add_signal_receiver(
            self.device_properties_changed,
            dbus_interface=DBUS_PROP_IFACE,
            signal_name="PropertiesChanged",
            arg0=DEVICE_IFACE,
            path_keyword="path"
        )

    # ----------------------------------------------------------------------
    # Signal handlers
    # ----------------------------------------------------------------------

    def device_properties_changed(self, interface, changed, invalidated, path):
        """Entry point for org.bluez.Device1 property changes."""
        if interface != DEVICE_IFACE:
            return

        device = self.bus.get_object(BLUEZ_SERVICE_NAME, path)
        props = dbus.Interface(device, DBUS_PROP_IFACE)
        addr = props.Get(DEVICE_IFACE, "Address")

        # Always log changes
        self._log_property_changes(addr, path, changed)

        # Handle connection state
        if "Connected" in changed:
            if changed["Connected"]:
                self._handle_device_connected(addr, path, props)
            else:
                self._handle_device_disconnected(addr, props)

    # ----------------------------------------------------------------------
    # Targeted helpers for property changes
    # ----------------------------------------------------------------------

    def _log_property_changes(self, addr, path, changed):
        """Log all property changes with timestamp."""
        for key, value in changed.items():
            log = {
                "event": "property_changed",
                "address": addr,
                "path": path,
                "property": key,
                "value": value,
                "timestamp": time.time()
            }
            self.logger.info(f"🔔 Property changed: {log}")
            self.event_log.append(log)

    def _handle_device_connected(self, addr, path, props):
        """Handle a device connection event."""
        self.logger.info(f"✅ Device connected: {addr}")

        dev_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, path)
        dev_props = dbus.Interface(dev_obj, DBUS_PROP_IFACE)
        dev_iface = dbus.Interface(dev_obj, DEVICE_IFACE)

        # Mark Trusted
        try:
            props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
            self.logger.info(f"✅ Device trusted: {addr}")
        except Exception as e:
            self.logger.warning(f"⚠️ Could not set Trusted for {addr}: {e}")

        # Pair if not already paired
        paired = dev_props.Get(DEVICE_IFACE, "Paired")
        if not paired:
            try:
                self.logger.info("[*] Not paired yet, calling Pair()")
                dev_iface.Pair()
            except dbus.exceptions.DBusException as e:
                self.logger.error(f"[!] Pair() failed: {e}")
        else:
            self.logger.debug("[*] Device already paired, skipping Pair()")

        # Send dummy HID reports
        self._send_dummy_reports()

    def _handle_device_disconnected(self, addr, props):
        """Handle a device disconnection event."""
        try:
            reason = props.Get(DEVICE_IFACE, "DisconnectReason")
        except Exception:
            reason = "unknown"
        self.logger.info(f"❌ Device disconnected: {addr} reason={reason}")

    def _send_dummy_reports(self):
        """Send initial empty HID reports for keyboard/mouse."""
        try:
            for svc in self.services:
                for ch in svc.characteristics:
                    name = (ch.name or '').lower()
                    if 'keyboard' in name and 'report' in name:
                        empty_report = [0x00] * 8
                        ch.update_value(empty_report)
                        self.logger.info("Sent dummy empty keyboard report")
                    elif 'mouse' in name and 'report' in name:
                        empty_report = [0x00] * 4
                        ch.update_value(empty_report)
                        self.logger.info("Sent dummy empty mouse report")
        except Exception as e:
            self.logger.exception("Error sending dummy report: %s", e)

    # ----------------------------------------------------------------------
    # Adapter control
    # ----------------------------------------------------------------------

    def power_on_adapter(self):
        try:
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter, DBUS_PROP_IFACE)
            props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))
            self.logger.info("✅ Bluetooth adapter powered on.")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to power on adapter: {e}")
            return False

    def power_off_adapter(self):
        try:
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter, DBUS_PROP_IFACE)
            props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(False))
            self.logger.info("✅ Bluetooth adapter powered off.")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to power off adapter: {e}")
            return False

    def set_discoverable_pairable(self):
        try:
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter, DBUS_PROP_IFACE)
            props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(True))
            props.Set(ADAPTER_IFACE, "Pairable", dbus.Boolean(True))
            self.logger.info("✅ Adapter set to discoverable and pairable.")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to set discoverable/pairable: {e}")
            return False

    # ----------------------------------------------------------------------
    # Agent registration
    # ----------------------------------------------------------------------

    def register_agent(self):
        try:
            manager = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, BLUEZ_SERVICE_PATH),
                AGENT_MANAGER_IFACE
            )
            manager.RegisterAgent(AGENT_PATH, AUTHORIZATION)
            manager.RequestDefaultAgent(AGENT_PATH)
            logger.info("✅ Agent registered and set as default.")
            return True

        except dbus.exceptions.DBusException as e:
            if "AlreadyExists" in str(e):
                logger.warning("⚠️ Agent already exists, attempting to unregister and re‑register...")
                try:
                    manager.UnregisterAgent(AGENT_PATH)
                    manager.RegisterAgent(AGENT_PATH, AUTHORIZATION)
                    manager.RequestDefaultAgent(AGENT_PATH)
                    logger.info("✅ Agent re‑registered after cleanup.")
                    return True
                except dbus.exceptions.DBusException as inner:
                    logger.error(f"❌ Failed to re‑register agent: {inner}")
                    return False
            else:
                logger.error(f"❌ Failed to register agent: {e}")
                return False


    # ----------------------------------------------------------------------
    # GATT application
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
        self.logger.debug("RegisterApplication call sent, waiting for reply...")


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
            # Go straight to advertisement registration
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
        else:
            self.logger.error(f"❌ Application registration failed: {error}")
            self._emit_failed(msg)



    def _on_adv_registered(self, *args):
        self.logger.info("✅ Advertisement registered successfully.")
        self._emit_ready()

    def _on_adv_error(self, error):
        msg = str(error)
        if "NoReply" in msg:
            self.logger.warning("⚠️ Advertisement registration timed out, retrying in 2s...")
            GLib.timeout_add_seconds(2, self._retry_advertisement)
        elif "AlreadyExists" in msg:
            self.logger.warning("⚠️ Advertisement already exists, continuing...")
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
        return False  # stop GLib timeout


    # Simple readiness signaling hooks
    def on_ready(self, cb):
        self._ready_cb = cb

    def on_failed(self, cb):
        self._failed_cb = cb

    def _emit_ready(self):
        if hasattr(self, "_ready_cb") and self._ready_cb:
            self._ready_cb()

    def _emit_failed(self, reason):
        if hasattr(self, "_failed_cb") and self._failed_cb:
            self._failed_cb(reason)


    # ----------------------------------------------------------------------
    # Advertising
    # ----------------------------------------------------------------------

    def register_advertisement(self):
        manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, ADAPTER_PATH), LE_ADVERTISING_MANAGER_IFACE)
        try:
            manager.RegisterAdvertisement(self.advertisement, {})
            logger.info("✅ Advertisement registered.")
            return True
        except dbus.exceptions.DBusException as e:
            if "AlreadyExists" in str(e) or "already a handler" in str(e):
                logger.warning("⚠️ Advertisement already exists, unregistering and retrying...")
                try:
                    self.unregister_advertisement()
                    manager.RegisterAdvertisement(self.advertisement, {})
                    logger.info("✅ Advertisement re‑registered after cleanup.")
                    return True
                except dbus.exceptions.DBusException as inner:
                    logger.error(f"❌ Failed to re‑register advertisement: {inner}")
                    return False
            else:
                logger.error(f"❌ Could not register advertisement: {e}")
                return False


    def unregister_advertisement(self):
        try:
            if self.advertisement:
                adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
                self.manager = dbus.Interface(adapter, LE_ADVERTISING_MANAGER_IFACE)
                self.manager.UnregisterAdvertisement(self.advertisement.get_path())
                self.logger.info("🛑 Advertisement unregistered.")
        except Exception as e:
            self.logger.error(f"❌ Failed to unregister advertisement: {e}")

    # ----------------------------------------------------------------------
    # Device management
    # ----------------------------------------------------------------------

    def trust_device(self, mac_address):
        """
        Mark a device as trusted so it can reconnect without prompting.
        """
        try:
            device_path = f"{ADAPTER_PATH}/dev_{mac_address.replace(':', '_')}"
            device = self.bus.get_object(BLUEZ_SERVICE_NAME, device_path)
            props = dbus.Interface(device, DBUS_PROP_IFACE)
            props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
            self.logger.info(f"✅ Device {mac_address} trusted.")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to trust device {mac_address}: {e}")
            return False

    #def list_connected_devices(self):
    #    """
    #    Return a list of currently connected devices as (addr, name, path).
    #    """
    #    connected = []
    #    objects = self.manager.GetManagedObjects()
    #    for path, ifaces in objects.items():
    #        if DEVICE_IFACE in ifaces:
    #            props = ifaces[DEVICE_IFACE]
    #            if props.get("Connected", False):
    #                addr = props.get("Address")
    #                name = props.get("Name")
    #                connected.append((addr, name, path))
    #    return connected

    # ----------------------------------------------------------------------
    # Lifecycle management
    # ----------------------------------------------------------------------

    def start(self):
        self.logger.info("🚀 Starting peripheral controller...")
        try:
            self.power_on_adapter()
            self.set_discoverable_pairable()
            self.register_agent()
            # Kick off async registration; don’t treat as failure here
            self.register_gatt_application_and_advertisement()
            return True
        except Exception as e:
            self.logger.exception(f"❌ Peripheral failed to start synchronously: {e}")
            self._emit_failed(str(e))
            return False

    def stop(self):
        """
        Stop the peripheral: unregister advertisement and power off adapter.
        """
        self.unregister_advertisement()
        result = self.power_off_adapter()
        self.is_on = False
        self.logger.info("🛑 Peripheral stopped.")
        return result

    def get_status(self):
        """
        Return current status of the peripheral.
        """
        return {'is_on': self.is_on}