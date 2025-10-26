import yaml

class HIDReportBuilder:
    def __init__(self, map_file):
        with open(map_file, 'r') as f:
            self.maps = yaml.safe_load(f)['report_maps']

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
        pressed_keys: iterable of evdev key names, e.g., ['KEY_A', 'KEY_LEFTSHIFT']
        Returns: list of 8 bytes [modifiers, reserved, key1..key6]
        """
        report = [0x00] * 8

        # Modifiers
        for key in pressed_keys:
            mod = self.modifiers.get(key)
            if mod:
                report[0] |= mod

        # Normal keys
        idx = 2
        for key in pressed_keys:
            usage = self.maps['keyboard'].get(key)
            if usage is not None and idx < 8:
                report[idx] = usage
                idx += 1

        return report

    def build_mouse_report(self, buttons, rel_x, rel_y):
        """
        buttons: set of pressed button names, e.g., {'BTN_LEFT'}
        rel_x, rel_y: integers (relative movement)
        Returns: 4-byte mouse report [buttons, x, y, wheel(0)]
        """
        report = [0x00, 0x00, 0x00, 0x00]
        if 'BTN_LEFT' in buttons:
            report[0] |= 0x01
        if 'BTN_RIGHT' in buttons:
            report[0] |= 0x02
        if 'BTN_MIDDLE' in buttons:
            report[0] |= 0x04

        report[1] = (rel_x + 256) % 256
        report[2] = (rel_y + 256) % 256
        report[3] = 0x00
        return report
