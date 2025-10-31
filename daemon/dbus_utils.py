# dbus_utils.py

import dbus
import dbus.service
import subprocess
import logging
import time

from constants import (
    DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE,
    HID_APP_PATH, HID_SERVICE_BASE, DAEMON_OBJ_PATH, AGENT_PATH, ADAPTER_PATH,
    BLUEZ_SERVICE_NAME, GATT_MANAGER_IFACE, LE_ADVERTISEMENT_IFACE, LE_ADVERTISING_MANAGER_IFACE, HCI_DISCONNECT_REASONS,
    DEVICE_IFACE, ADAPTER_IFACE, AGENT_IFACE, DBUS_OBJMGR_IFACE, AGENT_MANAGER_IFACE, BLUEZ_SERVICE_PATH,
    AUTHORIZATION, ADVERTISEMENT_PATH_BASE
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("PeripheralController")


class Agent(dbus.service.Object):
    """
    BlueZ Agent implementation (org.bluez.Agent1).
    Handles pairing and authorization requests from BlueZ.
    """

    def __init__(self, bus):
        super().__init__(bus, AGENT_PATH)

    # ------------------------------------------------------------------
    # BlueZ Agent1 interface methods
    # ------------------------------------------------------------------

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        """Called when the agent is unregistered or released by BlueZ."""
        logger.info("Agent released")

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        """Authorize a service connection request."""
        logger.info(f"AuthorizeService: {device} {uuid}")
        # Accept by returning normally
        # To reject: raise dbus.exceptions.DBusException("org.bluez.Error.Rejected", "Unauthorized")

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        """Request a PIN code (legacy pairing)."""
        logger.info(f"RequestPinCode: {device}")
        return dbus.String("0000")

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        """Request a numeric passkey (for SSP pairing)."""
        logger.info(f"RequestPasskey: {device}")
        return dbus.UInt32(123456)

    @dbus.service.method(AGENT_IFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        """Display a passkey with number of entered digits (for SSP)."""
        logger.info(f"DisplayPasskey: {device} passkey={passkey} entered={entered}")

    @dbus.service.method(AGENT_IFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        """Request confirmation of a displayed passkey."""
        logger.info(f"RequestConfirmation: {device} passkey={passkey}")
        # Accept by returning normally

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        """Request authorization for a device before pairing completes."""
        logger.info(f"RequestAuthorization: {device}")

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Cancel(self):
        """Called when the agent request is canceled by BlueZ."""
        logger.info("Agent request canceled")

    # ------------------------------------------------------------------
    # Additional methods for KeyboardDisplay capability
    # ------------------------------------------------------------------

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        """Display a PIN code to the user (KeyboardDisplay capability)."""
        logger.info(f"DisplayPinCode: {device} pincode={pincode}")

class PeripheralController:
    def __init__(self, bus, services, config, app_path=HID_APP_PATH):
        self.bus = bus
        self.manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OBJMGR_IFACE
        )
        self.services = services
        self.app_path = app_path
        self.adapter_path = ADAPTER_PATH
        self.agent = Agent(bus)
        self.is_on = False
        self.config = config
        self.event_log = [] 
        
        self.bus.add_signal_receiver(
            self.device_properties_changed,
            dbus_interface=DBUS_PROP_IFACE,
            signal_name="PropertiesChanged",
            arg0=DEVICE_IFACE,
            path_keyword="path"
        )

    def device_properties_changed(self, interface, changed, invalidated, path):
        """Log all property changes for org.bluez.Device1 objects."""
        if interface != DEVICE_IFACE:
            return

        device = self.bus.get_object(BLUEZ_SERVICE_NAME, path)
        props = dbus.Interface(device, DBUS_PROP_IFACE)
        addr = props.Get(DEVICE_IFACE, "Address")
        #name = props.Get(DEVICE_IFACE, "Name")

        for key, value in changed.items():
            #logger.info(f"🔔 Property changed: {addr} {key} = {value}")
            log = {
                "event": "property_changed",
                "address": addr,
                
                "path": path,
                "property": key,
                "value": value,
                "timestamp": time.time()
            }
            logger.info(f"🔔 Property changed: {log}")
            self.event_log.append(log)

        # Special handling for connect/disconnect
        if "Connected" in changed:
            if changed["Connected"]:
                logger.info(f"✅ Device connected: {addr}")
                if interface == DEVICE_IFACE:

                    dev_obj = self.bus.get_object("org.bluez", path)
                    dev_props = dbus.Interface(dev_obj, DBUS_PROP_IFACE)

                    # Mark Trusted and AutoConnect for resilience
                    try: 
                        props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
                        logger.info(f"✅ Device trusted: {addr}")
                    except(e): 
                        logger.info(f"✅ Device not trusted: {addr} - {e}")
                        pass

                    # Call Pair() on the device
                    dev_iface = dbus.Interface(dev_obj, DEVICE_IFACE)
                    paired = dev_props.Get(DEVICE_IFACE, "Paired")
                    if not paired:
                        try:
                            print("[*] Not paired yet, calling Pair()")
                            dev_iface.Pair()
                        except dbus.exceptions.DBusException as e:
                            print(f"[!] Pair() failed: {e}")
                    else:
                        print("[*] Device already paired, skipping Pair()")
                        
                    try:
                        for svc in self.services:
                            for ch in svc.characteristics:
                                name = (ch.name or '').lower()
                                if 'keyboard' in name and 'report' in name:
                                    keyboard_char = ch
                                    empty_report = [0x00] * 8
                                    ch.update_value(empty_report)
                                    logger.info("Sent dummy empty keyboard report")
                                elif 'mouse' in name and 'report' in name:
                                    mouse_char = ch
                    except Exception as e:
                            logger.exception("Error sending dummy report: %s", e)

            else:
                reason = None
                try:
                    reason = props.Get(DEVICE_IFACE, "DisconnectReason")
                except Exception:
                    reason = "unknown"
                logger.info(f"❌ Device disconnected: {addr} reason={reason}")

    def power_on_adapter(self):
        try:
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter, DBUS_PROP_IFACE)
            props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))
            logger.info("✅ Bluetooth adapter powered on.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to power on adapter: {e}")
            return False

    def power_off_adapter(self):
        try:
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter, DBUS_PROP_IFACE)
            props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(False))
            logger.info("✅ Bluetooth adapter powered off.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to power off adapter: {e}")
            return False

    def set_discoverable_pairable(self):
        try:
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter, DBUS_PROP_IFACE)
            props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(True))
            props.Set(ADAPTER_IFACE, "Pairable", dbus.Boolean(True))
            logger.info("✅ Adapter set to discoverable and pairable.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to set discoverable/pairable: {e}")
            return False

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
        except Exception as e:
            logger.error(f"❌ Failed to register agent: {e}")
            return False

    def register_gatt_application(self):
        logger.debug("=== Register GATT Application ===")
        logger.debug("Adapter path: %s", self.adapter_path)
        logger.debug("App path: %s", self.app_path)
        logger.debug("Bus name owner: %s", self.bus.get_unique_name())

        try:
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            gatt_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
            logger.debug("GattManager1 interface found on adapter.")
        except dbus.DBusException as e:
            logger.error("Could not get GattManager1 on adapter: %s", e)
            return False

        import traceback
        
        try:
            gatt_manager.RegisterApplication(
                self.app_path,
                {},
                reply_handler=lambda: logger.info("✅ RegisterApplication succeeded (async reply)."),
                error_handler=lambda e: logger.error("❌ RegisterApplication failed: %s (%s)", e, type(e).__name__)              
            )
            
            logger.debug("RegisterApplication call sent, waiting for reply...")
            # ✅ Treat sending the async call as success
            return True
        except dbus.DBusException as e:
            logger.error("Error calling RegisterApplication: %s", e)
            return False
    
    def enable_advertising(self):
        try:
            process = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            commands = ['power on\n', 'discoverable on\n', 'pairable on\n', 'advertise on\n', 'exit\n']
            process.communicate(''.join(commands))
            time.sleep(2)
            result = subprocess.run(['bluetoothctl', 'show'], capture_output=True, text=True)
            output = result.stdout
            if "Discoverable: yes" in output:
                logger.info("✅ Advertising successfully enabled.")
                return True
            else:
                logger.warning("❌ Advertising not confirmed.")
                return False
        except Exception as e:
            logger.error(f"❌ Error enabling advertising: {e}")
            return False
        
    def register_advertisement(self):
        adapter_path = ADAPTER_PATH
        adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
        ad_manager = dbus.Interface(adapter, LE_ADVERTISING_MANAGER_IFACE)

        self.advertisement = Advertisement(self.bus, 0, self.config)
        ad_manager.RegisterAdvertisement(
            self.advertisement.get_path(),
            {},
            reply_handler=lambda: logger.info("✅ Advertising registered: %s", self.advertisement.service_uuids),
            error_handler=lambda e: logger.error("❌ Failed to register advertisement: %s", e),
        )

    def trust_device(self, mac_address):
        try:
            device_path = f"{ADAPTER_PATH}/dev_{mac_address.replace(':', '_')}"
            device = self.bus.get_object(BLUEZ_SERVICE_NAME, device_path)
            props = dbus.Interface(device, DBUS_PROP_IFACE)
            props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
            logger.info(f"✅ Device {mac_address} trusted.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to trust device {mac_address}: {e}")
            return False

    def start(self):
        logger.info("🚀 Starting peripheral controller...")

        # Power on adapter
        if not self.power_on_adapter():
            logger.error("❌ Could not power on adapter.")
            return False

        # Make adapter discoverable/pairable
        if not self.set_discoverable_pairable():
            logger.error("❌ Could not make adapter discoverable.")
            return False

        # Register agent
        if not self.register_agent():
            logger.error("❌ Could not register agent.")
            return False

        # Register GATT application
        if not self.register_gatt_application():
            logger.error("❌ Peripheral failed to start.")
            return False
        
        connected = self.list_connected_devices()
        for c in connected:
            print(c[0])
            #self.trust_device(c[0])
            
        logger.debug(f"Connected devices: {self.list_connected_devices()}")
        
        return True

    def stop(self):
        result = self.power_off_adapter()
        self.is_on = False
        logger.info("🛑 Peripheral stopped.")
        return result

    def get_status(self):
        return {'is_on': self.is_on}
    
    def list_connected_devices(self):
        connected = []
        objects = self.manager.GetManagedObjects()
        for path, ifaces in objects.items():
            if DEVICE_IFACE in ifaces:
                props = ifaces[DEVICE_IFACE]
                if props.get("Connected", False):
                    addr = props.get("Address")
                    name = props.get("Name")
                    connected.append((addr, name, path))

        return connected

class Advertisement(dbus.service.Object):
    def __init__(self, bus, index, config, advertising_type="peripheral"):
        self.path = ADVERTISEMENT_PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = [svc["uuid"] for svc in config["peripheral"]["services"]]  # HID Service UUID
        self.local_name = config["peripheral"].get("localName", "HID Peripheral")
        self.manufacturer_data = {}
        self.solicit_uuids = None
        self.service_data = {}
        self.include_tx_power = True
        self.appearance = config["peripheral"].get("appearance", 960)
        super().__init__(bus, self.path)

    def get_properties(self):
        # Removed unsupported "Flags" property (BlueZ rejects it)
        return {
            LE_ADVERTISEMENT_IFACE: {
                "Type": dbus.String(self.ad_type),
                "ServiceUUIDs": dbus.Array([dbus.String(u) for u in self.service_uuids], signature="s"),
                "LocalName": dbus.String(self.local_name),
                "IncludeTxPower": dbus.Boolean(self.include_tx_power),
                "Appearance": dbus.UInt16(self.appearance),
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
        print("Advertisement released")