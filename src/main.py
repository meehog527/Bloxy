import asyncio
import logging
import sys
from bluetooth_setup import create_peripheral, power_on_bluetooth
from input_handler import keyboard_loop, mouse_loop
from input_devices import autodetect_inputs

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("hid-proxy")

def main():
    keyboard_event, mouse_event = autodetect_inputs()
    if not keyboard_event or not mouse_event:
        logger.error("Keyboard/mouse not detected.")
        sys.exit(1)

    power_on_bluetooth()
    ble = create_peripheral()
    ble.publish()

    loop = asyncio.get_event_loop()
    loop.create_task(keyboard_loop(keyboard_event, ble))
    loop.create_task(mouse_loop(mouse_event, ble))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        ble.unpublish()
        logger.info("Stopped advertising")

if __name__ == "__main__":
    main()