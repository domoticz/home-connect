"""
hood.py - Hood appliance handler for Home Connect.
"""

import devices as dev
from appliances.base import BaseAppliance


OFFSET_VENTING    = 6
OFFSET_INTENSIVE  = 7
OFFSET_FUNC_LIGHT = 8
OFFSET_AMB_LIGHT  = 9

_VENTING_NAMES  = ["FanOff", "Fan1", "Fan2", "Fan3", "Fan4", "Fan5"]
_INTENSIVE_NAMES = ["Off", "Intensive1", "Intensive2"]

_VENTING_LEVELS = {
    "FanOff": 0, "FanStage01": 10, "FanStage02": 20,
    "FanStage03": 30, "FanStage04": 40, "FanStage05": 50,
}
_VENTING_API = {v: k for k, v in _VENTING_LEVELS.items()}
_VENTING_PREFIX = "Cooking.Hood.EnumType.Stage."

_INTENSIVE_LEVELS = {"IntensiveStageOff": 0, "IntensiveStage1": 10, "IntensiveStage2": 20}
_INTENSIVE_API = {v: k for k, v in _INTENSIVE_LEVELS.items()}
_INTENSIVE_PREFIX = "Cooking.Hood.EnumType.IntensiveStage."


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


class HoodAppliance(BaseAppliance):
    """Handles Hood Home Connect appliances."""

    SUPPORTED_TYPES = ("Hood",)

    def create_devices(self, domoticz_devices):
        super().create_devices(domoticz_devices)

        dev.ensure_selector(domoticz_devices, self.u(OFFSET_VENTING), f"{self.name} - Venting Level",
                            dev.make_selector_options(_VENTING_NAMES))
        dev.ensure_selector(domoticz_devices, self.u(OFFSET_INTENSIVE), f"{self.name} - Intensive Level",
                            dev.make_selector_options(_INTENSIVE_NAMES))
        dev.ensure_switch(domoticz_devices, self.u(OFFSET_FUNC_LIGHT), f"{self.name} - Functional Light")
        dev.ensure_switch(domoticz_devices, self.u(OFFSET_AMB_LIGHT), f"{self.name} - Ambient Light")

    def _handle_status_key(self, domoticz_devices, key, value):
        if key == "Cooking.Common.Option.Hood.VentingLevel":
            short = str(value).rsplit(".", 1)[-1]
            level = _VENTING_LEVELS.get(short, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_VENTING), level)

        elif key == "Cooking.Common.Option.Hood.IntensiveLevel":
            short = str(value).rsplit(".", 1)[-1]
            level = _INTENSIVE_LEVELS.get(short, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_INTENSIVE), level)

        elif key == "BSH.Common.Setting.FunctionalLightEnabled":
            dev.update_switch(domoticz_devices, self.u(OFFSET_FUNC_LIGHT), _as_bool(value))

        elif key == "BSH.Common.Setting.AmbientLightEnabled":
            dev.update_switch(domoticz_devices, self.u(OFFSET_AMB_LIGHT), _as_bool(value))

        elif key == "Cooking.Hood.Event.GreaseFilterMaxSaturationNearlyReached":
            self._alert(domoticz_devices, "Grease filter nearly saturated.", level=2)

        elif key == "Cooking.Hood.Event.GreaseFilterMaxSaturationReached":
            self._alert(domoticz_devices, "Grease filter saturated - clean required.", level=4)

        else:
            super()._handle_status_key(domoticz_devices, key, value)

    def handle_command(self, domoticz_devices, unit, command, level):
        offset = unit - self.unit_base

        if offset == OFFSET_VENTING:
            suffix = _VENTING_API.get(level, "FanOff")
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/Cooking.Common.Option.Hood.VentingLevel",
                {"data": {"key": "Cooking.Common.Option.Hood.VentingLevel",
                          "value": f"{_VENTING_PREFIX}{suffix}"}},
            )

        elif offset == OFFSET_INTENSIVE:
            suffix = _INTENSIVE_API.get(level, "IntensiveStageOff")
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/Cooking.Common.Option.Hood.IntensiveLevel",
                {"data": {"key": "Cooking.Common.Option.Hood.IntensiveLevel",
                          "value": f"{_INTENSIVE_PREFIX}{suffix}"}},
            )

        elif offset == OFFSET_FUNC_LIGHT:
            value = "true" if command == "On" else "false"
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/BSH.Common.Setting.FunctionalLightEnabled",
                {"data": {"key": "BSH.Common.Setting.FunctionalLightEnabled", "value": value}},
            )

        elif offset == OFFSET_AMB_LIGHT:
            value = "true" if command == "On" else "false"
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/BSH.Common.Setting.AmbientLightEnabled",
                {"data": {"key": "BSH.Common.Setting.AmbientLightEnabled", "value": value}},
            )

        else:
            super().handle_command(domoticz_devices, unit, command, level)
