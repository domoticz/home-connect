"""
robot.py - CleaningRobot appliance handler for Home Connect.
"""

import devices as dev
from appliances.base import BaseAppliance


OFFSET_PROGRAM       = 6
OFFSET_CLEAN_MODE    = 7
OFFSET_DUST_BOX      = 8
OFFSET_LIFTED        = 9

_CLEANING_MODE_NAMES  = ["Silent", "Standard", "Power"]
_CLEANING_MODE_LEVELS = {"Silent": 0, "Standard": 10, "Power": 20}
_CLEANING_MODE_API    = {0: "Silent", 10: "Standard", 20: "Power"}
_CLEANING_MODE_PREFIX = "BSH.Common.EnumType.CleaningMode."

_ROBOT_PROGRAMS = [
    ("CleanAll", "ConsumerProducts.CleaningRobot.Program.Cleaning.CleanAll"),
    ("GoHome",   "ConsumerProducts.CleaningRobot.Program.Basic.GoHome"),
]


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


class CleaningRobotAppliance(BaseAppliance):
    """Handles CleaningRobot Home Connect appliances."""

    SUPPORTED_TYPES = ("CleaningRobot",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._programs = list(_ROBOT_PROGRAMS)  # list of (short_name, full_key) tuples

    def _programs_short(self):
        return [name for name, _ in self._programs]

    def _programs_keys(self):
        return [key for _, key in self._programs]

    def create_devices(self, domoticz_devices):
        super().create_devices(domoticz_devices)

        prog_options = dev.make_selector_options(self._programs_short())
        dev.ensure_selector(domoticz_devices, self.u(OFFSET_PROGRAM), f"{self.name} - Cleaning Program", prog_options)
        dev.ensure_selector(domoticz_devices, self.u(OFFSET_CLEAN_MODE), f"{self.name} - Cleaning Mode",
                            dev.make_selector_options(_CLEANING_MODE_NAMES))
        dev.ensure_switch(domoticz_devices, self.u(OFFSET_DUST_BOX), f"{self.name} - Dust Box Inserted")
        dev.ensure_switch(domoticz_devices, self.u(OFFSET_LIFTED), f"{self.name} - Robot Lifted")

    def _handle_status_key(self, domoticz_devices, key, value):
        if key in ("BSH.Common.Root.ActiveProgram", "BSH.Common.Root.SelectedProgram"):
            short = str(value).rsplit(".", 1)[-1]
            names = self._programs_short()
            if short in names:
                level = names.index(short) * 10
                dev.update_selector(domoticz_devices, self.u(OFFSET_PROGRAM), level)

        elif key == "BSH.Common.Option.CleaningMode":
            short = str(value).rsplit(".", 1)[-1]
            level = _CLEANING_MODE_LEVELS.get(short, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_CLEAN_MODE), level)

        elif key == "ConsumerProducts.CleaningRobot.Status.DustBoxInserted":
            dev.update_switch(domoticz_devices, self.u(OFFSET_DUST_BOX), _as_bool(value))

        elif key == "ConsumerProducts.CleaningRobot.Status.Lifted":
            dev.update_switch(domoticz_devices, self.u(OFFSET_LIFTED), _as_bool(value))

        elif key == "BSH.Common.Event.ProgramFinished":
            self._alert(domoticz_devices, "Cleaning finished.", level=1)

        elif key == "ConsumerProducts.CleaningRobot.Event.EmptyDustBox":
            self._alert(domoticz_devices, "Empty dust box.", level=3)

        elif key == "ConsumerProducts.CleaningRobot.Event.CleanFilter":
            self._alert(domoticz_devices, "Clean filter.", level=3)

        elif key == "ConsumerProducts.CleaningRobot.Event.RobotIsStuck":
            self._alert(domoticz_devices, "Robot is stuck.", level=4)

        elif key == "ConsumerProducts.CleaningRobot.Event.Docked":
            self._alert(domoticz_devices, "Robot docked.", level=1)

        else:
            super()._handle_status_key(domoticz_devices, key, value)

    def handle_command(self, domoticz_devices, unit, command, level):
        offset = unit - self.unit_base

        if offset == OFFSET_PROGRAM:
            idx = level // 10
            keys = self._programs_keys()
            if 0 <= idx < len(keys):
                self.api.put(
                    f"/api/homeappliances/{self.ha_id}/programs/active",
                    {"data": {"key": keys[idx]}},
                )
            else:
                self.log(f"HomeConnect: Invalid program index {idx} for {self.name}.")

        elif offset == OFFSET_CLEAN_MODE:
            suffix = _CLEANING_MODE_API.get(level, "Standard")
            self.api.put(
                f"/api/homeappliances/{self.ha_id}/settings/BSH.Common.Option.CleaningMode",
                {"data": {"key": "BSH.Common.Option.CleaningMode",
                          "value": f"{_CLEANING_MODE_PREFIX}{suffix}"}},
            )

        else:
            super().handle_command(domoticz_devices, unit, command, level)
