"""
oven.py - Oven, Microwave, and WarmingDrawer appliance handler for Home Connect.
"""

import devices as dev
from appliances.base import BaseAppliance


OFFSET_PROGRAM     = 6
OFFSET_PROGRESS    = 7
OFFSET_FINISH      = 8
OFFSET_CAVITY_TEMP = 9
OFFSET_SETPOINT    = 10
OFFSET_WARM_LEVEL  = 11
OFFSET_ALARM_CLOCK = 12

_WARMING_NAMES  = ["Low", "Medium", "High"]
_WARMING_LEVELS = {"Low": 0, "Medium": 10, "High": 20}
_WARMING_API    = {0: "Low", 10: "Medium", 20: "High"}
_WARMING_PREFIX = "Cooking.WarmingDrawer.EnumType.Level."


def _format_remaining(seconds):
    """Convert a seconds value to a human-readable duration string."""
    try:
        secs = int(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    if secs >= 3600:
        h = secs // 3600
        m = (secs % 3600) // 60
        return f"{h} h {m} min"
    return f"{secs // 60} min"


class OvenAppliance(BaseAppliance):
    """Handles Oven, Microwave, and WarmingDrawer Home Connect appliances."""

    SUPPORTED_TYPES = ("Oven", "Microwave", "WarmingDrawer")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._programs = []  # list of full program key strings

    def _programs_short(self):
        return [k.rsplit(".", 1)[-1] for k in self._programs]

    def _fetch_programs(self):
        """Fetch available programs from the API and populate self._programs."""
        try:
            resp = self.api.get(f"/api/homeappliances/{self.ha_id}/programs/available")
            programs = resp.get("data", {}).get("programs", [])
            self._programs = [p["key"] for p in programs if "key" in p]
        except Exception as exc:
            self.log(f"HomeConnect: Could not fetch programs for {self.name}: {exc}")
            self._programs = []

    def create_devices(self, domoticz_devices):
        super().create_devices(domoticz_devices)

        if not self._programs:
            self._fetch_programs()
        prog_options = dev.make_selector_options(self._programs_short() or ["None"])
        dev.ensure_selector(domoticz_devices, self.u(OFFSET_PROGRAM), f"{self.name} - Active Program", prog_options)
        dev.ensure_percentage(domoticz_devices, self.u(OFFSET_PROGRESS), f"{self.name} - Program Progress")
        dev.ensure_text(domoticz_devices, self.u(OFFSET_FINISH), f"{self.name} - Program Finish Time")
        dev.ensure_text(domoticz_devices, self.u(OFFSET_ALARM_CLOCK), f"{self.name} - Alarm Clock")

        if self.appliance_type in ("Oven", "Microwave"):
            dev.ensure_temperature(domoticz_devices, self.u(OFFSET_CAVITY_TEMP), f"{self.name} - Cavity Temperature")

        if self.appliance_type == "Oven":
            dev.ensure_custom(domoticz_devices, self.u(OFFSET_SETPOINT), f"{self.name} - Setpoint Temperature", "°C")

        if self.appliance_type == "WarmingDrawer":
            dev.ensure_selector(domoticz_devices, self.u(OFFSET_WARM_LEVEL), f"{self.name} - Warming Level",
                                dev.make_selector_options(_WARMING_NAMES))

    def _handle_status_key(self, domoticz_devices, key, value):
        if key == "BSH.Common.Option.ProgramProgress":
            try:
                dev.update_percentage(domoticz_devices, self.u(OFFSET_PROGRESS), float(value))
            except (TypeError, ValueError):
                pass

        elif key == "BSH.Common.Option.RemainingProgramTime":
            dev.update_text(domoticz_devices, self.u(OFFSET_FINISH), _format_remaining(value))

        elif key in ("BSH.Common.Root.ActiveProgram", "BSH.Common.Root.SelectedProgram"):
            short = str(value).rsplit(".", 1)[-1]
            names = self._programs_short()
            if short in names:
                level = names.index(short) * 10
                dev.update_selector(domoticz_devices, self.u(OFFSET_PROGRAM), level)

        elif key == "Cooking.Oven.Status.CurrentCavityTemperature" and self.appliance_type in ("Oven", "Microwave"):
            try:
                dev.update_temperature(domoticz_devices, self.u(OFFSET_CAVITY_TEMP), float(value))
            except (TypeError, ValueError):
                pass

        elif key == "Cooking.Oven.Option.SetpointTemperature" and self.appliance_type == "Oven":
            try:
                dev.update_custom(domoticz_devices, self.u(OFFSET_SETPOINT), int(float(value)))
            except (TypeError, ValueError):
                pass

        elif key == "Cooking.WarmingDrawer.Option.Level" and self.appliance_type == "WarmingDrawer":
            short = str(value).rsplit(".", 1)[-1]
            level = _WARMING_LEVELS.get(short, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_WARM_LEVEL), level)

        elif key == "BSH.Common.Option.AlarmClock":
            dev.update_text(domoticz_devices, self.u(OFFSET_ALARM_CLOCK), _format_remaining(value))

        elif key == "BSH.Common.Event.ProgramFinished":
            self._alert(domoticz_devices, "Program finished.", level=1)

        elif key == "Cooking.Oven.Event.PreheatFinished":
            self._alert(domoticz_devices, "Preheat finished.", level=1)

        elif key == "BSH.Common.Event.AlarmClockElapsed":
            self._alert(domoticz_devices, "Alarm clock elapsed.", level=1)

        else:
            super()._handle_status_key(domoticz_devices, key, value)

    def handle_command(self, domoticz_devices, unit, command, level):
        offset = unit - self.unit_base

        if offset == OFFSET_PROGRAM:
            idx = level // 10
            if 0 <= idx < len(self._programs):
                full_key = self._programs[idx]
                self.api.put(
                    f"/api/homeappliances/{self.ha_id}/programs/active",
                    {"data": {"key": full_key}},
                )
            else:
                self.log(f"HomeConnect: Invalid program index {idx} for {self.name}.")

        elif offset == OFFSET_SETPOINT and self.appliance_type == "Oven":
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/Cooking.Oven.Option.SetpointTemperature",
                {"data": {"key": "Cooking.Oven.Option.SetpointTemperature",
                          "value": int(level), "unit": "°C"}},
            )

        elif offset == OFFSET_WARM_LEVEL and self.appliance_type == "WarmingDrawer":
            suffix = _WARMING_API.get(level, "Low")
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/Cooking.WarmingDrawer.Option.Level",
                {"data": {"key": "Cooking.WarmingDrawer.Option.Level",
                          "value": f"{_WARMING_PREFIX}{suffix}"}},
            )

        else:
            super().handle_command(domoticz_devices, unit, command, level)

    def poll(self, domoticz_devices, connected: bool):
        super().poll(domoticz_devices, connected)
