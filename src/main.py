import asyncio
import logging
import sys
from bluetooth_setup import create_peripheral
from input_handler import keyboard_loop, mouse_loop
from config import KEYBOARD_EVENT, MOUSE_EVENT

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("hid-proxy")

def main():
    ble = create_peripheral()
    ble.publish()
    loop = asyncio.get_event_loop()
    loop.create_task(keyboard_loop(KEYBOARD_EVENT, ble))
    loop.create_task(mouse_loop(MOUSE_EVENT, ble))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        ble.unpublish()
        logger.info("Stopped advertising")

if __name__ == "__main__":
    main()