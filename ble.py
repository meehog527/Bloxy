import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

BLUEZ_SERVICE_NAME = 'org.bluez'
ADAPTER_PATH = '/org/bluez/hci0'
ADAPTER_IFACE = 'org.bluez.Adapter1'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_PROPS_IFACE = 'org.freedesktop.DBus.Properties'
DBUS_INTRO_IFACE = 'org.freedesktop.DBus.Introspectable'
GATT_CHAR_IFACE = 'org.bluez.GattCharacteristic1'

APP_BASE = '/org/bluez/hidapp'
APP_SERVICE_BASE = APP_BASE + '/service'
APP_ADVERT_BASE = APP_BASE + '/advertisement'

KEY_A_REPORT = [0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]
KEY_RELEASE = [0x00] * 8

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
        app = GattApplication(self.bus, service)
        gatt_manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, ADAPTER_PATH),
            GATT_MANAGER_IFACE
        )
        gatt_manager.RegisterApplication(app.path, {},
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

class HIDService(dbus.service.Object):
    def __init__(self, bus, index):
        self.path = APP_SERVICE_BASE + str(index)
        self.bus = bus
        dbus.service.Object.__init__(self, bus, self.path)
        self.input_char = InputReportCharacteristic(bus, 0, self.path)

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        if prop == 'UUID':
            return dbus.String('1812')
        elif prop == 'Primary':
            return dbus.Boolean(True)
        elif prop == 'Characteristics':
            return dbus.Array([self.input_char.path], signature='o')
        raise dbus.exceptions.DBusException('Unknown property')

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return {
            'UUID': dbus.String('1812'),
            'Primary': dbus.Boolean(True),
            'Characteristics': dbus.Array([self.input_char.path], signature='o')
        }

    @dbus.service.method(DBUS_INTRO_IFACE, in_signature='', out_signature='s')
    def Introspect(self):
        return f'''
        <node>
            <node name="char0" />
        </node>
        '''

class InputReportCharacteristic(dbus.service.Object):
    def __init__(self, bus, index, service_path):
        self.path = service_path + f'/char{index}'
        self.bus = bus
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        if prop == 'UUID':
            return dbus.String('2A4D')
        elif prop == 'Flags':
            return dbus.Array(['notify'], signature='s')
        raise dbus.exceptions.DBusException('Unknown property')

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return {
            'UUID': dbus.String('2A4D'),
            'Flags': dbus.Array(['notify'], signature='s')
        }

    @dbus.service.method(GATT_CHAR_IFACE, in_signature='', out_signature='')
    def StartNotify(self):
        self.notifying = True
        print("🔔 Notifications started")

    @dbus.service.method(GATT_CHAR_IFACE, in_signature='', out_signature='')
    def StopNotify(self):
        self.notifying = False
        print("🔕 Notifications stopped")

    def send_keypress(self, report_bytes):
        if not self.notifying:
            print("⚠️ Not notifying, can't send keypress")
            return
        value = dbus.Array([dbus.Byte(b) for b in report_bytes], signature='y')
        self.PropertiesChanged(GATT_CHAR_IFACE, {'Value': value}, [])

    @dbus.service.signal(DBUS_PROPS_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

class GattApplication(dbus.service.Object):
    def __init__(self, bus, service):
        self.path = APP_BASE
        self.bus = bus
        self.service = service
        dbus.service.Object.__init__(self, bus, self.path)

    @dbus.service.method(DBUS_INTRO_IFACE, in_signature='', out_signature='s')
    def Introspect(self):
        child_name = self.service.path[len(self.path)+1:]
        return f'''
        <node>
            <node name="{child_name}" />
        </node>
        '''

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        raise dbus.exceptions.DBusException('org.freedesktop.DBus.Error.UnknownProperty')

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return {}

class Advertisement(dbus.service.Object):
    def __init__(self, bus):
        dbus.service.Object.__init__(self, bus, APP_ADVERT_BASE)

    @dbus.service.method(DBUS_PROPS_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        if prop == 'Type':
            return dbus.String('peripheral')
        elif prop == 'ServiceUUIDs':
            return dbus.Array(['1812'], signature='s')
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
