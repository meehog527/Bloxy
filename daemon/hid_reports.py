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

    def build_mouse_report(self, buttons, rel_x, rel_y, scroll_v=0, code = -1):
        """
        rel_x, rel_y: these should be the current absolute position OR a raw incremental
        value that may be accumulated elsewhere. This function treats inputs as
        current absolute position if self._last_pos exists, otherwise as deltas.
        Returns 4-byte mouse report [buttons, x, y, wheel]
        """
        mouse_maps = self.maps.get('mouse', {})
        report = [0x00, 0x00, 0x00, 0x00]

        report[0] |= mouse_maps.get('BTN_LEFT', 0) if 'BTN_LEFT' in buttons else 0
        report[0] |= mouse_maps.get('BTN_RIGHT', 0) if 'BTN_RIGHT' in buttons else 0
        report[0] |= mouse_maps.get('BTN_MIDDLE', 0) if 'BTN_MIDDLE' in buttons else 0
        
        report[0] |= mouse_maps.get('BTN_LEFT', 0) if code == 272 else 0
        report[0] |= mouse_maps.get('BTN_RIGHT', 0) if code == 273 in buttons else 0
        report[0] |= mouse_maps.get('BTN_MIDDLE', 0) if code == 274 in buttons else 0

        # Interpret rel_x/rel_y as absolute if last_pos exists, otherwise as delta
        if hasattr(self, '_last_pos') and self._last_pos is not None:
            dx = int(rel_x) - self._last_pos[0]
            dy = int(rel_y) - self._last_pos[1]
            
            if (scroll_v > 0 and self._last_post[2] < 0) or (scroll_v < 0 and self._last_post[2] > 0) :
                dv = scroll_v
                scroll_v = 0

        else:
            dx = int(rel_x)
            dy = int(rel_y)
            scroll_v = int(scroll_v)

  

        # update last_pos to the current absolute values so next call computes a delta
        self._last_pos = (int(rel_x), int(rel_y), int(dv))

        # clamp to signed 8-bit and convert to two's complement byte
        def to_signed_byte(v):
            if v > 127:
                v = 127
            elif v < -127:
                v = -127
            return v & 0xFF

        report[1] = to_signed_byte(dx)
        report[2] = to_signed_byte(dy)
        report[3] = dv

        print(dv)

        return report
