# hid_daemon.py

import os
import json
import logging
import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

from ble_peripheral import HIDService, HIDApplication, load_yaml_config
from hid_reports import HIDReportBuilder
from evdev_tracker import EvdevTracker
from dbus_utils import register_app, DAEMON_BUS_NAME, DAEMON_OBJ_PATH, DAEMON_IFACE

# -------------------------------------------------------------------
# Logging configuration
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,  # Change to INFO for less verbosity
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hid_daemon")


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
        logger.info("Starting peripheral, registering GATT application at %s", self.app_path)
        try:
            register_app(self.bus, self.app_path)
            self.is_on = True
            logger.info("Peripheral started successfully")
        except Exception as e:
            logger.exception("Failed to register GATT application: %s", e)

    def stop(self):
        # Note: Some BlueZ versions don't provide UnregisterApplication. We simulate OFF state.
        self.is_on = False
        logger.info("Peripheral stopped (simulated)")

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
        logger.debug("HIDPeripheralService exported at %s", DAEMON_OBJ_PATH)

    @dbus.service.method(DAEMON_IFACE, out_signature='s')
    def GetStatus(self):
        #logger.debug("GetStatus called")
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
        logger.info("Toggle called. Current state: %s", self.controller.is_on)
        if self.controller.is_on:
            self.controller.stop()
        else:
            self.controller.start()

    @dbus.service.method(DAEMON_IFACE, in_signature='sb')
    def SetNotify(self, characteristic_uuid, enable):
        logger.info("SetNotify called for %s -> %s", characteristic_uuid, enable)
        for svc in self.services:
            for ch in svc.characteristics:
                if ch.uuid == characteristic_uuid:
                    ch.set_notifying(bool(enable))
                    logger.debug("Characteristic %s notifying=%s", ch.uuid, ch.notifying)
                    return

    @dbus.service.signal(DAEMON_IFACE, signature='s')
    def StatusUpdated(self, status_json):
        #logger.debug("StatusUpdated signal emitted")
        pass


def main():
    logger.info("Starting HID daemon")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    # Load configs
    peripheral_yaml = os.environ.get('PERIPHERAL_YAML', 'peripheral.yaml')
    report_yaml = os.environ.get('REPORT_MAP_YAML', 'report_map.yaml')
    logger.debug("Loading configs: %s, %s", peripheral_yaml, report_yaml)
    cfg = load_yaml_config(peripheral_yaml)
    report_builder = HIDReportBuilder(report_yaml)

    # Build services
    services = [HIDService(bus, i, svc_cfg) for i, svc_cfg in enumerate(cfg['peripheral']['services'])]
    logger.info("Built %d services", len(services))

    # Create application object at /org/bluez/hid
    app = HIDApplication(bus, services, path='/org/bluez/hid')
    logger.debug("HIDApplication exported at /org/bluez/hid")

    # Controller
    controller = PeripheralController(bus, services, app_path='/org/bluez/hid')

    # Evdev trackers
    kdev_path = os.environ.get('KEYBOARD_DEV', '/dev/input/event0')
    mdev_path = os.environ.get('MOUSE_DEV', '/dev/input/event1')
    logger.debug("Keyboard dev: %s, Mouse dev: %s", kdev_path, mdev_path)
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
                logger.debug("Keyboard characteristic found: %s", ch.uuid)
            elif 'mouse' in name and 'report' in name:
                mouse_char = ch
                logger.debug("Mouse characteristic found: %s", ch.uuid)

    # Periodic update loop
    def update_reports():
        try:
            keyboard_dev.poll()
            mouse_dev.poll()
            if keyboard_char:
                kb_report = report_builder.build_keyboard_report(list(keyboard_dev.pressed_keys))
                keyboard_char.update_value(kb_report)
                #slogger.debug("Keyboard report updated: %s", kb_report)
            if mouse_char:
                m_report = report_builder.build_mouse_report(mouse_dev.buttons, mouse_dev.rel_x, mouse_dev.rel_y)
                mouse_char.update_value(m_report)
                #logger.debug("Mouse report updated: %s", m_report)
                mouse_dev.rel_x = 0
                mouse_dev.rel_y = 0
            daemon.StatusUpdated(daemon.GetStatus())
        except Exception as e:
            logger.exception("Error in update_reports: %s", e)
        return True

    GLib.timeout_add(20, update_reports)
    logger.info("HID peripheral daemon running.")
    GLib.MainLoop().run()


if __name__ == '__main__':
    main()