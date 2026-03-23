"""
base.py - Base appliance class for Home Connect devices.
"""

import Domoticz
import devices as dev


def _effective_log_level(mode: int) -> int:
    if mode in (3, 4):
        return 2
    return mode


def _safe_float(value, default: float = 0.0) -> float:
    """Convert value to float, falling back to default on empty or invalid input."""
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        return default


# Unit offsets within each appliance block
OFFSET_CONNECTION = 0
OFFSET_POWER      = 1
OFFSET_OPERATION  = 2
OFFSET_DOOR       = 3
OFFSET_REMOTE     = 4
OFFSET_CHILDLOCK  = 5
OFFSET_ALERT      = 18
OFFSET_ENERGY     = 19

# Which base devices each appliance type supports
# (power, operation, door, remote, childlock)
APPLIANCE_CAPS = {
    "Washer":        (True,  True,  True,  True,  True),
    "Dryer":         (True,  True,  True,  True,  True),
    "WasherDryer":   (True,  True,  True,  True,  True),
    "Dishwasher":    (True,  True,  True,  True,  True),
    "Oven":          (True,  True,  True,  True,  True),
    "Microwave":     (True,  True,  True,  True,  True),
    "CoffeeMaker":   (True,  True,  False, True,  True),
    "Hood":          (True,  False, False, True,  True),
    "CleaningRobot": (True,  True,  False, True,  False),
    "Refrigerator":  (True,  False, True,  False, False),
    "FridgeFreezer": (True,  False, True,  False, False),
    "Freezer":       (True,  False, True,  False, False),
}


class BaseAppliance:
    """Represents one Home Connect appliance and its Domoticz devices."""

    def __init__(self, ha_id, name, appliance_type, unit_base, api, debug_mode=0, log_fn=print):
        self.ha_id = ha_id
        self.name = name
        self.appliance_type = appliance_type
        self.unit_base = unit_base
        self.api = api
        self.debug_mode = debug_mode
        self.log = log_fn
        self.connected = False
        self._watts = 0.0
        self._total_wh = 0.0

    def u(self, offset):
        """Return the Domoticz unit number for a given offset."""
        return self.unit_base + offset

    def _alert(self, domoticz_devices, message, level=4):
        """Update the Alert sensor device and log the message.
        level: 0=grey, 1=green, 2=yellow, 3=orange, 4=red (default).
        """
        dev.update_alert(domoticz_devices, self.u(OFFSET_ALERT), level, message)
        self.log(f"HomeConnect: {self.name} - {message}")

    def create_devices(self, domoticz_devices):
        """Create all base devices for this appliance. Call super() first in subclasses."""
        caps = APPLIANCE_CAPS.get(self.appliance_type, (True, True, True, True, True))
        has_power, has_operation, has_door, has_remote, has_childlock = caps

        dev.ensure_switch(domoticz_devices, self.u(OFFSET_CONNECTION), f"{self.name} - Connection")
        dev.ensure_alert(domoticz_devices, self.u(OFFSET_ALERT), f"{self.name} - Alert")

        if has_power:
            dev.ensure_selector(domoticz_devices, self.u(OFFSET_POWER), f"{self.name} - Power", dev.POWER_OPTIONS)
        if has_operation:
            dev.ensure_selector(domoticz_devices, self.u(OFFSET_OPERATION), f"{self.name} - Operation", dev.OPERATION_OPTIONS)
        if has_door:
            dev.ensure_contact(domoticz_devices, self.u(OFFSET_DOOR), f"{self.name} - Door")
        if has_remote:
            dev.ensure_switch(domoticz_devices, self.u(OFFSET_REMOTE), f"{self.name} - Remote Control")
        if has_childlock:
            dev.ensure_switch(domoticz_devices, self.u(OFFSET_CHILDLOCK), f"{self.name} - Child Lock")

    def update_from_status(self, domoticz_devices, status_list):
        """
        Process a list of status items from GET /api/homeappliances/{haId}/status.
        Each item: {"key": "BSH.Common.Status.OperationState", "value": "BSH.Common.EnumType.OperationState.Ready"}
        """
        for item in status_list:
            key = item.get("key", "")
            value = item.get("value", "")
            self._handle_status_key(domoticz_devices, key, value)

    def handle_event(self, domoticz_devices, event_key, value):
        """Handle a single SSE event key/value pair."""
        self._handle_status_key(domoticz_devices, event_key, value)

    def _handle_status_key(self, domoticz_devices, key, value):
        """Map a Home Connect status key to a device update."""
        caps = APPLIANCE_CAPS.get(self.appliance_type, (True, True, True, True, True))
        has_power, has_operation, has_door, has_remote, has_childlock = caps

        if key == "BSH.Common.Status.OperationState" and has_operation:
            # e.g. "BSH.Common.EnumType.OperationState.Ready" -> "Ready"
            state = value.rsplit(".", 1)[-1]
            level = dev.OPERATION_LEVELS.get(state, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_OPERATION), level)

        elif key in ("BSH.Common.Setting.PowerState", "BSH.Common.Status.PowerState") and has_power:
            state = value.rsplit(".", 1)[-1]
            level = dev.POWER_LEVELS.get(state, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_POWER), level)

        elif key == "BSH.Common.Status.DoorState" and has_door:
            is_open = value.rsplit(".", 1)[-1].lower() == "open"
            dev.update_contact(domoticz_devices, self.u(OFFSET_DOOR), is_open)

        elif key == "BSH.Common.Status.RemoteControlActive" and has_remote:
            dev.update_switch(domoticz_devices, self.u(OFFSET_REMOTE), bool(value))

        elif key == "BSH.Common.Setting.ChildLock" and has_childlock:
            dev.update_switch(domoticz_devices, self.u(OFFSET_CHILDLOCK), bool(value))

        elif key == "BSH.Common.Status.CurrentEnergyConsumption":
            self._watts = _safe_float(value)
            dev.ensure_kwh(domoticz_devices, self.u(OFFSET_ENERGY), f"{self.name} - Energy")
            dev.update_kwh(domoticz_devices, self.u(OFFSET_ENERGY), self._watts, self._total_wh)

        elif key == "BSH.Common.Status.TotalEnergyConsumption":
            self._total_wh = _safe_float(value)
            dev.ensure_kwh(domoticz_devices, self.u(OFFSET_ENERGY), f"{self.name} - Energy")
            dev.update_kwh(domoticz_devices, self.u(OFFSET_ENERGY), self._watts, self._total_wh)

    def handle_command(self, domoticz_devices, unit, command, level):
        """Handle a Domoticz device command (e.g. switch on/off)."""
        offset = unit - self.unit_base

        if offset == OFFSET_CHILDLOCK:
            value = "true" if command == "On" else "false"
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/BSH.Common.Setting.ChildLock",
                {"data": {"key": "BSH.Common.Setting.ChildLock", "value": value}},
            )

        elif offset == OFFSET_POWER:
            # Level 0=Off, 10=On, 20=Standby
            level_map = {0: "Off", 10: "On", 20: "Standby"}
            state = level_map.get(level, "Off")
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/BSH.Common.Setting.PowerState",
                {"data": {"key": "BSH.Common.Setting.PowerState",
                          "value": f"BSH.Common.EnumType.PowerState.{state}"}},
            )

    def poll(self, domoticz_devices, connected: bool):
        """Poll current status and settings from the API and update devices."""
        dev.update_switch(domoticz_devices, self.u(OFFSET_CONNECTION), connected)

        if not connected:
            return

        # Status endpoint: OperationState, DoorState, RemoteControlActive, etc.
        resp = self.api.get(f"/api/homeappliances/{self.ha_id}/status")
        status_list = resp.get("data", {}).get("status", [])
        if status_list:
            self.update_from_status(domoticz_devices, status_list)
        elif _effective_log_level(self.debug_mode) >= 2:
            self.log(f"HomeConnect: No status items for {self.name}.")

        # Settings endpoint: PowerState, ChildLock, etc.
        resp = self.api.get(f"/api/homeappliances/{self.ha_id}/settings")
        settings_list = resp.get("data", {}).get("settings", [])
        if settings_list:
            self.update_from_status(domoticz_devices, settings_list)
        elif _effective_log_level(self.debug_mode) >= 2:
            self.log(f"HomeConnect: No settings items for {self.name}.")
