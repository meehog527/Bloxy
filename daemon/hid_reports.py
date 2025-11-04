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
        rel_x, rel_y: treated here as relative deltas (typical from poll/SYN).
        This function updates internal absolute position (self._last_pos) by adding
        these deltas, then produces a 4-byte HID report [buttons, dx, dy, wheel_delta].
        scroll_v is treated as a relative delta and cumulative wheel state is tracker
        in self.cumulative_wheel for bookkeeping.
        """
        mouse_maps = self.maps.get('mouse', {})
        report = [0x00, 0x00, 0x00, 0x00]

        # named buttons
        report[0] |= mouse_maps.get('BTN_LEFT', 0) if 'BTN_LEFT' in buttons else 0
        report[0] |= mouse_maps.get('BTN_RIGHT', 0) if 'BTN_RIGHT' in buttons else 0
        report[0] |= mouse_maps.get('BTN_MIDDLE', 0) if 'BTN_MIDDLE' in buttons else 0

        # raw evdev codes (272,273,274)
        if code == 272:
            report[0] |= mouse_maps.get('BTN_LEFT', 0)
        elif code == 273:
            report[0] |= mouse_maps.get('BTN_RIGHT', 0)
        elif code == 274:
            report[0] |= mouse_maps.get('BTN_MIDDLE', 0)

        # Ensure last_pos exists
        if not hasattr(self, '_last_pos') or self._last_pos is None:
            self._last_pos = (0, 0, 0)

        # Inputs are relative deltas: update absolute last_pos before computing the HID deltas
        dx = int(rel_x)
        dy = int(rel_y)
        dv = int(scroll_v)

        lx, ly, lw = self._last_pos
        # update internal absolute position
        new_lx = lx + dx
        new_ly = ly + dy
        new_lw = lw + dv
        self._last_pos = (int(new_lx), int(new_ly), int(new_lw))

        # maintain cumulative wheel for diagnostics if needed
        if not hasattr(self, 'cumulative_wheel'):
            self.cumulative_wheel = 0
        self.cumulative_wheel += dv

        # clamp to signed 8-bit two's complement
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
