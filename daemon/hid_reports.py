#hid_reports.py

import yaml

class HIDReportBuilder:
    """
    Builds HID reports (keyboard, mouse) from evdev-style input using a YAML map.
    """
    def __init__(self, map_file):
        with open(map_file, 'r') as f:
            data = yaml.safe_load(f)
        self.maps = data.get('report_maps', {})

        # HID keyboard modifiers bitmap
        self.modifiers = {
            'KEY_LEFTCTRL': 0x01,
            'KEY_LEFTSHIFT': 0x02,
            'KEY_LEFTALT': 0x04,
            'KEY_LEFTMETA': 0x08,
            'KEY_RIGHTCTRL': 0x10,
            'KEY_RIGHTSHIFT': 0x20,
            'KEY_RIGHTALT': 0x40,
            'KEY_RIGHTMETA': 0x80,
        }

    def build_keyboard_report(self, pressed_keys):
        """
        pressed_keys: iterable of evdev key names (e.g., ['KEY_A','KEY_LEFTSHIFT'])
        Returns: 8-byte HID keyboard report [mod, reserved, key1..key6]
        """
        report = [0x00] * 8

        # Modifiers
        for key in pressed_keys:
            mod = self.modifiers.get(key)
            if mod:
                report[0] |= mod

        # Non-modifier keys (up to 6)
        idx = 2
        keyboard_map = self.maps.get('keyboard', {})
        for key in pressed_keys:
            usage = keyboard_map.get(key)
            if usage is not None and idx < 8:
                report[idx] = usage
                idx += 1

        return report

    def build_mouse_report(self, buttons, rel_x, rel_y):
        """
        buttons: set of pressed button names {'BTN_LEFT', 'BTN_RIGHT', ...}
        rel_x, rel_y: integer deltas (relative movement)
        Returns: 4-byte mouse report [buttons, x, y, wheel]
        """
        mouse_maps = self.maps.get('mouse', {})
        report = [0x00, 0x00, 0x00, 0x00]

        # safe button lookup with default 0
        if 'BTN_LEFT' in buttons:
            report[0] |= mouse_maps.get('BTN_LEFT', 0)
        if 'BTN_RIGHT' in buttons:
            report[0] |= mouse_maps.get('BTN_RIGHT', 0)
        if 'BTN_MIDDLE' in buttons:
            report[0] |= mouse_maps.get('BTN_MIDDLE', 0)

        # clamp to signed 8-bit range and convert to two's complement byte
        print(f"got x:{rel_x} y:{rel_y}")
        def to_signed_byte(val):
            if val > 127:
                val = 127
            elif val < -127:
                val = -127
            return val & 0xFF

        report[1] = to_signed_byte(int(rel_x))
        report[2] = to_signed_byte(int(rel_y))
        report[3] = 0x00
        return report
