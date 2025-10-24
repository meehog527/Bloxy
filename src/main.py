import asyncio
import logging
import sys
from bluetooth_setup import create_peripheral, power_on_bluetooth, unblock_bluetooth, enable_pairing_and_discovery
from input_handler import keyboard_loop, mouse_loop
from input_devices import autodetect_inputs

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("hid-proxy")

def main():
    keyboard_event, mouse_event = autodetect_inputs()
    if not keyboard_event or not mouse_event:
        logger.error("Keyboard/mouse not detected.")
        sys.exit(1)

    #setup bluetooth
    unblock_bluetooth()
    power_on_bluetooth()
    enable_pairing_and_discovery()
    ble = create_peripheral()
    ble.publish()
    logger.debug("BLE published")

    loop = asyncio.get_event_loop()
    loop.create_task(keyboard_loop(keyboard_event, ble))
    logger.debug("Keyboard loop started")
    loop.create_task(mouse_loop(mouse_event, ble))
    logger.debug("Mouse loop started")
    
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        ble.unpublish()
        logger.info("Stopped advertising")

if __name__ == "__main__":
    main()