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
    """
    Base GATT object that provides org.freedesktop.DBus.Properties helpers
    and a helper to produce its managed object entry.
    """
    dbus_interface = None  # override in subclasses

    def __init__(self, bus, path):
        super().__init__(bus, path)

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

    # Set is optional for GATT; only implement if you need writable properties
    # @dbus.service.method(DBUS_PROP_IFACE, in_signature='ssv', out_signature='')
    # def Set(self, interface, prop, value):
    #     pass

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
        # store as bytes
        self.value = [dbus.Byte(int(v) & 0xFF) for v in raw_val]
        self.path = f'{char.path}/desc{index}'
        super().__init__(bus, self.path)

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
        # CCCD handling (0x2902) toggles notify/indicate
        if self.uuid.lower() == '00002902-0000-1000-8000-00805f9b34fb':
            # value is array of bytes; 0x01 for notify, 0x02 for indicate (bitmask)
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
        self.path = f'{service.path}/char{index}'
        super().__init__(bus, self.path)

        for i, desc_cfg in enumerate(config.get('descriptors', [])):
            self.descriptors.append(HIDDescriptor(bus, i, self, desc_cfg))

    def get_property_map(self):
        return {
            'UUID': dbus.String(self.uuid),
            'Service': dbus.ObjectPath(self.service.path),
            'Flags': dbus.Array([dbus.String(f) for f in self.flags], signature='s'),
            # Value and Notifying are valid properties for BlueZ characteristics
            'Value': dbus.Array(self.value, signature='y'),
            'Notifying': dbus.Boolean(self.notifying),
        }

    def get_managed_object(self):
        obj = super().get_managed_object()
        # Do NOT add a nonstandard "Descriptors" property.
        # BlueZ discovers descriptors by GetManagedObjects tree entries.
        for desc in self.descriptors:
            obj.update(desc.get_managed_object())
        return obj

    def set_notifying(self, enabled: bool):
        if self.notifying != bool(enabled):
            self.notifying = bool(enabled)
            # Emit PropertiesChanged for Notifying
            try:
                self.PropertiesChanged(
                    self.dbus_interface,
                    {'Notifying': dbus.Boolean(self.notifying)},
                    []
                )
            except Exception as e:
                logger.warning(f"Failed to emit PropertiesChanged(Notifying) for {self.name}: {e}")

    def update_value(self, new_value_bytes):
        # Update internal value and emit PropertiesChanged to notify subscribers
        self.value = [dbus.Byte(int(v) & 0xFF) for v in new_value_bytes]
        try:
            self.PropertiesChanged(
                self.dbus_interface,
                {'Value': dbus.Array(self.value, signature='y')},
                []
            )
        # If host isn't subscribed, BlueZ will still accept PropertiesChanged; it just won't deliver a notification.
        except Exception as e:
            logger.warning(f"Failed to emit PropertiesChanged(Value) for {self.name}: {e}")

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        # For HID output/feature reports, you may want to handle writes here.
        self.value = [dbus.Byte(int(b) & 0xFF) for b in value]
        # Optionally emit PropertiesChanged so the UI reflects the write
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

    @dbus.service.signal('org.freedesktop.DBus.Properties', signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class HIDService(GattObject):
    dbus_interface = GATT_SERVICE_IFACE

    def __init__(self, bus, index, config):
        self.uuid = config['uuid']
        # Respect type if present; default to primary
        self.primary = (config.get('type', 'primary') == 'primary')
        self.characteristics = []
        # Includes should be object paths; if you don't use them, leave empty
        includes_cfg = config.get('includes', [])
        self.includes = [dbus.ObjectPath(p) for p in includes_cfg] if includes_cfg else []
        self.path = f'/org/bluez/hid/service{index}'
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
    """
    Implements org.freedesktop.DBus.ObjectManager for the HID GATT application.
    Register this object's path with org.bluez.GattManager1.RegisterApplication.
    """
    def __init__(self, bus, services, path='/org/bluez/hid'):
        self.path = path
        self.services = services
        super().__init__(bus, self.path)
        logger.debug("HIDApplication initialized at %s with %d services", self.path, len(self.services))

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", in_signature='', out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        for svc in self.services:
            response.update(svc.get_managed_object())
        return response


def load_yaml_config(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)