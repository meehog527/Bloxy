import dbus
import dbus.service
from gi.repository import GLib

from .dbus_utils import DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE

class HIDDescriptor(dbus.service.Object):
    def __init__(self, bus, index, char, config):
        self.char = char
        self.path = f'{char.path}/desc{index}'
        self.uuid = config['uuid']
        self.flags = config['flags']
        self.value = [dbus.Byte(v) for v in config['value']]
        dbus.service.Object.__init__(self, bus, self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        if prop == 'UUID':
            return self.uuid
        elif prop == 'Characteristic':
            return self.char.path
        elif prop == 'Value':
            return dbus.Array(self.value, signature='y')
        elif prop == 'Flags':
            return dbus.Array(self.flags, signature='s')
        raise NotImplementedError(f'Unknown descriptor property: {prop}')

    @dbus.service.method(GATT_DESC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_DESC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        # CCCD handling: 0x2902
        if self.uuid.lower() == '00002902-0000-1000-8000-00805f9b34fb':
            self.value = value
            enabled = len(value) >= 1 and value[0] == 0x01
            self.char.set_notifying(enabled)
            print(f'CCCD write for {self.char.name}: notifications {"enabled" if enabled else "disabled"}')
        else:
            self.value = value

class HIDCharacteristic(dbus.service.Object):
    def __init__(self, bus, index, service, config):
        self.service = service
        self.path = f'{service.path}/char{index}'
        self.uuid = config['uuid']
        self.flags = config['flags']
        self.value = [dbus.Byte(v) for v in config['value']]
        self.name = config.get('name', self.uuid)
        self.notifying = bool(config.get('notifying', False))
        self.descriptors = []
        dbus.service.Object.__init__(self, bus, self.path)

        for i, desc_cfg in enumerate(config.get('descriptors', [])):
            self.descriptors.append(HIDDescriptor(bus, i, self, desc_cfg))

    def set_notifying(self, enabled: bool):
        self.notifying = enabled

    def update_value(self, new_value_bytes):
        self.value = [dbus.Byte(v) for v in new_value_bytes]
        if self.notifying:
            # BlueZ sends notifications when ReadValue is called by host and Notifying=true,
            # but we can trigger PropertiesChanged for Value if needed.
            try:
                self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': dbus.Array(self.value, signature='y')}, [])
            except Exception:
                pass
        print(f'[{self.name}] value updated: {list(new_value_bytes)}')

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        if prop == 'UUID':
            return self.uuid
        elif prop == 'Service':
            return self.service.path
        elif prop == 'Flags':
            return dbus.Array(self.flags, signature='s')
        elif prop == 'Value':
            return dbus.Array(self.value, signature='y')
        elif prop == 'Notifying':
            return self.notifying
        raise NotImplementedError(f'Unknown characteristic property: {prop}')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        self.value = value
        print(f'[{self.name}] write: {list(value)}')

    @dbus.service.signal('org.freedesktop.DBus.Properties', signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        self.notifying = True
        print(f'[{self.name}] StartNotify')

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self.notifying = False
        print(f'[{self.name}] StopNotify')

class HIDService(dbus.service.Object):
    def __init__(self, bus, index, config):
        self.path = f'/org/bluez/hid/service{index}'
        self.uuid = config['uuid']
        self.primary = True
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

        for i, char_cfg in enumerate(config.get('characteristics', [])):
            self.characteristics.append(HIDCharacteristic(bus, i, self, char_cfg))

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        if prop == 'UUID':
            return self.uuid
        elif prop == 'Primary':
            return self.primary
        raise NotImplementedError(f'Unknown service property: {prop}')
