"""
refrigerator.py - Refrigerator, FridgeFreezer, and Freezer appliance handler for Home Connect.
"""

import devices as dev
from appliances.base import BaseAppliance, OFFSET_DOOR


OFFSET_FRIDGE_TEMP    = 6
OFFSET_FRIDGE_SET     = 7
OFFSET_FREEZER_TEMP   = 8
OFFSET_FREEZER_SET    = 9
OFFSET_FREEZER_DOOR   = 10
OFFSET_SUPER_COOL     = 11
OFFSET_SUPER_FREEZE   = 12
OFFSET_ECO            = 13
OFFSET_VACATION       = 14


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


class RefrigeratorAppliance(BaseAppliance):
    """Handles Refrigerator, FridgeFreezer, and Freezer Home Connect appliances."""

    SUPPORTED_TYPES = ("Refrigerator", "FridgeFreezer", "Freezer")

    def _has_fridge(self):
        return self.appliance_type in ("Refrigerator", "FridgeFreezer")

    def _has_freezer(self):
        return self.appliance_type in ("Freezer", "FridgeFreezer")

    def _is_combo(self):
        return self.appliance_type == "FridgeFreezer"

    def create_devices(self, domoticz_devices):
        super().create_devices(domoticz_devices)

        if self._has_fridge():
            dev.ensure_temperature(domoticz_devices, self.u(OFFSET_FRIDGE_TEMP), f"{self.name} - Fridge Temperature")
            dev.ensure_custom(domoticz_devices, self.u(OFFSET_FRIDGE_SET), f"{self.name} - Fridge Setpoint", "°C")

        if self._has_freezer():
            dev.ensure_temperature(domoticz_devices, self.u(OFFSET_FREEZER_TEMP), f"{self.name} - Freezer Temperature")
            dev.ensure_custom(domoticz_devices, self.u(OFFSET_FREEZER_SET), f"{self.name} - Freezer Setpoint", "°C")

        if self._is_combo():
            dev.ensure_contact(domoticz_devices, self.u(OFFSET_FREEZER_DOOR), f"{self.name} - Freezer Door")

        if self._has_fridge():
            dev.ensure_switch(domoticz_devices, self.u(OFFSET_SUPER_COOL), f"{self.name} - Super Cool")

        if self._has_freezer():
            dev.ensure_switch(domoticz_devices, self.u(OFFSET_SUPER_FREEZE), f"{self.name} - Super Freeze")

        dev.ensure_switch(domoticz_devices, self.u(OFFSET_ECO), f"{self.name} - Eco Mode")
        dev.ensure_switch(domoticz_devices, self.u(OFFSET_VACATION), f"{self.name} - Vacation Mode")

    def _handle_status_key(self, domoticz_devices, key, value):
        if key == "Refrigeration.FridgeFreezer.Status.DoorRefrigerator":
            is_open = str(value).rsplit(".", 1)[-1].lower() == "open"
            dev.update_contact(domoticz_devices, self.u(OFFSET_DOOR), is_open)

        elif key == "Refrigeration.FridgeFreezer.Status.DoorFreezer":
            is_open = str(value).rsplit(".", 1)[-1].lower() == "open"
            dev.update_contact(domoticz_devices, self.u(OFFSET_FREEZER_DOOR), is_open)

        elif key == "Refrigeration.FridgeFreezer.Setting.SetpointTemperatureRefrigerator":
            try:
                dev.update_custom(domoticz_devices, self.u(OFFSET_FRIDGE_SET), int(float(value)))
            except (TypeError, ValueError):
                pass

        elif key == "Refrigeration.Refrigerator.Setting.SetpointTemperature":
            try:
                dev.update_custom(domoticz_devices, self.u(OFFSET_FRIDGE_SET), int(float(value)))
            except (TypeError, ValueError):
                pass

        elif key == "Refrigeration.FridgeFreezer.Setting.SetpointTemperatureFreezer":
            try:
                dev.update_custom(domoticz_devices, self.u(OFFSET_FREEZER_SET), int(float(value)))
            except (TypeError, ValueError):
                pass

        elif key == "Refrigeration.Freezer.Setting.SetpointTemperature":
            try:
                dev.update_custom(domoticz_devices, self.u(OFFSET_FREEZER_SET), int(float(value)))
            except (TypeError, ValueError):
                pass

        elif key == "Refrigeration.FridgeFreezer.Setting.SuperCoolingMode":
            dev.update_switch(domoticz_devices, self.u(OFFSET_SUPER_COOL), _as_bool(value))

        elif key == "Refrigeration.FridgeFreezer.Setting.SuperFreezing":
            dev.update_switch(domoticz_devices, self.u(OFFSET_SUPER_FREEZE), _as_bool(value))

        elif key == "Refrigeration.FridgeFreezer.Setting.EcoMode":
            dev.update_switch(domoticz_devices, self.u(OFFSET_ECO), _as_bool(value))

        elif key == "Refrigeration.FridgeFreezer.Setting.VacationMode":
            dev.update_switch(domoticz_devices, self.u(OFFSET_VACATION), _as_bool(value))

        elif key == "Refrigeration.FridgeFreezer.Event.DoorAlarmRefrigerator":
            self._alert(domoticz_devices, "Refrigerator door open too long.", level=3)

        elif key == "Refrigeration.FridgeFreezer.Event.DoorAlarmFreezer":
            self._alert(domoticz_devices, "Freezer door open too long.", level=3)

        elif key == "Refrigeration.FridgeFreezer.Event.TemperatureAlarmFreezer":
            self._alert(domoticz_devices, "Freezer temperature too high.", level=4)

        else:
            super()._handle_status_key(domoticz_devices, key, value)

    def handle_command(self, domoticz_devices, unit, command, level):
        offset = unit - self.unit_base

        if offset == OFFSET_FRIDGE_SET:
            if self._is_combo():
                setting_key = "Refrigeration.FridgeFreezer.Setting.SetpointTemperatureRefrigerator"
            else:
                setting_key = "Refrigeration.Refrigerator.Setting.SetpointTemperature"
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/{setting_key}",
                {"data": {"key": setting_key, "value": int(level), "unit": "°C"}},
            )

        elif offset == OFFSET_FREEZER_SET:
            if self._is_combo():
                setting_key = "Refrigeration.FridgeFreezer.Setting.SetpointTemperatureFreezer"
            else:
                setting_key = "Refrigeration.Freezer.Setting.SetpointTemperature"
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/{setting_key}",
                {"data": {"key": setting_key, "value": int(level), "unit": "°C"}},
            )

        elif offset == OFFSET_SUPER_COOL:
            value = "true" if command == "On" else "false"
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/Refrigeration.FridgeFreezer.Setting.SuperCoolingMode",
                {"data": {"key": "Refrigeration.FridgeFreezer.Setting.SuperCoolingMode", "value": value}},
            )

        elif offset == OFFSET_SUPER_FREEZE:
            value = "true" if command == "On" else "false"
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/Refrigeration.FridgeFreezer.Setting.SuperFreezing",
                {"data": {"key": "Refrigeration.FridgeFreezer.Setting.SuperFreezing", "value": value}},
            )

        elif offset == OFFSET_ECO:
            value = "true" if command == "On" else "false"
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/Refrigeration.FridgeFreezer.Setting.EcoMode",
                {"data": {"key": "Refrigeration.FridgeFreezer.Setting.EcoMode", "value": value}},
            )

        elif offset == OFFSET_VACATION:
            value = "true" if command == "On" else "false"
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/Refrigeration.FridgeFreezer.Setting.VacationMode",
                {"data": {"key": "Refrigeration.FridgeFreezer.Setting.VacationMode", "value": value}},
            )

        else:
            super().handle_command(domoticz_devices, unit, command, level)
