#check_hid_setup.py

import subprocess
import logging
import time
import os

try:
    from pydbus import SystemBus
except ImportError:
    print("❌ pydbus is not installed. Run: sudo apt install python3-pydbus")
    exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger("check_hid_setup")

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip(), result.returncode

def check_bluez_service():
    logging.info("🔍 Checking if BlueZ service is running...")
    output, _ = run_command(['systemctl', 'is-active', 'bluetooth'])
    if output == 'active':
        logging.info("✅ BlueZ service is active.")
        return True
    else:
        logging.warning("❌ BlueZ is not active. Attempting restart...")
        _, _ = run_command(['sudo', 'systemctl', 'restart', 'bluetooth'])
        time.sleep(2)
        output, _ = run_command(['systemctl', 'is-active', 'bluetooth'])
        if output == 'active':
            logging.info("✅ BlueZ restarted successfully.")
            return True
        else:
            logging.error("❌ Failed to restart BlueZ.")
            return False

def check_gatt_registration():
    logging.info("🔍 Checking GATT registration via D-Bus...")
    try:
        bus = SystemBus()
        bluez = bus.get("org.bluez", "/")
        managed_objects = bluez.GetManagedObjects()
        found = False
        for path, interfaces in managed_objects.items():
            if "org.bluez.GattService1" in interfaces:
                logging.info(f"✅ GATT Service found at {path}")
                found = True
            if "org.bluez.GattCharacteristic1" in interfaces:
                logging.info(f"  ➤ Characteristic at {path}")
            if "org.bluez.GattDescriptor1" in interfaces:
                logging.info(f"    ➤ Descriptor at {path}")
        if not found:
            logging.warning("❌ No GATT services found.")
        return found
    except Exception as e:
        logging.error(f"❌ D-Bus error: {e}")
        return False

def check_advertising_status():
    logging.info("🔍 Checking advertising status via bluetoothctl...")
    output, _ = run_command(['bluetoothctl', 'show'])

    is_powered = "Powered: yes" in output
    is_advertising = "AdvertisingFlags" in output or "Discoverable: yes" in output

    if is_powered and is_advertising:
        logging.info("✅ Device is powered and advertising/discoverable.")
        return True
    else:
        logging.warning("❌ Device is not advertising. Attempting to enable advertising...")

        # Try enabling advertising via bluetoothctl
        try:
            # Start interactive bluetoothctl session
            process = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            # Send commands to power on, make discoverable, and advertise
            commands = [
                'power on\n',
                'discoverable on\n',
                'pairable on\n',
                'advertise on\n',
                'exit\n'
            ]
            process.communicate(''.join(commands))
            time.sleep(2)

            # Re-check status
            output, _ = run_command(['bluetoothctl', 'show'])
            if "AdvertisingFlags" in output or "Discoverable: yes" in output:
                logging.info("✅ Advertising successfully enabled.")
                return True
            else:
                logging.error("❌ Failed to enable advertising.")
                return False
        except Exception as e:
            logging.error(f"❌ Error enabling advertising: {e}")
            return False

def inspect_hid_daemon_logs(service_name='hid-daemon'):
    logging.info(f"🔍 Inspecting logs for {service_name}...")
    output, code = run_command(['journalctl', '-u', service_name, '--no-pager', '-n', '20'])
    if code == 0:
        logging.info(f"📄 Recent logs for {service_name}:\n{output}")
        return True
    else:
        logging.warning(f"❌ Could not retrieve logs for {service_name}.")
        return False

def restart_hid_daemon():
    logging.info("🔄 Restarting hid-daemon service...")
    _, _ = run_command(['sudo', 'systemctl', 'restart', 'hid-daemon'])
    time.sleep(2)
    output, _ = run_command(['systemctl', 'is-active', 'hid-daemon'])
    if output == 'active':
        logging.info("✅ hid-daemon restarted successfully.")
    else:
        logging.error("❌ Failed to restart hid-daemon.")

def main():
    logging.info("🚀 Starting HID GATT system check...\n")

    bluez_ok = check_bluez_service()
    gatt_ok = check_gatt_registration()
    adv_ok = check_advertising_status()
    logs_ok = inspect_hid_daemon_logs()

    if not gatt_ok:
        logging.warning("⚠️ GATT not registered. Attempting to restart hid-daemon...")
        restart_hid_daemon()
        logging.info("🔁 Rechecking GATT registration...")
        time.sleep(3)
        check_gatt_registration()

    logging.info("\n📋 Summary:")
    logging.info(f"BlueZ running: {'✅' if bluez_ok else '❌'}")
    logging.info(f"GATT registered: {'✅' if gatt_ok else '❌'}")
    logging.info(f"Advertising: {'✅' if adv_ok else '❌'}")
    logging.info(f"HID daemon logs: {'✅' if logs_ok else '❌'}")

def validate_input_device(path, name):
    if not os.path.exists(path):
        logger.error("❌ %s device path does not exist: %s", name, path)
        return False
    if not os.access(path, os.R_OK):
        logger.error("❌ %s device path is not readable: %s", name, path)
        return False
    logger.info("✅ %s device is accessible: %s", name, path)
    return True

if __name__ == "__main__":
    main()