import asyncio
import logging
import signal
import sys
from bluetooth_setup import (
    create_peripheral,
    power_on_bluetooth,
    unblock_bluetooth,
    enable_pairing_and_discovery,
    monitor_devices
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
    monitor_devices()
    #auto_trust_on_connect()


    # Run BLE publish inside the event loop
    def publish_ble():
        ble.publish()
        logger.debug("BLE published")

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, shutdown)
    
    # Run BLE publishing in a background thread
    ble_task = loop.run_in_executor(None, publish_ble)

    try:
        await ble_task
    except asyncio.CancelledError:
        print("BLE task was cancelled.")
    finally:
        print("Cleaning up BLE resources...")


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

def shutdown():
    print("Received shutdown signal. Cancelling tasks...")
    for task in asyncio.all_tasks():
        task.cancel()


if __name__ == "__main__":
    try:
        # Register signal handler for graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown)

        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("KeyboardInterrupt received. Exiting cleanly.")

