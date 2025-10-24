from bluezero import peripheral
from config import *
from report_map import REPORT_MAP

LOCAL_NAME = "Bloxy"

def create_peripheral():
    ble = peripheral.Peripheral(adapter_addr=None, local_name=LOCAL_NAME, appearance=961)
    ble.add_service(1, UUID_HID_SERVICE, primary=True)
    ble.add_characteristic(1, 1, UUID_HID_INFORMATION, bytes([0x11, 0x01, 0x00, 0x02]), ['read'])
    ble.add_characteristic(1, 2, UUID_HID_REPORT_MAP, REPORT_MAP, ['read'])
    ble.add_characteristic(1, 3, UUID_HID_PROTOCOL_MODE, bytes([0x01]), ['read', 'write-without-response'])
    ble.add_characteristic(1, 4, UUID_HID_CONTROL_POINT, b'\x00', ['write-without-response'])
    ble.add_characteristic(1, 5, UUID_REPORT, bytes([0x01] + [0x00]*8), ['read', 'notify'])
    ble.add_characteristic(1, 6, UUID_REPORT, bytes([0x02, 0x00, 0x00, 0x00]), ['read', 'notify'])
    return ble