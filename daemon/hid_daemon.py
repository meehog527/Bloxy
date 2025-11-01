# hid_daemon.py

import os
import json
import logging
import dbus
import dbus.mainloop.glib
import dbus.service
import signal
import sys
from gi.repository import GLib
import threading

from ble_peripheral import HIDService, HIDApplication, load_yaml_config
from hid_reports import HIDReportBuilder
from evdev_tracker import EvdevTracker, HIDMouseService
from dbus_utils import PeripheralController

from constants import (
    DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE,
    HID_APP_PATH, HID_SERVICE_BASE, DAEMON_OBJ_PATH, DAEMON_IFACE, DAEMON_BUS_NAME, LOG_LEVEL, LOG_FORMAT
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# DBus Service
# ----------------------------------------------------------------------

class HIDPeripheralService(dbus.service.Object):
    """
    DBus service exposing HID peripheral status and control.
    """

    def __init__(self, bus, services, controller, trackers, report_builder):
        super().__init__(bus, DAEMON_OBJ_PATH)
        self.bus = bus
        self.services = services
        self.controller = controller
        self.trackers = trackers
        self.report_builder = report_builder
        self.connected_devices = []  # placeholder, can be updated from controller
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ------------------------------------------------------------------
    # DBus methods
    # ------------------------------------------------------------------

    @dbus.service.method(DAEMON_IFACE, out_signature='s')
    def GetStatus(self):
        """Return JSON status of controller, services, and devices."""
        return json.dumps(self._serialize_status())

    @dbus.service.method(DAEMON_IFACE)
    def Toggle(self):
        """Toggle controller on/off and emit status update."""
        if self.controller.is_on:
            self.controller.stop()
        else:
            self.controller.start()
        self.StatusUpdated(self.GetStatus())

    @dbus.service.method(DAEMON_IFACE, in_signature='sb')
    def SetNotify(self, characteristic_uuid, enable):
        """Enable/disable notifications for a characteristic by UUID."""
        for svc in self.services:
            for ch in svc.characteristics:
                if ch.uuid == characteristic_uuid:
                    ch.set_notifying(bool(enable))
                    self.logger.info(f"SetNotify: {characteristic_uuid} -> {enable}")
                    return
        self.logger.warning(f"SetNotify: characteristic {characteristic_uuid} not found")

    # ------------------------------------------------------------------
    # DBus signals
    # ------------------------------------------------------------------

    @dbus.service.signal(DAEMON_IFACE, signature='s')
    def StatusUpdated(self, status_json):
        """Signal emitted when status changes."""
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _serialize_status(self):
        return {
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


# ----------------------------------------------------------------------
# HIDDaemon Orchestrator
# ----------------------------------------------------------------------

class HIDDaemon:
    """
    HIDDaemon orchestrates the HID peripheral:
      - Starts the PeripheralController
      - Validates and sets up input devices
      - Creates the DBus HIDPeripheralService
      - Schedules periodic report updates
    """

    def __init__(self, bus, services, controller, report_builder):
        self.bus = bus
        self.services = services
        self.controller = controller
        self.report_builder = report_builder

        self.keyboard_dev = None
        self.mouse_dev = None
        self.keyboard_char = None
        self.mouse_svc = None
        self.daemon_service = None
        self.last_kb_report = None

        # New flags to prevent duplicates
        self._service_created = False
        self._controller_ready_seen = False

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Subscribe to controller events
        self.controller.on_ready(self._on_controller_ready)
        self.controller.on_failed(self._on_controller_failed)

    # ------------------------------------------------------------------
    # Initialization steps
    # ------------------------------------------------------------------

    def start(self):
        # Just kick off controller; readiness comes via callback
        if not self._start_controller():
            return False
        return True

    def _start_controller(self):
        try:
            if not self.controller.start():
                self.logger.error("Peripheral controller failed to start synchronously.")
                GLib.MainLoop().quit()
                return False
            return True
        except Exception as e:
            self.logger.exception(f"Controller start raised exception: {e}")
            GLib.MainLoop().quit()
            return False

    def _setup_input_devices(self):
        """Validate and initialize input devices."""
        kdev_path = os.environ.get('KEYBOARD_DEV', '/dev/input/event0')
        mdev_path = os.environ.get('MOUSE_DEV', '/dev/input/event1')

        if not validate_input_device(kdev_path, "keyboard"):
            self.logger.error("Keyboard device not valid, exiting.")
            GLib.MainLoop().quit()
            return False

        if not validate_input_device(mdev_path, "mouse"):
            self.logger.error("Mouse device not valid, exiting.")
            GLib.MainLoop().quit()
            return False

        self.keyboard_dev = EvdevTracker(kdev_path)
        self.mouse_dev = EvdevTracker(mdev_path)
        return True

    def _create_dbus_service(self):
        """Create the HIDPeripheralService and locate HID characteristics."""
        if self._service_created:
            self.logger.warning("⚠️ HIDPeripheralService already exists, skipping re‑creation.")
            return

        self.daemon_service = HIDPeripheralService(
            bus=self.bus,
            services=self.services,
            controller=self.controller,
            trackers={'keyboard': self.keyboard_dev, 'mouse': self.mouse_dev},
            report_builder=self.report_builder
        )
        self._service_created = True

        for svc in self.services:
            for ch in svc.characteristics:
                name = (ch.name or '').lower()
                if 'HID Report - Input (Keyboard)' in name:
                    self.keyboard_char = ch
                elif 'mouse' in name and 'report' in name:
                    self.mouse_svc = HIDMouseService(
                        os.environ.get('MOUSE_DEV', '/dev/input/event1'), ch
                    )

    def _schedule_report_updates(self):
        """Schedule periodic polling of input devices and report updates."""
        def update_reports():
            try:
                self.keyboard_dev.poll()
                if self.mouse_svc:
                    self.mouse_svc.poll()
                if self.keyboard_char:
                    kb_report = self.report_builder.build_keyboard_report(
                        list(self.keyboard_dev.pressed_keys)
                    )
                    if kb_report != self.last_kb_report:
                        self.keyboard_char.update_value(kb_report)
                        self.last_kb_report = kb_report
                        self.daemon_service.StatusUpdated(self.daemon_service.GetStatus())
            except Exception as e:
                self.logger.exception("Error in update_reports: %s", e)
            return True

        GLib.timeout_add(20, update_reports)

    # ------------------------------------------------------------------
    # Controller callbacks
    # ------------------------------------------------------------------

    def _on_controller_ready(self):
        if not self._setup_input_devices():
            return
        if self._controller_ready_seen:
            self.logger.debug("Controller ready already processed; ignoring duplicate.")
            return
        self._create_dbus_service()
        self._schedule_report_updates()
        self.logger.info("✅ HID peripheral daemon fully running.")
        self._controller_ready_seen = True

    def _on_controller_failed(self, reason):
        if "AlreadyExists" in str(reason):
            self.logger.warning("⚠️ Ignoring AlreadyExists error; controller is probably still active.")
            return
        self.logger.error(f"❌ Peripheral controller failed: {reason}")
        GLib.MainLoop().quit()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def stop(self):
        """Clean shutdown: unregister advertisement/application if needed."""
        try:
            if self.daemon_service:
                try:
                    self.daemon_service.remove_from_connection()
                    self.logger.info("🛑 HIDPeripheralService unregistered.")
                except Exception as e:
                    self.logger.warning(f"⚠️ Could not unregister HIDPeripheralService: {e}")
                self.daemon_service = None
                self._service_created = False
                self._controller_ready_seen = False

            if self.controller:
                self.controller.stop()
            self.logger.info("HIDDaemon stopped cleanly.")
        except Exception as e:
            self.logger.exception(f"Error during shutdown: {e}")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def validate_input_device(dev_path, device_type):
    """
    Ensure the given input device path exists and is accessible.
    Returns True if valid, False otherwise.
    """
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



# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------

def main():
    logger.info("🚀 Starting HID daemon")
    # Ensure DBus integrates with GLib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()
    name = dbus.service.BusName(DAEMON_BUS_NAME, bus)

    # Load configuration
    peripheral_yaml = os.environ.get('PERIPHERAL_YAML', 'peripheral.yaml')
    report_yaml = os.environ.get('REPORT_MAP_YAML', 'report_map.yaml')
    cfg = load_yaml_config(peripheral_yaml)
    report_builder = HIDReportBuilder(report_yaml)

    # Build services and application
    services = [HIDService(bus, i, svc_cfg)
                for i, svc_cfg in enumerate(cfg['peripheral']['services'])]
    app = HIDApplication(bus, services, path=HID_APP_PATH)

    # Controller and daemon
    controller = PeripheralController(bus, services, cfg, app_path=HID_APP_PATH)
    daemon = HIDDaemon(bus, services, controller, report_builder)

    # Main loop
    loop = GLib.MainLoop()

    # Clean shutdown on SIGINT/SIGTERM
    def shutdown(*args):
        logger.info("🛑 Stopping HID daemon...")
        try:
            daemon.stop()
        except Exception as e:
            logger.exception("Error during daemon shutdown: %s", e)
        loop.quit()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start daemon once loop is idle (return False so it only runs once)
    def start_once():
        daemon.start()
        return False

    GLib.idle_add(start_once)

    # Start REPL in background thread
    threading.Thread(target=repl_loop, args=(daemon,), daemon=True).start()

    try:
        loop.run()
    except KeyboardInterrupt:
        shutdown()


# ----------------------------------------------------------------------
# Interactive REPL for text commands
# ----------------------------------------------------------------------

def repl_loop(daemon):
    """
    Simple REPL loop running in a background thread.
    Type commands into stdin while the daemon is running.
    """
    print("Type 'help' for commands. Ctrl+D or 'quit' to exit REPL (daemon keeps running).")
    for line in sys.stdin:
        cmd = line.strip().lower()
        if not cmd:
            continue
        if cmd in ("quit", "exit"):
            print("Exiting REPL (daemon continues).")
            break
        elif cmd == "help":
            command_map=[
                "status",
                "check-adapter",
                "check-services",
                "check-devices",
                "trust <mac>",
                "cache-list",
                "cache-remove",
                "get-connected-devices"
            ]
            command_msg = "\r\n".join(command_map)
            print(command_msg)
        elif cmd == "status":
            if daemon.daemon_service:
                status_json = daemon.daemon_service.GetStatus()
                try:
                    status_obj = json.loads(status_json)
                    print(json.dumps(status_obj, indent=2))
                except Exception as e:
                    print("Could not parse status JSON:", e)
                    print(status_json)
            else:
                print("No service yet")

        elif cmd == "check-adapter":
            print(daemon.controller._check_adapter())
        elif cmd == "check-services":
            print(f"Services: {[svc.uuid for svc in daemon.services]}")
        elif cmd == "check-devices":
            print(daemon.controller._check_devices())
        elif cmd.startswith("trust "):
            mac = cmd.split(" ", 1)[1]
            print("Trust result:", daemon.controller.trust_device(mac))
        elif cmd == "cache-list":
            devices = daemon.controller.list_cached_devices()
            print(json.dumps(devices, indent=2))
        elif cmd.startswith("cache-remove "):
            mac = cmd.split(" ", 1)[1]
            daemon.controller.remove_cached_device(mac)
        elif cmd == "get-connected-devices":
            devices = daemon.controller.get_connected_devices()
            print(json.dumps(devices, indent=2))
        else:
            print(f"Unknown command: {cmd}")


if __name__ == '__main__':
    main()