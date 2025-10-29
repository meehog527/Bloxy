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


class Agent(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, AGENT_PATH)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        logger.info("Release")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        logger.info(f"AuthorizeService: {device} {uuid}")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        logger.info(f"RequestPinCode: {device}")
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        logger.info(f"RequestPasskey: {device}")
        return dbus.UInt32(123456)

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        logger.info(f"DisplayPasskey: {device} {passkey} entered: {entered}")

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        logger.info(f"RequestConfirmation: {device} passkey={passkey}")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        logger.info(f"RequestAuthorization: {device}")

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        logger.info("Cancel called")

    # --- Added for KeyboardDisplay capability ---
    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        """
        Called when the agent needs to display a PIN code to the user.
        Required for KeyboardDisplay capability.
        """
        logger.info(f"DisplayPinCode: {device} pincode={pincode}")

class PeripheralController:
    def __init__(self, bus, services, config, app_path=HID_APP_PATH):
        self.bus = bus
        self.manager = dbus.Interface(
            self.bus.get_object("org.bluez", "/"),
            "org.freedesktop.DBus.ObjectManager"
        )
        self.services = services
        self.app_path = app_path
        self.adapter_path = ADAPTER_PATH
        self.agent = Agent(bus)
        self.is_on = False
        self.config = config

    def power_on_adapter(self):
        try:
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter, DBUS_PROP_IFACE)
            props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            logger.info("✅ Bluetooth adapter powered on.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to power on adapter: {e}")
            return False

    def power_off_adapter(self):
        try:
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter, DBUS_PROP_IFACE)
            props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(False))
            logger.info("✅ Bluetooth adapter powered off.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to power off adapter: {e}")
            return False

    def set_discoverable_pairable(self):
        try:
            adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter, DBUS_PROP_IFACE)
            props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True))
            props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
            logger.info("✅ Adapter set to discoverable and pairable.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to set discoverable/pairable: {e}")
            return False

    def register_agent(self):
        try:
            manager = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez"),
                "org.bluez.AgentManager1"
            )
            manager.RegisterAgent(AGENT_PATH, "DisplayYesNo")
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

        try:
            gatt_manager.RegisterApplication(
                self.app_path,
                {},
                reply_handler=lambda: logger.info("✅ RegisterApplication succeeded (async reply)."),
                error_handler=self.on_register_error,
            )
            logger.debug("RegisterApplication call sent, waiting for reply...")
            # ✅ Treat sending the async call as success
            return True
        except dbus.DBusException as e:
            logger.error("Error calling RegisterApplication: %s", e)
            return False
        
    def on_register_error(e):
        logger.error("❌ RegisterApplication failed: %s (%s)", e, type(e).__name__)
        import traceback
        logger.error("Traceback:\n%s", traceback.format_exc())

    
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
            props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
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
            self.trust_device(c[0])
            
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
            if "org.bluez.Device1" in ifaces:
                props = ifaces["org.bluez.Device1"]
                if props.get("Connected", False):
                    addr = props.get("Address")
                    name = props.get("Name")
                    connected.append((addr, name, path))

        return connected

import dbus
import dbus.service

class Advertisement(dbus.service.Object):
    PATH_BASE = "/org/example/advertisement"

    def __init__(self, bus, index, config, advertising_type="peripheral"):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = [svc["uuid"] for svc in config["peripheral"]["services"]]  # HID Service UUID
        self.local_name = config["peripheral"].get("localName", "HID Peripheral")
        self.manufacturer_data = {}
        self.solicit_uuids = None
        self.service_data = {}
        self.include_tx_power = True
        super().__init__(bus, self.path)

    def get_properties(self):
        return {
            LE_ADVERTISEMENT_IFACE: {
                "Type": self.ad_type,
                "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s"),
                "LocalName": dbus.String(self.local_name),
                "IncludeTxPower": dbus.Boolean(self.include_tx_power),
                "Flags": dbus.Byte(0x06) # General Discoverable Mode, BR/EDR Not Supported
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(dbus.PROPERTIES_IFACE,
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs: Invalid interface %s" % interface
            )
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        print("Advertisement released")