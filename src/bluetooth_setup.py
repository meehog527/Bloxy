from bluezero import peripheral, adapter
from bluezero.device import Device
from config import (
    UUID_HID_SERVICE,
    UUID_HID_INFORMATION,
    UUID_HID_REPORT_MAP,
    UUID_HID_PROTOCOL_MODE,
    UUID_HID_CONTROL_POINT,
    UUID_REPORT,
    UUID_BATTERY_SERVICE,
    UUID_BATTERY_LEVEL,
    UUID_DEVICE_INFORMATION_SERVICE,
    UUID_MANUFACTURER_NAME,
    UUID_PNP_ID,
    UUID_SYSTEM_ID,
    UUID_SERIAL_NUMBER,
    UUID_FIRMWARE_REV,
    UUID_HARDWARE_REV,
    UUID_SOFTWARE_REV
)
from report_map import REPORT_MAP
from logger import get_logger
from pydbus import SystemBus
from gi.repository import GLib
import subprocess
import time
import threading
import asyncio

LOCAL_NAME = "Bloxy"

logger = get_logger("bluetooth_setup")

def get_adapter_address():
    ad = adapter.Adapter()
    return ad.address

def create_peripheral():
    logger.debug("Creating Bluetooth peripheral (Windows-optimized, full HID profile)...")

    # Create the BLE peripheral with HID appearance (963 = Keyboard + Mouse)
    ble = peripheral.Peripheral(
        adapter_address=get_adapter_address(),
        local_name=LOCAL_NAME,
        appearance=963
    )

    # -------------------------
    # HID Service (0x1812)
    # -------------------------
    ble.add_service(1, UUID_HID_SERVICE, primary=True)

    # HID Information characteristic (version, country code, flags)
    ble.add_characteristic(1, 1, UUID_HID_INFORMATION,
                           bytes([0x11, 0x01, 0x00, 0x02]),
                           False, ['read'])

    # HID Report Map characteristic (defines HID structure)
    ble.add_characteristic(1, 2, UUID_HID_REPORT_MAP,
                           REPORT_MAP,
                           False, ['read'])

    # Protocol Mode characteristic (Report Mode = 1)
    ble.add_characteristic(1, 3, UUID_HID_PROTOCOL_MODE,
                           bytes([0x01]),
                           False, ['read', 'write-without-response'])

    # HID Control Point characteristic (used to suspend/resume)
    ble.add_characteristic(1, 4, UUID_HID_CONTROL_POINT,
                           b'\x00',
                           False, ['write-without-response'])

    # Keyboard Input Report (Report ID 1)
    ble.add_characteristic(1, 5, UUID_REPORT,
                           bytes([0x01] + [0x00]*8),
                           True, ['read', 'notify'])
    ble.add_descriptor(1, 5, 1, '2908', bytes([0x01, 0x01]), ['read'])  # Report Reference

    # Mouse Input Report (Report ID 2)
    ble.add_characteristic(1, 6, UUID_REPORT,
                           bytes([0x02, 0x00, 0x00, 0x00, 0x00]),
                           True, ['read', 'notify'])
    ble.add_descriptor(1, 6, 1, '2908', bytes([0x02, 0x01]), ['read'])  # Report Reference

    # Keyboard Output Report (LEDs)
    ble.add_characteristic(1, 7, UUID_REPORT,
                           bytes([0x01, 0x00]),
                           True, ['read', 'write', 'write-without-response'])
    ble.add_descriptor(1, 7, 1, '2908', bytes([0x01, 0x02]), ['read'])  # Report Reference

    # Boot Keyboard Input Report
    ble.add_characteristic(1, 8, '00002a22-0000-1000-8000-00805f9b34fb',
                           bytes([0x00]*8),
                           True, ['read', 'notify'])

    # Boot Keyboard Output Report
    ble.add_characteristic(1, 9, '00002a32-0000-1000-8000-00805f9b34fb',
                           b'\x00',
                           True, ['read', 'write', 'write-without-response'])

    # Boot Mouse Input Report
    ble.add_characteristic(1, 10, '00002a33-0000-1000-8000-00805f9b34fb',
                           bytes([0x00, 0x00, 0x00]),
                           True, ['read', 'notify'])

    # Feature Report stub (Report ID 3)
    ble.add_characteristic(1, 11, UUID_REPORT,
                           bytes([0x03, 0x00]),
                           True, ['read'])
    ble.add_descriptor(1, 11, 1, '2908', bytes([0x03, 0x03]), ['read'])  # Report Reference

    # External Report Reference Descriptor linking to Battery Service
    ble.add_descriptor(1, 2, 1, '2907',
                       bytes([0x0F, 0x18]),  # UUID 0x180F (Battery Service)
                       ['read'])

    # -------------------------
    # Battery Service (0x180F)
    # -------------------------
    ble.add_service(2, UUID_BATTERY_SERVICE, primary=True)
    ble.add_characteristic(2, 1, UUID_BATTERY_LEVEL,
                           bytes([100]), True, ['read', 'notify'])

    # Presentation Format descriptor (0x2904) for Battery Level
    # Format=uint8 (0x04), Exponent=0, Unit=percentage (0x27AD)   
    ble.add_descriptor(2, 1, 1, '2904', 'Format: uint8, Unit: %'.encode('utf-8'), ['read'])

    # -------------------------
    # Device Information Service (0x180A)
    # -------------------------
    ble.add_service(3, UUID_DEVICE_INFORMATION_SERVICE, primary=True)
    ble.add_characteristic(3, 1, UUID_MANUFACTURER_NAME,
                           b'Bloxy', False, ['read'])
    ble.add_characteristic(3, 2, UUID_PNP_ID,
                           bytes([0x01, 0x5D, 0x00, 0x12, 0x34, 0x00, 0x01]),
                           False, ['read'])
    ble.add_characteristic(3, 3, UUID_SYSTEM_ID,
                           bytes([0x12, 0x34, 0x56, 0xFF, 0xFE, 0x9A, 0xBC, 0xDE]),
                           False, ['read'])
    ble.add_characteristic(3, 4, UUID_SERIAL_NUMBER,
                           b'SN1234567890', False, ['read'])
    ble.add_characteristic(3, 5, UUID_FIRMWARE_REV,
                           b'1.0.0', False, ['read'])
    ble.add_characteristic(3, 6, UUID_HARDWARE_REV,
                           b'1.0', False, ['read'])
    ble.add_characteristic(3, 7, UUID_SOFTWARE_REV,
                           b'1.0.0', False, ['read'])
      
    # Register connection lifecycle callbacks
    ble.on_connect = on_connect
    ble.on_disconnect = on_disconnect

    return ble

def on_connect(device):
    try:
        logger.info(f"🔗 Central device connected: {device.address}")

        # Trust the device if not already trusted
        if not device.trusted:
            try:
                device.trusted = True
                logger.info(f"✅ Trusted device: {device.address}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to trust device: {e}")
        else:
            logger.info(f"✅ Device already trusted: {device.address}")

        # Pair the device if not already paired
        if not device.paired:
            try:
                device.pair()
                logger.info(f"✅ Paired device: {device.address}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to pair device: {e}")
        else:
            logger.info(f"✅ Device already paired: {device.address}")

    except Exception as e:
        logger.warning(f"🔗 Unhandled exception: {e}")

def on_disconnect(device):
    try:
        logger.warning(f"Central device disconnected: {device.address}")
    except AttributeError:
        logger.warning(f"Central device disconnected: {device}")

def monitor_devices():
    for dev in Device.available():
        try:
            logger.info(f"Monitoring device: {dev.address}")
            logger.info(f"  Connected={dev.connected}, Paired={dev.paired}, ServicesResolved={dev.services_resolved}")
            logger.info(f"  RSSI={getattr(dev, 'RSSI', 'n/a')}, MTU={getattr(dev, 'MTU', 'n/a')}")
        except Exception as e:
            logger.warning(f"Failed to read device state for {dev.address}: {e}")

        def prop_changed(iface, changed, invalidated, path=dev.remote_device_path):
            for key, value in changed.items():
                logger.info(f"{dev.address} {key} changed to {value}")

        dev.on_properties_changed = prop_changed

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
                'agent on',
                'default-agent',
                'discoverable on',
                'pairable on'
            ]),
            text=True,
            check=True
        )
        logger.debug("Bluetooth is now discoverable and pairable.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to enable pairing/discovery: {e}")
        raise

def trust_connected_devices():
    logger.debug("Checking for connected devices to trust...")
    bus = SystemBus()
    mngr = bus.get('org.bluez', '/')
    objects = mngr.GetManagedObjects()

    for path, interfaces in objects.items():
        if 'org.bluez.Device1' in interfaces:
            device = interfaces['org.bluez.Device1']
            if device.get('Connected', False):
                mac = path.split('/')[-1].replace('dev_', '').replace('_', ':')
                try:
                    dev_obj = bus.get('org.bluez', path)
                    dev_obj.Trusted = True
                    logger.info(f"Trusted device: {mac}")
                except Exception as e:
                    logger.warning(f"Failed to trust {mac}: {e}")

async def wait_for_ble_advertising():
    """Wait until bluetoothctl reports that BLE advertising is active."""
    while True:
        try:
            result = subprocess.run(
                ["bluetoothctl", "show"],
                capture_output=True,
                text=True,
                check=True
            )
            output = result.stdout
            for line in output.splitlines():
                if "ActiveInstances:" in line:
                    value = line.strip().split(":")[1].strip().split(" ")[0]
                    if value != "0x00":
                        logger.info("✅ BLE advertising is active.")
                        return
                    else:
                        logger.debug("Waiting for BLE advertising to become active...")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Error checking BLE advertising status: {e}")
        await asyncio.sleep(1)

