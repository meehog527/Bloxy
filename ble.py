import dbus
import dbus.mainloop.glib
from gi.repository import GLib

BLUEZ_SERVICE_NAME = 'org.bluez'
ADAPTER_PATH = '/org/bluez/hci0'
ADAPTER_IFACE = 'org.bluez.Adapter1'

GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'

DBUS_PROPS_IFACE = 'org.freedesktop.DBus.Properties'
DBUS_INTRO_IFACE = 'org.freedesktop.DBus.Introspectable'

APP_BASE = '/org/bluez/hidapp'
APP_SERVICE_BASE = APP_BASE + 'service'
APP_ADVERT_BASE = APP_BASE + 'advertisement'

class BLEPeripheral:
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.adapter = self.bus.get_object(BLUEZ_SERVICE_NAME, ADAPTER_PATH)
        self.adapter_props = dbus.Interface(self.adapter, DBUS_PROPS_IFACE)

    def setup_adapter(self):
        self.adapter_props.Set(ADAPTER_IFACE, 'Powered', dbus.Boolean(1))
        self.adapter_props.Set(ADAPTER_IFACE, 'Discoverable', dbus.Boolean(1))
        print("✅ Adapter powered and discoverable")
    
    def register_gatt(self):
        service = HIDService(self.bus, 0)
        gatt_manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, ADAPTER_PATH),
            GATT_MANAGER_IFACE
        )
        gatt_manager.RegisterApplication(service, {},
            reply_handler=lambda: print("✅ GATT service registered"),
            error_handler=lambda e: print(f"❌ GATT registration failed: {e}")
        )
    
    def advertise(self):
        ad = Advertisement(self.bus)
        ad_manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, ADAPTER_PATH),
            LE_ADVERTISING_MANAGER_IFACE
        )
        ad_manager.RegisterAdvertisement(ad, {},
            reply_handler=lambda: print("✅ Advertisement registered"),
            error_handler=lambda e: print(f"❌ Advertisement failed: {e}")
        )

    def run(self):
        self.setup_adapter()
        self.register_gatt()
        self.advertise()
        print("🚀 BLE HID Keyboard is running. Waiting for connections...")
        GLib.MainLoop().run()



import dbus.service

class HIDService(dbus.service.Object):
    def __init__(self, bus, index):
        self.path = APP_SERVICE_BASE + str(index)
        self.bus = bus
        dbus.service.Object.__init__(self, bus, self.path)

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        if prop == 'UUID':
            return dbus.String('1812')  # HID Service UUID
        elif prop == 'Primary':
            return dbus.Boolean(True)
        elif prop == 'Characteristics':
            return dbus.Array([], signature='o')
        raise dbus.exceptions.DBusException('Unknown property')

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return {
            'UUID': dbus.String('1812'),
            'Primary': dbus.Boolean(True),
            'Characteristics': dbus.Array([], signature='o')
        }

    @dbus.service.method(DBUS_INTRO_IFACE, in_signature='', out_signature='s')
    def Introspect(self):
        return ''

class Advertisement(dbus.service.Object):
    def __init__(self, bus):
        dbus.service.Object.__init__(self, bus, APP_ADVERT_BASE)

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        if prop == 'Type':
            return dbus.String('peripheral')
        elif prop == 'ServiceUUIDs':
            return dbus.Array(['1812'], signature='s')  # HID UUID
        raise dbus.exceptions.DBusException('Unknown property')

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return {
            'Type': dbus.String('peripheral'),
            'ServiceUUIDs': dbus.Array(['1812'], signature='s')
        }

    @dbus.service.method(DBUS_INTRO_IFACE, in_signature='', out_signature='s')
    def Introspect(self):
        return ''

if __name__ == '__main__':
    peripheral = BLEPeripheral()
    peripheral.run()
    
    