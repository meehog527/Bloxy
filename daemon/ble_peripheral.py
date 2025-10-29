# ble_peripheral.py

import dbus
import dbus.service
import logging
from gi.repository import GLib
import yaml

from constants import (
    DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE,
    HID_APP_PATH, HID_SERVICE_BASE, DAEMON_OBJ_PATH
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hid_daemon")


class GattObject(dbus.service.Object):
    dbus_interface = None  # override in subclasses

    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.path = path  # ensure set for get_managed_object

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        if interface != self.dbus_interface:
            raise dbus.exceptions.DBusException('org.freedesktop.DBus.Error.InvalidArgs')
        props = self.get_property_map()
        if prop in props:
            return props[prop]
        raise dbus.exceptions.DBusException('org.freedesktop.DBus.Error.InvalidArgs')

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == self.dbus_interface:
            return self.get_property_map()
        return {}

    def get_property_map(self):
        return {}

    def get_managed_object(self):
        # Use dbus.ObjectPath for the key, strict types inside
        return {
            dbus.ObjectPath(self.path): {
                self.dbus_interface: self.get_property_map()
            }
        }


class HIDDescriptor(GattObject):
    dbus_interface = GATT_DESC_IFACE

    def __init__(self, bus, index, char, config):
        self.char = char
        self.uuid = config['uuid']
        self.flags = config.get('flags', [])
        raw_val = config.get('value', [])
        self.value = [dbus.Byte(int(v) & 0xFF) for v in raw_val]
        path = f'{char.path}/desc{index}'
        super().__init__(bus, path)

    def get_property_map(self):
        return {
            'UUID': dbus.String(self.uuid),
            'Characteristic': dbus.ObjectPath(self.char.path),
            'Value': dbus.Array(self.value, signature='y'),
            'Flags': dbus.Array([dbus.String(f) for f in self.flags], signature='s'),
        }

    @dbus.service.method(GATT_DESC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_DESC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        # CCCD handling (0x2902)
        if self.uuid.lower() == '00002902-0000-1000-8000-00805f9b34fb':
            self.value = [dbus.Byte(int(b) & 0xFF) for b in value]
            notify_enabled = len(value) >= 1 and (int(value[0]) & 0x01) != 0
            self.char.set_notifying(notify_enabled)
            logger.info(f'CCCD write for {self.char.name}: notifications {"enabled" if notify_enabled else "disabled"}')
        else:
            self.value = [dbus.Byte(int(b) & 0xFF) for b in value]


class HIDCharacteristic(GattObject):
    dbus_interface = GATT_CHRC_IFACE

    def __init__(self, bus, index, service, config):
        self.service = service
        self.uuid = config['uuid']
        self.flags = config.get('flags', [])
        raw_val = config.get('value', [])
        self.value = [dbus.Byte(int(v) & 0xFF) for v in raw_val]
        self.name = config.get('name', self.uuid)
        self.notifying = bool(config.get('notifying', False))
        self.descriptors = []
        path = f'{service.path}/char{index}'
        super().__init__(bus, path)

        for i, desc_cfg in enumerate(config.get('descriptors', [])):
            self.descriptors.append(HIDDescriptor(bus, i, self, desc_cfg))

    def get_property_map(self):
        # Keep only the properties BlueZ expects here; expose Value via ReadValue/WriteValue
        return {
            'UUID': dbus.String(self.uuid),
            'Service': dbus.ObjectPath(self.service.path),
            'Flags': dbus.Array([dbus.String(f) for f in self.flags], signature='s'),
            'Notifying': dbus.Boolean(self.notifying),
        }

    def get_managed_object(self):
        obj = super().get_managed_object()
        for desc in self.descriptors:
            obj.update(desc.get_managed_object())
        return obj

    def set_notifying(self, enabled: bool):
        enabled = bool(enabled)
        if self.notifying != enabled:
            self.notifying = enabled
            try:
                self.PropertiesChanged(
                    self.dbus_interface,
                    {'Notifying': dbus.Boolean(self.notifying)},
                    []
                )
            except Exception as e:
                logger.warning(f"Failed to emit PropertiesChanged(Notifying) for {self.name}: {e}")

    def update_value(self, new_value_bytes):
        new_value = [dbus.Byte(int(v) & 0xFF) for v in new_value_bytes]

        # Skip if identical to current value
        if new_value == self.value:
            return

        self.value = new_value
        try:
            self.PropertiesChanged(
                self.dbus_interface,
                {'Value': dbus.Array(self.value, signature='y')},
                []
            )
        except Exception as e:
            logger.warning(f"Failed to emit PropertiesChanged(Value) for {self.name}: {e}")

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        # Return the current value
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        self.value = [dbus.Byte(int(b) & 0xFF) for b in value]
        try:
            self.PropertiesChanged(
                self.dbus_interface,
                {'Value': dbus.Array(self.value, signature='y')},
                []
            )
        except Exception as e:
            logger.debug(f"WriteValue PropertiesChanged skipped: {e}")

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StartNotify(self):
        self.set_notifying(True)

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StopNotify(self):
        self.set_notifying(False)

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class HIDService(GattObject):
    dbus_interface = GATT_SERVICE_IFACE

    def __init__(self, bus, index, config):
        self.uuid = config['uuid']
        self.primary = (config.get('type', 'primary') == 'primary')
        self.characteristics = []
        includes_cfg = config.get('includes', [])
        self.includes = [dbus.ObjectPath(p) for p in includes_cfg] if includes_cfg else []
        self.path = f"{HID_SERVICE_BASE}{index}"
        super().__init__(bus, self.path)

        for i, char_cfg in enumerate(config.get('characteristics', [])):
            self.characteristics.append(HIDCharacteristic(bus, i, self, char_cfg))

    def get_property_map(self):
        return {
            'UUID': dbus.String(self.uuid),
            'Primary': dbus.Boolean(self.primary),
            'Includes': dbus.Array(self.includes, signature='o'),
        }

    def get_managed_object(self):
        obj = super().get_managed_object()
        for char in self.characteristics:
            obj.update(char.get_managed_object())
        return obj


class HIDApplication(dbus.service.Object):
    def __init__(self, bus, services, path=HID_APP_PATH):
        self.path = path
        self.services = services
        super().__init__(bus, self.path)
        logger.debug("HIDApplication initialized at %s with %d services", self.path, len(self.services))

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", in_signature='', out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        # Build strict a{oa{sa{sv}}} with dbus types
        response = {}
        for svc in self.services:
            # Each get_managed_object returns a dict keyed by dbus.ObjectPath
            response.update(svc.get_managed_object())
            
        logger.debug("GetManagedObjects called, returning %s", len(response))
        return response


def load_yaml_config(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)