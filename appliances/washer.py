"""
washer.py - Washer, Dryer, and WasherDryer appliance handler for Home Connect.
"""

import devices as dev
from appliances.base import BaseAppliance


OFFSET_PROGRAM   = 6
OFFSET_PROGRESS  = 7
OFFSET_FINISH    = 8
OFFSET_TEMP      = 9
OFFSET_SPIN      = 10
OFFSET_DRY       = 11

_TEMP_NAMES  = ["Cold", "C20", "C30", "C40", "C60", "C90", "GentleWash40"]
_SPIN_NAMES  = ["Off", "RPM400", "RPM600", "RPM800", "RPM1000", "RPM1200", "RPM1400", "RPM1600"]
_DRY_NAMES   = ["IronDry", "GentleDry", "CupboardDry", "ExtraDry"]

_TEMP_LEVELS = {n: i * 10 for i, n in enumerate(_TEMP_NAMES)}
_SPIN_LEVELS = {n: i * 10 for i, n in enumerate(_SPIN_NAMES)}
_DRY_LEVELS  = {n: i * 10 for i, n in enumerate(_DRY_NAMES)}

_TEMP_PREFIX = "LaundryCare.Washer.EnumType.Temperature."
_SPIN_PREFIX = "LaundryCare.Washer.EnumType.SpinSpeed."
_DRY_PREFIX  = "LaundryCare.Dryer.EnumType.DryingTarget."


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


def _as_bool(value):
    """Normalise API bool values (Python bool or 'true'/'false' string)."""
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


class WasherAppliance(BaseAppliance):
    """Handles Washer, Dryer, and WasherDryer Home Connect appliances."""

    SUPPORTED_TYPES = ("Washer", "Dryer", "WasherDryer")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._programs = []          # list of full program key strings

    def _has_wash(self):
        return self.appliance_type in ("Washer", "WasherDryer")

    def _has_dry(self):
        return self.appliance_type in ("Dryer", "WasherDryer")

    def create_devices(self, domoticz_devices):
        super().create_devices(domoticz_devices)

        if not self._programs:
            self._fetch_programs()
        prog_options = dev.make_selector_options(self._programs_short() or ["None"])
        dev.ensure_selector(domoticz_devices, self.u(OFFSET_PROGRAM), f"{self.name} - Active Program", prog_options)
        dev.ensure_percentage(domoticz_devices, self.u(OFFSET_PROGRESS), f"{self.name} - Program Progress")
        dev.ensure_text(domoticz_devices, self.u(OFFSET_FINISH), f"{self.name} - Program Finish Time")

        if self._has_wash():
            dev.ensure_selector(domoticz_devices, self.u(OFFSET_TEMP), f"{self.name} - Wash Temperature",
                                dev.make_selector_options(_TEMP_NAMES))
            dev.ensure_selector(domoticz_devices, self.u(OFFSET_SPIN), f"{self.name} - Spin Speed",
                                dev.make_selector_options(_SPIN_NAMES))
        if self._has_dry():
            dev.ensure_selector(domoticz_devices, self.u(OFFSET_DRY), f"{self.name} - Drying Target",
                                dev.make_selector_options(_DRY_NAMES))

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

    def _handle_status_key(self, domoticz_devices, key, value):
        if key == "BSH.Common.Option.RemainingProgramTime":
            dev.update_text(domoticz_devices, self.u(OFFSET_FINISH), _format_remaining(value))

        elif key == "BSH.Common.Option.ProgramProgress":
            try:
                dev.update_percentage(domoticz_devices, self.u(OFFSET_PROGRESS), float(value))
            except (TypeError, ValueError):
                pass

        elif key == "LaundryCare.Washer.Option.Temperature" and self._has_wash():
            short = str(value).rsplit(".", 1)[-1]
            level = _TEMP_LEVELS.get(short, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_TEMP), level)

        elif key == "LaundryCare.Washer.Option.SpinSpeed" and self._has_wash():
            short = str(value).rsplit(".", 1)[-1]
            level = _SPIN_LEVELS.get(short, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_SPIN), level)

        elif key == "LaundryCare.Dryer.Option.DryingTarget" and self._has_dry():
            short = str(value).rsplit(".", 1)[-1]
            level = _DRY_LEVELS.get(short, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_DRY), level)

        elif key in ("BSH.Common.Root.ActiveProgram", "BSH.Common.Root.SelectedProgram"):
            short = str(value).rsplit(".", 1)[-1]
            names = self._programs_short()
            if short in names:
                level = names.index(short) * 10
                dev.update_selector(domoticz_devices, self.u(OFFSET_PROGRAM), level)

        elif key == "BSH.Common.Event.ProgramFinished":
            self._alert(domoticz_devices, "Program finished.", level=1)

        elif key == "BSH.Common.Event.ProgramAborted":
            self._alert(domoticz_devices, "Program aborted.", level=3)

        elif key == "LaundryCare.Common.Event.LoadRecommendation.CleanMachine":
            self._alert(domoticz_devices, "Clean machine recommended.", level=2)

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

        elif offset == OFFSET_TEMP and self._has_wash():
            self.log("HomeConnect: Temperature change requires restarting the program.")

        elif offset == OFFSET_SPIN and self._has_wash():
            self.log("HomeConnect: Spin speed change requires restarting the program.")

        elif offset == OFFSET_DRY and self._has_dry():
            self.log("HomeConnect: Drying target change requires restarting the program.")

        else:
            super().handle_command(domoticz_devices, unit, command, level)

    def poll(self, domoticz_devices, connected: bool):
        super().poll(domoticz_devices, connected)
