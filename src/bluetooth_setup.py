from bluezero import peripheral, adapter
from config import *
from report_map import REPORT_MAP
from logger import get_logger
import subprocess
import time

LOCAL_NAME = "Bloxy"

logger = get_logger("bluetooth_setup")

def get_adapter_address():
    ad = adapter.Adapter()
    return ad.address

def create_peripheral():
    logger.debug("Creating Bluetooth peripheral...")
    ble = peripheral.Peripheral(adapter_address=get_adapter_address(), local_name=LOCAL_NAME, appearance=961)
    ble.add_service(1, UUID_HID_SERVICE, primary=True)
    ble.add_characteristic(1, 1, UUID_HID_INFORMATION, bytes([0x11, 0x01, 0x00, 0x02]), False, ['read'])
    ble.add_characteristic(1, 2, UUID_HID_REPORT_MAP, REPORT_MAP, False, ['read'])
    ble.add_characteristic(1, 3, UUID_HID_PROTOCOL_MODE, bytes([0x01]), False, ['read', 'write-without-response'])
    ble.add_characteristic(1, 4, UUID_HID_CONTROL_POINT, b'\x00', False, ['write-without-response'])
    ble.add_characteristic(1, 5, UUID_REPORT, bytes([0x01] + [0x00]*8), True, ['read', 'notify'])  # Keyboard
    ble.add_characteristic(1, 6, UUID_REPORT, bytes([0x02, 0x00, 0x00, 0x00]), True, ['read', 'notify'])  # Mouse
    ble.add_descriptor(1, 5, '2908', bytes([0x01, 0x01]))
    ble.add_descriptor(1, 6, '2908', bytes([0x02, 0x01]))
    return ble

def power_on_bluetooth():
    logger.debug("Ensuring Bluetooth is powered on...")
    time.sleep(1.5)  # Give BlueZ time to settle
    
    try:
        subprocess.run(["bluetoothctl", "power", "on"], check=True)
        logger.debug("Bluetooth powered on.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to power on Bluetooth: {e}")
        raise

def unblock_bluetooth():
    try:
        # Check rfkill status
        result = subprocess.run(['rfkill', 'list', 'bluetooth'], capture_output=True, text=True)
        if 'Soft blocked: yes' in result.stdout:
            logger.debug("Bluetooth is soft blocked. Unblocking...")
            subprocess.run(['sudo', 'rfkill', 'unblock', 'bluetooth'], check=True)
            logger.debug("Bluetooth unblocked.")
        else:
            logger.debug("Bluetooth is already unblocked.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running rfkill: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        
def enable_pairing_and_discovery():
    logger.debug("Enabling Bluetooth discoverable and pairable mode...")
    try:
        subprocess.run(
            ['bluetoothctl'],
            input='\n'.join([
                'discoverable on',
                'pairable on',
                'agent NoInputNoOutput',
                'default-agent'
            ]),
            text=True,
            check=True
        )
        logger.debug("Bluetooth is now discoverable and pairable.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to enable pairing/discovery: {e}")
        raise




