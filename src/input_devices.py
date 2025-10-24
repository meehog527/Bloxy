import os
import logging

logger = logging.getLogger("hid-proxy")

def autodetect_inputs():
    keyboard_event = None
    mouse_event = None
    base = "/dev/input/by-id"

    if not os.path.isdir(base):
        logger.warning(f"{base} not found. Set devices manually.")
        return None, None

    for name in os.listdir(base):
        path = os.path.join(base, name)
        try:
            real = os.path.realpath(path)
        except Exception:
            continue
        lname = name.lower()
        if ("keyboard" in lname or "kbd" in lname) and real.startswith("/dev/input/event"):
            keyboard_event = real
        if "mouse" in lname and real.startswith("/dev/input/event"):
            mouse_event = real

    logger.info(f"Auto-detected keyboard={keyboard_event}, mouse={mouse_event}")
    return keyboard_event, mouse_event