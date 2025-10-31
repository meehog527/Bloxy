# ble_peripheral.py

import dbus
import dbus.service
import logging
from gi.repository import GLib
import yaml

from constants import (
    DBUS_PROP_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE,
    HID_APP_PATH, HID_SERVICE_BASE, DAEMON_OBJ_PATH, DBUS_ERROR_INVARG, DBUS_ERROR_PROPRO,DBUS_OBJMGR_IFACE
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hid_daemon")


class GattObject(dbus.service.Object):
    """
    Base class for GATT objects (Service, Characteristic, Descriptor).
    Provides the D-Bus Properties interface and common helpers.
    Subclasses must override `dbus_interface` and `get_property_map()`.
    """
    dbus_interface = None  # OVERRIDE in subclasses

    def __init__(self, bus, path):
        # --- Internal state ---
        super().__init__(bus, path)
        self.path = path

    # ----------------------------------------------------------------------
    # Implemented D-Bus Properties interface (org.freedesktop.DBus.Properties)
    # ----------------------------------------------------------------------

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='ssv', out_signature='')
    def Set(self, interface, prop, value):
        """
        BlueZ calls this to set a property.
        By default, disallows writes unless subclass overrides.
        """
        if interface != self.dbus_interface:
            raise dbus.exceptions.DBusException(DBUS_ERROR_INVARG)
        raise dbus.exceptions.DBusException(DBUS_ERROR_PROPRO)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        """
        BlueZ calls this to get a single property value.
        """
        if interface != self.dbus_interface:
            raise dbus.exceptions.DBusException(DBUS_ERROR_INVARG)

        props = self.get_property_map()
        if prop in props:
            return props[prop]
        raise dbus.exceptions.DBusException(DBUS_ERROR_INVARG)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        """
        BlueZ calls this to get all properties for the given interface.
        """
        if interface == self.dbus_interface:
            return self.get_property_map()
        return {}

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        """
        Signal emitted when properties change.
        Subclasses should use update_property() to trigger this.
        """
        pass

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='', out_signature='')
    def Release(self):
        """
        Optional cleanup hook.
        Called if BlueZ ever wants to release this object.
        """
        logger.debug(f"{self.path} released")

    # ----------------------------------------------------------------------
    # Helpers for subclasses (to override or call internally)
    # ----------------------------------------------------------------------

    def get_property_map(self):
        """
        OVERRIDE in subclasses.
        Return a dict of dbus-typed properties for this object.
        """
        return {}

    def get_managed_object(self):
        """
        Return this object’s entry for ObjectManager.GetManagedObjects().
        Subclasses may extend this to include children.
        """
        return {
            dbus.ObjectPath(self.path): {
                self.dbus_interface: self.get_property_map()
            }
        }

    def update_property(self, name, value):
        """
        Convenience helper to update a property and emit PropertiesChanged.
        """
        props = {name: value}
        try:
            self.PropertiesChanged(self.dbus_interface, props, [])
        except Exception as e:
            logger.warning(f"Failed to emit PropertiesChanged for {self.path}: {e}")


class HIDDescriptor(GattObject):
    """
    GATT Descriptor object (org.bluez.GattDescriptor1).
    Exposes descriptor-level properties and implements
    ReadValue/WriteValue for BlueZ.
    """
    dbus_interface = GATT_DESC_IFACE

    def __init__(self, bus, index, char, config):
        # --- Internal state ---
        self.char = char
        self.uuid = str(config['uuid'])
        self.flags = [str(f) for f in config.get('flags', [])]
        raw_val = config.get('value', [])
        self.value = [dbus.Byte(int(v) & 0xFF) for v in raw_val]

        # Deterministic path under parent characteristic
        path = f'{char.path}/desc{index}'
        super().__init__(bus, path)

        logger.debug(
            f"HIDDescriptor {self.uuid} initialized at {self.path} "
            f"for characteristic {self.char.name}"
        )

    # ----------------------------------------------------------------------
    # Overrides from GattObject
    # ----------------------------------------------------------------------

    def get_property_map(self):
        """
        OVERRIDE: GattObject.get_property_map()
        BlueZ expects UUID, Characteristic, Value, and Flags for GattDescriptor1.
        """
        return {
            'UUID': dbus.String(self.uuid),
            'Characteristic': dbus.ObjectPath(self.char.path),
            'Value': dbus.Array(self.value, signature='y'),
            'Flags': dbus.Array([dbus.String(f) for f in self.flags], signature='s'),
        }

    # ----------------------------------------------------------------------
    # BlueZ-facing D-Bus methods (specific to org.bluez.GattDescriptor1)
    # ----------------------------------------------------------------------

    @dbus.service.method(GATT_DESC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        """BlueZ calls this when the host reads the descriptor value."""
        logger.debug(f"Descriptor {self.uuid}: ReadValue called, returning {self.value}")
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_DESC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        """
        BlueZ calls this when the host writes to the descriptor.
        Special case: CCCD (0x2902) controls notifications.
        """
        try:
            new_val = [dbus.Byte(int(b) & 0xFF) for b in value]

            if self.uuid.lower() == '00002902-0000-1000-8000-00805f9b34fb':
                # Client Characteristic Configuration Descriptor (CCCD)
                self.value = new_val
                notify_enabled = len(value) >= 1 and (int(value[0]) & 0x01) != 0
                self.char.set_notifying(notify_enabled)

                # Reflect the new value back to the host
                self.update_property('Value', dbus.Array(self.value, signature='y'))

                logger.info(
                    f'CCCD write for {self.char.name}: '
                    f'notifications {"enabled" if notify_enabled else "disabled"}'
                )
            else:
                # Generic descriptor write
                self.value = new_val
                self.update_property('Value', dbus.Array(self.value, signature='y'))
                logger.debug(f"Descriptor {self.uuid} updated value: {self.value}")

        except Exception as e:
            logger.exception(f"Error in descriptor WriteValue ({self.uuid}): {e}")

    # ----------------------------------------------------------------------
    # Internal helpers (Not called by BlueZ)
    # ----------------------------------------------------------------------
    # (None needed here beyond GattObject already provides)


class HIDCharacteristic(GattObject):
    """
    GATT Characteristic object (org.bluez.GattCharacteristic1).
    Exposes characteristic-level properties and implements
    ReadValue/WriteValue/StartNotify/StopNotify for BlueZ.
    """
    dbus_interface = GATT_CHRC_IFACE

    def __init__(self, bus, index, service, config):
        # --- Internal state ---
        self.service = service
        self.uuid = str(config['uuid'])
        self.flags = [str(f) for f in config.get('flags', [])]
        raw_val = config.get('value', [])
        self.value = [dbus.Byte(self.parse_byte(v)) for v in raw_val]
        self.name = config.get('name', self.uuid)
        self.notifying = bool(config.get('notifying', False))
        self.descriptors = []

        # Deterministic path under parent service
        path = f'{service.path}/char{index}'
        super().__init__(bus, path)

        # Build child descriptors
        for i, desc_cfg in enumerate(config.get('descriptors', [])):
            self.descriptors.append(HIDDescriptor(bus, i, self, desc_cfg))

        logger.debug(
            f"HIDCharacteristic {self.uuid} ({self.name}) initialized at {self.path} "
            f"with {len(self.descriptors)} descriptors"
        )

    # ----------------------------------------------------------------------
    # Overrides from GattObject
    # ----------------------------------------------------------------------

    def get_property_map(self):
        """
        OVERRIDE: GattObject.get_property_map()
        BlueZ expects UUID, Service, Flags, and Notifying for GattCharacteristic1.
        Value is exposed via ReadValue/WriteValue, not here.
        """
        return {
            'UUID': dbus.String(self.uuid),
            'Service': dbus.ObjectPath(self.service.path),
            'Flags': dbus.Array([dbus.String(f) for f in self.flags], signature='s'),
            'Notifying': dbus.Boolean(self.notifying),
        }

    def get_managed_object(self):
        """
        OVERRIDE: GattObject.get_managed_object()
        Return this characteristic’s object entry, plus all of its descriptors.
        """
        obj = super().get_managed_object()
        for desc in self.descriptors:
            obj.update(desc.get_managed_object())
        return obj

    # ----------------------------------------------------------------------
    # BlueZ-facing D-Bus methods (specific to org.bluez.GattCharacteristic1)
    # ----------------------------------------------------------------------

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        """BlueZ calls this when the host reads the characteristic value."""
        logger.debug(f"{self.name}: ReadValue called, returning {self.value}")
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        """BlueZ calls this when the host writes to the characteristic."""
        self.value = [dbus.Byte(int(b) & 0xFF) for b in value]
        self.update_property('Value', dbus.Array(self.value, signature='y'))
        logger.debug(f"{self.name}: WriteValue called, new value {self.value}")

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StartNotify(self):
        """BlueZ calls this when the host subscribes to notifications."""
        self.set_notifying(True)

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StopNotify(self):
        """BlueZ calls this when the host unsubscribes from notifications."""
        self.set_notifying(False)

    # ----------------------------------------------------------------------
    # Internal helpers (Not called by BlueZ)
    # ----------------------------------------------------------------------

    def parse_byte(self, v):
        """
        Convert YAML values (int, hex string, decimal string) into an int (0–255).
        Stored as dbus.Byte when building self.value.
        """
        if isinstance(v, int):
            return v & 0xFF
        if isinstance(v, str):
            try:
                return int(v, 16) & 0xFF
            except ValueError:
                return int(v) & 0xFF
        return int(v) & 0xFF

    def set_notifying(self, enabled: bool):
        """
        Update the Notifying property and emit PropertiesChanged.
        Called internally and by StartNotify/StopNotify.
        """
        enabled = bool(enabled)
        if self.notifying != enabled:
            self.notifying = enabled
            self.update_property('Notifying', dbus.Boolean(self.notifying))
            logger.debug(f"{self.name}: Notifying set to {self.notifying}")

    def update_value(self, new_value_bytes):
        """
        Update the characteristic value and emit PropertiesChanged if changed.
        Called internally when input events update HID reports.
        """
        new_value = [dbus.Byte(int(v) & 0xFF) for v in new_value_bytes]
        if new_value == self.value:
            return  # No change
        self.value = new_value
        self.update_property('Value', dbus.Array(self.value, signature='y'))
        logger.debug(f"{self.name}: Value updated to {self.value}")


class HIDService(GattObject):
    """
    GATT Service object (org.bluez.GattService1).
    Exposes only service-level properties: UUID, Primary, Includes.
    Holds child characteristics and their descriptors.
    """
    dbus_interface = GATT_SERVICE_IFACE

    def __init__(self, bus, index, config):
        # --- Internal state ---
        self.uuid = str(config['uuid'])
        self.primary = bool(config.get('type', 'primary') == 'primary')
        self.characteristics = []

        includes_cfg = config.get('includes', [])
        self.includes = [dbus.ObjectPath(p) for p in includes_cfg] if includes_cfg else []

        # Deterministic service path under the app root
        self.path = f"{HID_SERVICE_BASE}{index}"
        super().__init__(bus, self.path)

        # Build child characteristics
        for i, char_cfg in enumerate(config.get('characteristics', [])):
            self.characteristics.append(HIDCharacteristic(bus, i, self, char_cfg))

        logger.debug(
            f"HIDService {self.uuid} initialized at {self.path} "
            f"with {len(self.characteristics)} characteristics"
        )

    # ----------------------------------------------------------------------
    # Overrides from GattObject
    # ----------------------------------------------------------------------

    def get_property_map(self):
        """
        OVERRIDE: GattObject.get_property_map()
        BlueZ expects UUID, Primary, and Includes for GattService1.
        """
        return {
            'UUID': dbus.String(self.uuid),
            'Primary': dbus.Boolean(self.primary),
            'Includes': dbus.Array(self.includes, signature='o'),
        }

    def get_managed_object(self):
        """
        OVERRIDE: GattObject.get_managed_object()
        Return this service’s object entry, plus all of its children
        (characteristics + descriptors).
        """
        obj = super().get_managed_object()
        for char in self.characteristics:
            obj.update(char.get_managed_object())
        return obj

    # ----------------------------------------------------------------------
    # BlueZ-facing D-Bus methods (specific to org.bluez.GattService1)
    # ----------------------------------------------------------------------

    @dbus.service.method(GATT_SERVICE_IFACE, in_signature='', out_signature='')
    def Release(self):
        """
        OPTIONAL BlueZ hook.
        Called if BlueZ ever wants to release this service.
        """
        logger.debug(f"Service {self.uuid} released at {self.path}")

    # ----------------------------------------------------------------------
    # Internal helpers (Not called by BlueZ)
    # ----------------------------------------------------------------------

    def find_characteristic(self, uuid):
        """
        Locate a child characteristic by UUID.
        Returns the characteristic object or None if not found.
        """
        for ch in self.characteristics:
            if ch.uuid.lower() == uuid.lower():
                return ch
        return None


class HIDApplication(dbus.service.Object):
    """
    HIDApplication implements org.freedesktop.DBus.ObjectManager.
    It acts as the container for all GATT services and exposes them
    to BlueZ via GetManagedObjects().
    """

    def __init__(self, bus, services, path=HID_APP_PATH):
        # --- Internal state ---
        self.path = path
        self.services = services
        super().__init__(bus, self.path)

        logger.debug(
            "HIDApplication initialized at %s with %d services",
            self.path, len(self.services)
        )

    # ----------------------------------------------------------------------
    # Implemented D-Bus ObjectManager interface (org.freedesktop.DBus.ObjectManager)
    # ----------------------------------------------------------------------

    @dbus.service.method(DBUS_OBJMGR_IFACE, in_signature='', out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        """
        BlueZ calls this to discover the full GATT hierarchy.
        Must return a{oa{sa{sv}}}:
          - dict keyed by object path
          - each value is a dict of interfaces
          - each interface maps to a dict of properties
        """
        response = {}
        for svc in self.services:
            # Each service returns a dict keyed by dbus.ObjectPath
            response.update(svc.get_managed_object())

        logger.debug("GetManagedObjects called, returning %d objects", len(response))
        return response

    @dbus.service.method(DBUS_OBJMGR_IFACE, in_signature='', out_signature='')
    def Release(self):
        """
        OPTIONAL: Cleanup hook if BlueZ ever calls Release on the application.
        """
        logger.debug(f"HIDApplication released at {self.path}")

    # ----------------------------------------------------------------------
    # Internal helpers (Not called by BlueZ)
    # ----------------------------------------------------------------------

    def add_service(self, service):
        """
        Add a new service to the application at runtime.
        """
        self.services.append(service)
        logger.debug(
            "Service %s added to HIDApplication at %s",
            getattr(service, 'uuid', 'unknown'), self.path
        )

    def remove_service(self, uuid):
        """
        Remove a service by UUID.
        """
        before = len(self.services)
        self.services = [s for s in self.services if s.uuid.lower() != uuid.lower()]
        after = len(self.services)
        logger.debug(
            "Service %s removed from HIDApplication at %s (before=%d, after=%d)",
            uuid, self.path, before, after
        )

    def find_service(self, uuid):
        """
        Locate a child service by UUID.
        Returns the service object or None if not found.
        """
        for svc in self.services:
            if svc.uuid.lower() == uuid.lower():
                return svc
        return None

    def list_services(self):
        """
        Return a list of all service UUIDs in this application.
        """
        return [svc.uuid for svc in self.services]

    @property
    def object_path(self):
        """
        Return the D-Bus object path for this application.
        """
        return dbus.ObjectPath(self.path)


def load_yaml_config(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)