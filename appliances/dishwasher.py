"""
dishwasher.py - Dishwasher appliance handler for Home Connect.
"""

import devices as dev
from appliances.base import BaseAppliance


OFFSET_PROGRAM   = 6
OFFSET_PROGRESS  = 7
OFFSET_FINISH    = 8
OFFSET_INTENSIV  = 9
OFFSET_BRILLIANCE = 10
OFFSET_VARIO     = 11


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


class DishwasherAppliance(BaseAppliance):
    """Handles Dishwasher Home Connect appliances."""

    SUPPORTED_TYPES = ("Dishwasher",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._programs = []          # list of full program key strings

    def create_devices(self, domoticz_devices):
        super().create_devices(domoticz_devices)

        if not self._programs:
            self._fetch_programs()
        prog_options = dev.make_selector_options(self._programs_short() or ["None"])
        dev.ensure_selector(domoticz_devices, self.u(OFFSET_PROGRAM), f"{self.name} - Active Program", prog_options)
        dev.ensure_percentage(domoticz_devices, self.u(OFFSET_PROGRESS), f"{self.name} - Program Progress")
        dev.ensure_text(domoticz_devices, self.u(OFFSET_FINISH), f"{self.name} - Program Finish Time")
        dev.ensure_switch(domoticz_devices, self.u(OFFSET_INTENSIV), f"{self.name} - Intensiv Zone")
        dev.ensure_switch(domoticz_devices, self.u(OFFSET_BRILLIANCE), f"{self.name} - Brilliance Dry")
        dev.ensure_switch(domoticz_devices, self.u(OFFSET_VARIO), f"{self.name} - Vario Speed Plus")

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

        elif key == "BSH.Common.Root.ActiveProgram":
            short = str(value).rsplit(".", 1)[-1]
            names = self._programs_short()
            if short in names:
                level = names.index(short) * 10
                dev.update_selector(domoticz_devices, self.u(OFFSET_PROGRAM), level)

        elif key == "Dishcare.Dishwasher.Option.IntensivZone":
            dev.update_switch(domoticz_devices, self.u(OFFSET_INTENSIV), _as_bool(value))

        elif key == "Dishcare.Dishwasher.Option.BrillianceDry":
            dev.update_switch(domoticz_devices, self.u(OFFSET_BRILLIANCE), _as_bool(value))

        elif key == "Dishcare.Dishwasher.Option.VarioSpeedPlus":
            dev.update_switch(domoticz_devices, self.u(OFFSET_VARIO), _as_bool(value))

        elif key == "BSH.Common.Event.ProgramFinished":
            self._alert(domoticz_devices, "Program finished.", level=1)

        elif key == "BSH.Common.Event.ProgramAborted":
            self._alert(domoticz_devices, "Program aborted.", level=3)

        elif key == "Dishcare.Dishwasher.Event.SaltNearlyEmpty":
            self._alert(domoticz_devices, "Salt nearly empty.", level=2)

        elif key == "Dishcare.Dishwasher.Event.RinseAidNearlyEmpty":
            self._alert(domoticz_devices, "Rinse aid nearly empty.", level=2)

        else:
            super()._handle_status_key(domoticz_devices, key, value)

    def _put_option(self, option_key, value):
        self.api.put(
            f"/api/homeappliances/{self.ha_id}/programs/active",
            {"data": {"options": [{"key": option_key, "value": value}]}},
        )

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

        elif offset == OFFSET_INTENSIV:
            self.log("HomeConnect: Intensiv Zone change requires restarting the program.")

        elif offset == OFFSET_BRILLIANCE:
            self.log("HomeConnect: Brilliance Dry change requires restarting the program.")

        elif offset == OFFSET_VARIO:
            self.log("HomeConnect: Vario Speed Plus change requires restarting the program.")

        else:
            super().handle_command(domoticz_devices, unit, command, level)

    def poll(self, domoticz_devices, connected: bool):
        super().poll(domoticz_devices, connected)
