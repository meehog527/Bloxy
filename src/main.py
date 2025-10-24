import asyncio
import logging
import sys
from bluetooth_setup import (
    create_peripheral,
    power_on_bluetooth,
    unblock_bluetooth,
    enable_pairing_and_discovery,
    auto_trust_on_connect
)
from input_handler import keyboard_loop, mouse_loop
from input_devices import autodetect_inputs

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("hid-proxy")

async def main_async():
    keyboard_event, mouse_event = autodetect_inputs()
    if not keyboard_event or not mouse_event:
        logger.error("Keyboard/mouse not detected.")
        sys.exit(1)

    # Setup Bluetooth
    unblock_bluetooth()
    power_on_bluetooth()
    enable_pairing_and_discovery()
    ble = create_peripheral()
    auto_trust_on_connect()


    # Run BLE publish inside the event loop
    def publish_ble():
        ble.publish()
        logger.debug("BLE published")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, publish_ble)

    # Start input loops
    asyncio.create_task(keyboard_loop(keyboard_event, ble))
    logger.debug("Keyboard loop started")
    asyncio.create_task(mouse_loop(mouse_event, ble))
    logger.debug("Mouse loop started")

    # Keep the loop alive
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Shutting down...")
        # If your BLE object has a stop or cleanup method, call it here
        try:
            ble.stop()
            logger.info("Stopped advertising")
        except AttributeError:
            logger.warning("BLE object has no stop() method")

if __name__ == "__main__":
    try:
       asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting...")
        # Optional: cancel all tasks
        for task in asyncio.all_tasks():
            task.cancel()
