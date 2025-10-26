import os
import json
import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

from .ble_peripheral import HIDService, load_yaml_config
from .hid_reports import HIDReportBuilder
from .evdev_tracker import EvdevTracker
from .dbus_utils import register_app, DAEMON_BUS_NAME, DAEMON_OBJ_PATH, DAEMON_IFACE

class PeripheralController:
    """
    Controls the lifecycle of the GATT application registration.
    """
    def __init__(self, bus, services, app_path='/org/bluez/hid'):
        self.bus = bus
        self.services = services
        self.app_path = app_path
        self.is_on = False

    def start(self):
        register_app(self.bus, self.app_path)
        self.is_on = True
        print("Peripheral started")

    def stop(self):
        # Note: Some BlueZ versions don't provide UnregisterApplication. We simulate OFF state.
        self.is_on = False
        print("Peripheral stopped (simulated)")

    def get_status(self):
        return {'is_on': self.is_on}

class HIDPeripheralService(dbus.service.Object):
    """
    Custom D-Bus service exposing status/control for the HID daemon.
    """
    def __init__(self, bus, services, controller, trackers, report_builder):
        super().__init__(bus, DAEMON_OBJ_PATH)
        self.bus = bus
        self.services = services
        self.controller = controller
        self.trackers = trackers
        self.report_builder = report_builder
        self.connected_devices = []  # Can be hooked to BlueZ connections

    @dbus.service.method(DAEMON_IFACE, out_signature='s')
    def GetStatus(self):
        status = {
            'is_on': self.controller.is_on,
            'connected_devices': self.connected_devices,
            'services': [
                {
                    'uuid': svc.uuid,
                    'path': svc.path,
                    'characteristics': [
                        {
                            'uuid': ch.uuid,
                            'name': ch.name,
                            'value': [int(b) for b in ch.value],
                            'notifying': ch.notifying,
                            'flags': getattr(ch, 'flags', []),
                            'descriptors': [
                                {'uuid': d.uuid, 'value': [int(b) for b in d.value]}
                                for d in ch.descriptors
                            ]
                        } for ch in svc.characteristics
                    ]
                } for svc in self.services
            ]
        }
        return json.dumps(status)

    @dbus.service.method(DAEMON_IFACE)
    def Toggle(self):
        if self.controller.is_on:
            self.controller.stop()
        else:
            self.controller.start()

    @dbus.service.method(DAEMON_IFACE, in_signature='sb')
    def SetNotify(self, characteristic_uuid, enable):
        for svc in self.services:
            for ch in svc.characteristics:
                if ch.uuid == characteristic_uuid:
                    ch.set_notifying(bool(enable))
                    return

    @dbus.service.signal(DAEMON_IFACE, signature='s')
    def StatusUpdated(self, status_json):
        pass

def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    # Load configs
    peripheral_yaml = os.environ.get('PERIPHERAL_YAML', 'peripheral.yaml')
    report_yaml = os.environ.get('REPORT_MAP_YAML', 'report_map.yaml')
    cfg = load_yaml_config(peripheral_yaml)
    report_builder = HIDReportBuilder(report_yaml)

    # Build services
    services = [HIDService(bus, i, svc_cfg) for i, svc_cfg in enumerate(cfg['peripheral']['services'])]

    # Controller
    controller = PeripheralController(bus, services)

    # Evdev trackers
    kdev_path = os.environ.get('KEYBOARD_DEV', '/dev/input/event0')
    mdev_path = os.environ.get('MOUSE_DEV', '/dev/input/event1')
    keyboard_dev = EvdevTracker(kdev_path)
    mouse_dev = EvdevTracker(mdev_path)

    # Export D-Bus service
    daemon = HIDPeripheralService(
        bus=bus,
        services=services,
        controller=controller,
        trackers={'keyboard': keyboard_dev, 'mouse': mouse_dev},
        report_builder=report_builder
    )

    # Start peripheral by default
    controller.start()

    # Identify HID report characteristics
    keyboard_char = None
    mouse_char = None
    for svc in services:
        for ch in svc.characteristics:
            name = (ch.name or '').lower()
            if 'keyboard' in name and 'report' in name:
                keyboard_char = ch
            elif 'mouse' in name and 'report' in name:
                mouse_char = ch

    # Periodic update loop
    def update_reports():
        keyboard_dev.poll()
        mouse_dev.poll()
        # Keyboard
        if keyboard_char:
            kb_report = report_builder.build_keyboard_report(list(keyboard_dev.pressed_keys))
            keyboard_char.update_value(kb_report)
        # Mouse
        if mouse_char:
            m_report = report_builder.build_mouse_report(mouse_dev.buttons, mouse_dev.rel_x, mouse_dev.rel_y)
            mouse_char.update_value(m_report)
            mouse_dev.rel_x = 0
            mouse_dev.rel_y = 0
        # Broadcast status
        try:
            daemon.StatusUpdated(daemon.GetStatus())
        except Exception:
            pass
        return True

    GLib.timeout_add(20, update_reports)
    print('HID peripheral daemon running.')
    GLib.MainLoop().run()

if __name__ == '__main__':
    main()
