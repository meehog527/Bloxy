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

    def build_mouse_report(self, buttons, rel_x, rel_y, scroll_v=0, code=-1):
        """
        Treat rel_x and rel_y as relative deltas (not absolute).
        scroll_v is a relative wheel delta.
        Returns 4-byte mouse report [buttons, x_delta, y_delta, wheel_delta].
        """

        mouse_maps = self.maps.get('mouse', {})
        report = [0x00, 0x00, 0x00, 0x00]

        # set bits from named buttons
        report[0] |= mouse_maps.get('BTN_LEFT', 0) if 'BTN_LEFT' in buttons else 0
        report[0] |= mouse_maps.get('BTN_RIGHT', 0) if 'BTN_RIGHT' in buttons else 0
        report[0] |= mouse_maps.get('BTN_MIDDLE', 0) if 'BTN_MIDDLE' in buttons else 0

        # also set bits from raw evdev code if present
        if code == 272:   # BTN_LEFT
            report[0] |= mouse_maps.get('BTN_LEFT', 0)
        elif code == 273: # BTN_RIGHT
            report[0] |= mouse_maps.get('BTN_RIGHT', 0)
        elif code == 274: # BTN_MIDDLE
            report[0] |= mouse_maps.get('BTN_MIDDLE', 0)

        # Always treat inputs as relative deltas
        dx = int(rel_x)
        dy = int(rel_y)
        dv = int(scroll_v)

        # maintain a dedicated cumulative wheel value for bookkeeping (not required for the report)
        if not hasattr(self, 'cumulative_wheel'):
            self.cumulative_wheel = 0
        self.cumulative_wheel += dv

        # clamp to signed 8-bit and convert to two's complement byte
        def to_signed_byte(v):
            if v > 127:
                v = 127
            elif v < -127:
                v = -127
            return v & 0xFF

        report[1] = to_signed_byte(dx)
        report[2] = to_signed_byte(dy)
        report[3] = to_signed_byte(dv)

        return report

