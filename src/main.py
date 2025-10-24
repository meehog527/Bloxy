import asyncio
import logging
import signal
import sys
import threading
import time
import subprocess
from bluetooth_setup import (
    create_peripheral,
    power_on_bluetooth,
    unblock_bluetooth,
    enable_pairing_and_discovery,
    monitor_devices,
    wait_for_ble_advertising
)
from input_handler import keyboard_loop, mouse_loop
from input_devices import autodetect_inputs

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("hid-proxy")

# Global BLE object
ble = None

async def main_async():
    global ble

    keyboard_event, mouse_event = autodetect_inputs()
    if not keyboard_event or not mouse_event:
        logger.error("Keyboard/mouse not detected.")
        sys.exit(1) 
    
    monitor_devices()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, shutdown)
    
    await wait_for_ble_advertising()

    # Start input loops
    asyncio.create_task(keyboard_loop(keyboard_event, ble))
    logger.debug("Keyboard loop started")
    asyncio.create_task(mouse_loop(mouse_event, ble))
    logger.debug("Mouse loop started")

    # Keep the loop alive
    
    try:
        await asyncio.Event().wait()  # Wait forever until cancelled
    except asyncio.CancelledError:
        logger.info("Shutdown requested.")
    finally:
        try:
            ble.unpublish()
            logger.info("Stopped advertising")
        except Exception as e:
            logger.warning(f"Failed to stop BLE advertising: {e}")
        sys.exit(0)

def shutdown():
    print("Received shutdown signal. Cancelling tasks...")
    for task in asyncio.all_tasks():
        task.cancel()

def start_ble():
    unblock_bluetooth()
    power_on_bluetooth()
    enable_pairing_and_discovery()
    ble = create_peripheral()
    print(dir(ble))
    ble.publish()

if __name__ == "__main__":
    try:
        ble_thread = threading.Thread(target=start_ble, daemon=True)
        ble_thread.start()
        logger.debug("BLE Advertisment Loop Started")

        # Register signal handler for graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown)

        asyncio.run(main_async())
    except asyncio.CancelledError:
        print("KeyboardInterrupt received. Exiting cleanly.")
        sys.exit(0)

