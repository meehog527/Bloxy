import dbus
import dbus.mainloop.glib
from gi.repository import GLib

import yaml
from .hid_reports import HIDReportBuilder
from .evdev_tracker import EvdevTracker
from .ble_peripheral import HIDService
from .dbus_utils import register_app

def load_yaml_config(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def find_hid_chars(services):
    keyboard_char = None
    mouse_char = None
    for svc in services:
        for ch in svc.characteristics:
            name = (ch.name or '').lower()
            if 'keyboard' in name:
                keyboard_char = ch
            elif 'mouse' in name:
                mouse_char = ch
    return keyboard_char, mouse_char

def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    peripheral_cfg = load_yaml_config('peripheral.yaml')
    report_builder = HIDReportBuilder('report_map.yaml')

    # Build HID service(s)
    services = []
    for i, svc_cfg in enumerate(peripheral_cfg['peripheral']['services']):
        services.append(HIDService(bus, i, svc_cfg))

    # Register GATT application
    register_app(bus, '/org/bluez/hid')

    # Identify keyboard and mouse characteristics
    keyboard_char, mouse_char = find_hid_chars(services)

    # Set up evdev trackers (adjust paths)
    keyboard_dev = EvdevTracker('/dev/input/event0')  # replace with actual keyboard
    mouse_dev = EvdevTracker('/dev/input/event1')     # replace with actual mouse

    def update_reports():
        # Poll devices
        keyboard_dev.poll()
        mouse_dev.poll()

        # Keyboard report
        if keyboard_char:
            kb_report = report_builder.build_keyboard_report(list(keyboard_dev.pressed_keys))
            keyboard_char.update_value(kb_report)

        # Mouse report
        if mouse_char:
            m_report = report_builder.build_mouse_report(mouse_dev.buttons, mouse_dev.rel_x, mouse_dev.rel_y)
            mouse_char.update_value(m_report)
            # Reset deltas
            mouse_dev.rel_x = 0
            mouse_dev.rel_y = 0

        return True

    # Periodic updates (50 Hz)
    GLib.timeout_add(20, update_reports)

    print('HID peripheral running. Connect a host and enable notifications via CCCD.')
    GLib.MainLoop().run()

if __name__ == '__main__':
    main()
