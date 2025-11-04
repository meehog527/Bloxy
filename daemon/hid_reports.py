# hid_reports.py  (optimized)

import yaml

class HIDReportBuilder:
    """
    Fast HID report builder that minimizes allocations.
    build_*_bytes returns immutable bytes suitable for cheap equality checks
    and immediate BLE sending. The builder reuses internal bytearray buffers.
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

        # Preallocated buffers reused per call
        self._kb_buf = bytearray(8)
        self._mouse_buf = bytearray(4)

    # -------------------------
    # Keyboard
    # -------------------------
    def build_keyboard_report(self, pressed_keys):
        """
        Backwards-compatible API returning a list (same shape as before).
        """
        kb_bytes = self.build_keyboard_report_bytes(pressed_keys)
        return list(kb_bytes)

    def build_keyboard_report_bytes(self, pressed_keys):
        """
        Fast path: returns immutable bytes(8) for keyboard report.
        pressed_keys: iterable of evdev key names (strings).
        """
        # zero the buffer in-place
        buf = self._kb_buf
        for i in range(8):
            buf[i] = 0

        # Modifiers
        for key in pressed_keys:
            mod = self.modifiers.get(key)
            if mod:
                buf[0] |= mod

        # Non-modifier keys (up to 6)
        idx = 2
        keyboard_map = self.maps.get('keyboard', {})
        for key in pressed_keys:
            if idx >= 8:
                break
            usage = keyboard_map.get(key)
            if usage:
                buf[idx] = usage & 0xFF
                idx += 1

        return bytes(buf)  # single small copy

    # -------------------------
    # Mouse (delta mode)
    # -------------------------
    def build_mouse_report(self, buttons, rel_x, rel_y, code=None):
        """
        Backwards-compatible API returning list [buttons,x,y,wheel]
        Buttons: iterable of string names like 'BTN_LEFT' (or set)
        rel_x/rel_y: deltas (integers)
        code: optional last button code (not used here)
        """
        mouse_bytes = self.build_mouse_report_bytes(buttons, rel_x, rel_y, code)
        return list(mouse_bytes)

    def build_mouse_report_bytes(self, buttons, rel_x, rel_y, code=None):
        """
        Fast path: returns immutable bytes(4) for mouse report.
        - buttons: iterable or set of 'BTN_LEFT'/'BTN_RIGHT'/'BTN_MIDDLE'
        - rel_x, rel_y: delta integers (signed, clamped to -127..127)
        - code: unused, kept for compatibility
        """
        maps = self.maps.get('mouse', {})
        buf = self._mouse_buf

        # button byte
        b = 0
        btn_left_mask = maps.get('BTN_LEFT', 0)
        btn_right_mask = maps.get('BTN_RIGHT', 0)
        btn_mid_mask = maps.get('BTN_MIDDLE', 0)

        # `buttons` may be a set of strings or evdev keycodes; normalize to strings
        # Accept both 'BTN_LEFT' or evdev's string names from your tracker
        if buttons:
            # iterate once and OR masks
            for btn in buttons:
                # support both 'BTN_LEFT' and 'BTN_LEFT' present as name
                if btn == 'BTN_LEFT' or str(btn).upper().endswith('BTN_LEFT'):
                    b |= btn_left_mask
                elif btn == 'BTN_RIGHT' or str(btn).upper().endswith('BTN_RIGHT'):
                    b |= btn_right_mask
                elif btn == 'BTN_MIDDLE' or str(btn).upper().endswith('BTN_MIDDLE'):
                    b |= btn_mid_mask

        buf[0] = b & 0xFF

        # clamp deltas to signed 8-bit range and encode as two's complement byte
        def clamp8(v):
            if v > 127:
                v = 127
            elif v < -127:
                v = -127
            return v & 0xFF

        buf[1] = clamp8(int(rel_x))
        buf[2] = clamp8(int(rel_y))
        buf[3] = 0x00  # wheel unused

        return bytes(buf)  # single small copy

    # Optional: absolute mouse if you really want it
    def build_mouse_report_bytes_absolute(self, abs_x, abs_y, buttons, wheel=0):
        """
        If you supply absolute positions, this will compute deltas internally
        and return a bytes report. It keeps last absolute on the builder.
        """
        if not hasattr(self, '_last_abs'):
            self._last_abs = (int(abs_x), int(abs_y))
        last_x, last_y = self._last_abs
        dx = int(abs_x) - last_x
        dy = int(abs_y) - last_y
        self._last_abs = (int(abs_x), int(abs_y))
        return self.build_mouse_report_bytes(buttons, dx, dy, code=None)