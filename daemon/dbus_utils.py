# dbus_utils.py

import dbus
import dbus.service
import subprocess
import logging
import time

from constants import (
    DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE,
    HID_APP_PATH, HID_SERVICE_BASE, DAEMON_OBJ_PATH, AGENT_PATH, ADAPTER_PATH,
    BLUEZ_SERVICE_NAME, GATT_MANAGER_IFACE
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


class PeripheralController:
    def __init__(self, bus, services, app_path='/org/bluez/hid'):
        self.bus = bus
        self.services = services
        self.app_path = app_path
        self.adapter_path = ADAPTER_PATH
        self.agent = Agent(bus)
        self.is_on = False

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
            manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
            manager.RequestDefaultAgent(AGENT_PATH)
            logger.info("✅ Agent registered and set as default.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to register agent: {e}")
            return False

    def register_gatt_application(self):
        try:
            logger.debug("=== Register GATT Application ===")
            logger.debug(f"Adapter path: {self.adapter_path}")
            logger.debug(f"App path: {self.app_path}")
            logger.debug(f"Bus name owner: {self.bus.get_unique_name()}")

            # Check adapter object exists
            try:
                obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
                logger.debug("Adapter object retrieved successfully.")
            except Exception as e:
                logger.error(f"Failed to get adapter object at {self.adapter_path}: {e}")
                return False

            # Introspect adapter to confirm GattManager1 is present
            try:
                introspect_iface = dbus.Interface(obj, "org.freedesktop.DBus.Introspectable")
                xml = introspect_iface.Introspect()
                if GATT_MANAGER_IFACE in xml:
                    logger.debug("GattManager1 interface found on adapter.")
                else:
                    logger.error("GattManager1 interface NOT found on adapter. Is bluetoothd running with -E?")
            except Exception as e:
                logger.error(f"Failed to introspect adapter: {e}")

            gatt_manager = dbus.Interface(obj, GATT_MANAGER_IFACE)

            # Confirm our application object is exported
            try:
                app_obj = self.bus.get_object(self.bus.get_unique_name(), self.app_path)
                introspect_iface = dbus.Interface(app_obj, "org.freedesktop.DBus.Introspectable")
                xml = introspect_iface.Introspect()
                logger.debug(f"Introspection of {self.app_path}:\n{xml}")
                if "ObjectManager" in xml:
                    logger.debug("Our application object implements ObjectManager.")
                else:
                    logger.error("Our application object does NOT implement ObjectManager!")
            except Exception as e:
                logger.error(f"Could not introspect our own app object at {self.app_path}: {e}")

            # Call GetManagedObjects directly to see what we’ll return
            try:
                app_iface = dbus.Interface(app_obj, "org.freedesktop.DBus.ObjectManager")
                managed = app_iface.GetManagedObjects()
                logger.debug(f"GetManagedObjects returned {len(managed)} objects:")
                for path, ifaces in managed.items():
                    logger.debug(f"  {path}: {list(ifaces.keys())}")
            except Exception as e:
                logger.error(f"Error calling GetManagedObjects on our app: {e}")

            # Now attempt registration
            app_obj_path = dbus.ObjectPath(self.app_path)
            options = dbus.Dictionary({}, signature='sv')

            logger.debug(f"Calling RegisterApplication({app_obj_path}, options={dict(options)})")

            def reply_handler():
                logger.info("✅ RegisterApplication succeeded (async reply).")

            def error_handler(err):
                logger.error(f"❌ RegisterApplication failed (async error): {err}")

            # Use async form so we can see errors without blocking
            gatt_manager.RegisterApplication(app_obj_path, options,
                                            reply_handler=reply_handler,
                                            error_handler=error_handler)

            logger.debug("RegisterApplication call sent, waiting for reply...")
            return True

        except Exception as e:
            logger.exception("❌ Exception during RegisterApplication")
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
            if "Discoverable: yes" in output:
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
            device_path = f"/{ADAPTER_PATH}/dev_{mac_address.replace(':', '_')}"
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