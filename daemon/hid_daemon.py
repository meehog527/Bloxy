# hid_daemon.py

import os
import json
import logging
import dbus
import dbus.mainloop.glib
import dbus.service
import sys
from gi.repository import GLib

from ble_peripheral import HIDService, HIDApplication, load_yaml_config
from hid_reports import HIDReportBuilder
from evdev_tracker import EvdevTracker, HIDMouseService
from dbus_utils import PeripheralController

from constants import (
    DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE,
    HID_APP_PATH, HID_SERVICE_BASE, DAEMON_OBJ_PATH, DAEMON_IFACE, DAEMON_BUS_NAME
)

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("hid_daemon")


class HIDPeripheralService(dbus.service.Object):
    def __init__(self, bus, services, controller, trackers, report_builder):
        super().__init__(bus, DAEMON_OBJ_PATH)
        self.bus = bus
        self.services = services
        self.controller = controller
        self.trackers = trackers
        self.report_builder = report_builder
        self.connected_devices = []

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


def validate_input_device(dev_path, device_type):
    if not os.path.exists(dev_path):
        logger.error("Device path %s does not exist", dev_path)
        return False
    try:
        with open(dev_path, 'rb'):
            logger.debug("%s device %s is accessible", device_type, dev_path)
            return True
    except Exception as e:
        logger.error("Failed to access %s device %s: %s", device_type, dev_path, e)
        return False


def main():
    logger.info("Starting HID daemon")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()
    name = dbus.service.BusName(DAEMON_BUS_NAME, bus)

    peripheral_yaml = os.environ.get('PERIPHERAL_YAML', 'peripheral.yaml')
    report_yaml = os.environ.get('REPORT_MAP_YAML', 'report_map.yaml')
    cfg = load_yaml_config(peripheral_yaml)
    report_builder = HIDReportBuilder(report_yaml)

    services = [HIDService(bus, i, svc_cfg) for i, svc_cfg in enumerate(cfg['peripheral']['services'])]
    
    app = HIDApplication(bus, services, path=HID_APP_PATH)

    controller = PeripheralController(bus, services, app_path=HID_APP_PATH)

    # Defer controller.start() until the main loop is active
    def init_controller():
        if not controller.start():
            logger.error("Peripheral controller failed to start, exiting.")
            sys.exit(1)

        kdev_path = os.environ.get('KEYBOARD_DEV', '/dev/input/event0')
        mdev_path = os.environ.get('MOUSE_DEV', '/dev/input/event1')

        if not validate_input_device(kdev_path, "keyboard"):
            logger.error("Keyboard device not valid, exiting.")
            sys.exit(1)

        if not validate_input_device(mdev_path, "mouse"):
            logger.error("Mouse device not valid, exiting.")
            sys.exit(1)

        keyboard_dev = EvdevTracker(kdev_path)
        mouse_dev = EvdevTracker(mdev_path)

        daemon = HIDPeripheralService(
            bus=bus,
            services=services,
            controller=controller,
            trackers={'keyboard': keyboard_dev, 'mouse': mouse_dev},
            report_builder=report_builder
        )

        keyboard_char = None
        mouse_char = None
        mouse_svc = None
        for svc in services:
            for ch in svc.characteristics:
                name = (ch.name or '').lower()
                if 'keyboard' in name and 'report' in name:
                    keyboard_char = ch
                elif 'mouse' in name and 'report' in name:
                    mouse_char = ch
                    mouse_svc = HIDMouseService(mdev_path, ch)

        def update_reports():
            try:
                keyboard_dev.poll()
                if mouse_svc:
                    mouse_svc.poll()
                if keyboard_char:
                    kb_report = report_builder.build_keyboard_report(list(keyboard_dev.pressed_keys))
                    keyboard_char.update_value(kb_report)
                daemon.StatusUpdated(daemon.GetStatus())
            except Exception as e:
                logger.exception("Error in update_reports: %s", e)
            return True

        GLib.timeout_add(20, update_reports)
        logger.info("HID peripheral daemon running.")
        return False  # run once

    GLib.idle_add(init_controller)

    GLib.MainLoop().run()


if __name__ == '__main__':
    main()