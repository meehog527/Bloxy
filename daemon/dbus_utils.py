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

import dbus
import dbus.service
import subprocess
import logging
import time

# Logging configuration
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("PeripheralController")

AGENT_PATH = "/org/bluez/hid_agent"

class Agent(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, AGENT_PATH)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self): pass

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

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def Cancel(self, device):
        logger.info(f"Cancel: {device}")

class PeripheralController:
    def __init__(self, bus, services, app_path='/org/bluez/hid'):
        self.bus = bus
        self.services = services
        self.app_path = app_path
        self.adapter_path = '/org/bluez/hci0'
        self.agent = Agent(bus)
        self.is_on = False

    def power_on_adapter(self):
        try:
            adapter = self.bus.get_object("org.bluez", self.adapter_path)
            props = dbus.Interface(adapter, "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            logger.info("✅ Bluetooth adapter powered on.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to power on adapter: {e}")
            return False

    def power_off_adapter(self):
        try:
            adapter = self.bus.get_object("org.bluez", self.adapter_path)
            props = dbus.Interface(adapter, "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(False))
            logger.info("✅ Bluetooth adapter powered off.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to power off adapter: {e}")
            return False

    def set_discoverable_pairable(self):
        try:
            adapter = self.bus.get_object("org.bluez", self.adapter_path)
            props = dbus.Interface(adapter, "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True))
            props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
            logger.info("✅ Adapter set to discoverable and pairable.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to set discoverable/pairable: {e}")
            return False

    def register_agent(self):
        try:
            manager = dbus.Interface(self.bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1")
            manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
            manager.RequestDefaultAgent(AGENT_PATH)
            logger.info("✅ Agent registered and set as default.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to register agent: {e}")
            return False

    def register_gatt_application(self):
        try:
            gatt_manager = dbus.Interface(self.bus.get_object("org.bluez", self.adapter_path), "org.bluez.GattManager1")
            gatt_manager.RegisterApplication(self.app_path, {}, timeout=60000)
            logger.info("✅ GATT application registered.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to register GATT application: {e}")
            return False

    def enable_advertising(self):
        try:
            process = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            commands = ['power on\n', 'discoverable on\n', 'pairable on\n', 'advertise on\n', 'exit\n']
            process.communicate(''.join(commands))
            time.sleep(2)
            result = subprocess.run(['bluetoothctl', 'show'], capture_output=True, text=True)
            output = result.stdout
            if "AdvertisingFlags" in output or "Discoverable: yes" in output:
                logger.info("✅ Advertising successfully enabled.")
                return True
            else:
                logger.warning("❌ Advertising not confirmed.")
                return False
        except Exception as e:
            logger.error(f"❌ Error enabling advertising: {e}")
            return False

    def trust_device(self, mac_address):
        try:
            device_path = f"/org/bluez/hci0/dev_{mac_address.replace(':', '_')}"
            device = self.bus.get_object("org.bluez", device_path)
            props = dbus.Interface(device, "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
            logger.info(f"✅ Device {mac_address} trusted.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to trust device {mac_address}: {e}")
            return False

    def start(self):
        logger.info("🚀 Starting peripheral controller...")
        success = (
            self.power_on_adapter() and
            self.set_discoverable_pairable() and
            self.register_agent() and
            self.register_gatt_application() and
            self.enable_advertising()
        )
        self.is_on = success
        if success:
            logger.info("✅ Peripheral started.")
        else:
            logger.error("❌ Peripheral failed to start.")
        return success

    def stop(self):
        result = self.power_off_adapter()
        self.is_on = False
        logger.info("🛑 Peripheral stopped.")
        return result

    def get_status(self):
        return {'is_on': self.is_on}