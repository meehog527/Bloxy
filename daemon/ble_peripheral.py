# ble_peripheral.py

import dbus
import dbus.service
import logging
from gi.repository import GLib
import yaml

from dbus_utils import DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE

# -------------------------------------------------------------------
# Logging configuration
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hid_daemon")


class GattObject(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        props = self.get_property_map()
        if prop in props:
            return props[prop]
        raise NotImplementedError(f'Unknown property: {prop}')

    def get_property_map(self):
        return {}

    def get_managed_object(self):
        return {self.path: {self.dbus_interface: self.get_property_map()}}


class HIDDescriptor(GattObject):
    dbus_interface = GATT_DESC_IFACE

    def __init__(self, bus, index, char, config):
        self.char = char
        self.uuid = config['uuid']
        self.flags = config.get('flags', [])
        raw_val = config.get('value', [])
        self.value = [dbus.Byte(v) for v in raw_val]
        path = f'{char.path}/desc{index}'
        super().__init__(bus, path)

    def get_property_map(self):
        return {
            'UUID': self.uuid,
            'Characteristic': dbus.ObjectPath(self.char.path),
            'Value': dbus.Array(self.value, signature='y'),
            'Flags': dbus.Array(self.flags, signature='s'),
        }

    @dbus.service.method(GATT_DESC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_DESC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        if self.uuid.lower() == '00002902-0000-1000-8000-00805f9b34fb':
            self.value = value
            enabled = len(value) >= 1 and int(value[0]) == 0x01
            self.char.set_notifying(enabled)
            print(f'CCCD write for {self.char.name}: notifications {"enabled" if enabled else "disabled"}')
        else:
            self.value = value


class HIDCharacteristic(GattObject):
    dbus_interface = GATT_CHRC_IFACE

    def __init__(self, bus, index, service, config):
        self.service = service
        self.uuid = config['uuid']
        self.flags = config.get('flags', [])
        raw_val = config.get('value', [])
        self.value = [dbus.Byte(v) for v in raw_val]
        self.name = config.get('name', self.uuid)
        self.notifying = bool(config.get('notifying', False))
        self.descriptors = []
        path = f'{service.path}/char{index}'
        super().__init__(bus, path)

        for i, desc_cfg in enumerate(config.get('descriptors', [])):
            self.descriptors.append(HIDDescriptor(bus, i, self, desc_cfg))

    def get_property_map(self):
        return {
            'UUID': self.uuid,
            'Service': dbus.ObjectPath(self.service.path),
            'Flags': dbus.Array(self.flags, signature='s'),
            'Value': dbus.Array(self.value, signature='y'),
            'Notifying': self.notifying,
        }

    def get_managed_object(self):
        obj = super().get_managed_object()
        obj[self.path][self.dbus_interface]['Descriptors'] = dbus.Array(
            [d.path for d in self.descriptors], signature='o'
        )
        for desc in self.descriptors:
            obj.update(desc.get_managed_object())
        return obj

    def set_notifying(self, enabled: bool):
        self.notifying = enabled

    def update_value(self, new_value_bytes):
        self.value = [dbus.Byte(v) for v in new_value_bytes]
        if self.notifying:
            try:
                self.PropertiesChanged(
                    GATT_CHRC_IFACE,
                    {'Value': dbus.Array(self.value, signature='y')},
                    []
                )
            except Exception as e:
                logger.warning(f"Failed to emit PropertiesChanged for {self.name}: {e}")

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        self.value = value

    @dbus.service.signal('org.freedesktop.DBus.Properties', signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass
    
    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self.notifying = False


class HIDService(GattObject):
    dbus_interface = GATT_SERVICE_IFACE

    def __init__(self, bus, index, config):
        self.uuid = config['uuid']
        self.primary = True
        self.characteristics = []
        self.includes = config.get('includes', [])
        path = f'/org/bluez/hid/service{index}'
        super().__init__(bus, path)

        for i, char_cfg in enumerate(config.get('characteristics', [])):
            self.characteristics.append(HIDCharacteristic(bus, i, self, char_cfg))

    def get_property_map(self):
        return {
            'UUID': self.uuid,
            'Primary': dbus.Boolean(self.primary),
            'Includes': dbus.Array(self.includes, signature='o'),
        }

    def get_managed_object(self):
        obj = super().get_managed_object()
        for char in self.characteristics:
            obj.update(char.get_managed_object())
        return obj


class HIDApplication(dbus.service.Object):
    """
    Implements org.freedesktop.DBus.ObjectManager for the HID GATT application.
    """
    def __init__(self, bus, services, path='/org/bluez/hid'):
        self.path = path
        self.services = services
        super().__init__(bus, self.path)
        logger.debug("HIDApplication initialized at %s with %d services", self.path, len(self.services))

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        for svc in self.services:
            response.update(svc.get_managed_object())
        return response


def load_yaml_config(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)