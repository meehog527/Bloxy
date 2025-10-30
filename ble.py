import asyncio
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, dbus_property
from dbus_next import Variant
from dbus_next.service import PropertyAccess

# Constants
BLUEZ_SERVICE_NAME = 'org.bluez'
ADAPTER_PATH = '/org/bluez/hci0'
APP_BASE = '/org/bluez/hidble/'
APP_PATH = APP_BASE + '/app'
APP_SERVICE_PATH = APP_BASE + '/service'
SERVICE_IFACE = 'org.bluez.GattService1'
APP_IFACE = 'org.bluez.GattApplication1'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
HID_SERVICE_UUID = '1812'  # HID Service UUID

class Application(ServiceInterface):
    def __init__(self):
        super().__init__(APP_IFACE)

class HIDService(ServiceInterface):
    def __init__(self, index):
        super().__init__(SERVICE_IFACE)
        self.path = f'{APP_SERVICE_PATH}{index}'
        self.uuid = HID_SERVICE_UUID
        self.primary = True

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> str:
        return self.uuid

    @dbus_property(access=PropertyAccess.READ)
    def Primary(self) -> bool:
        return self.primary

    @dbus_property(access=PropertyAccess.READ)
    def Characteristics(self) -> list:
        return []

async def main():
    bus = await MessageBus(system=True).connect()

    # Register GATT application
    app = Application()
    bus.export(APP_PATH, app)

    # Register HID service
    hid_service = HIDService(0)
    bus.export(hid_service.path, hid_service)

    # Get GattManager1 interface
    obj = await bus.introspect(BLUEZ_SERVICE_NAME, ADAPTER_PATH)
    gatt_manager = bus.get_proxy_object(BLUEZ_SERVICE_NAME, ADAPTER_PATH, obj)
    gatt_iface = gatt_manager.get_interface(GATT_MANAGER_IFACE)

    # Register application
    await gatt_iface.call_register_application(APP_PATH, {})

    print("✅ HID BLE keyboard service registered. Waiting for connection...")
    await asyncio.get_event_loop().create_future()

if __name__ == '__main__':
    asyncio.run(main())