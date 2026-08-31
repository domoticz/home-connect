"""
coffeemaker.py - CoffeeMaker appliance handler for Home Connect.
"""

import devices as dev
from appliances.base import BaseAppliance


OFFSET_PROGRAM      = 6
OFFSET_BEAN_AMOUNT  = 7
OFFSET_COFFEE_TEMP  = 8
OFFSET_COFFEE_COUNT = 9
OFFSET_HOTWATER_COUNT = 10

_BEAN_NAMES  = ["VeryMild", "Mild", "Normal", "Strong", "VeryStrong", "ExtraStrong"]
_TEMP_NAMES  = ["88Â°C", "90Â°C", "92Â°C", "94Â°C", "95Â°C", "97Â°C"]
_TEMP_SUFFIXES = ["88C", "90C", "92C", "94C", "95C", "97C"]

_BEAN_LEVELS = {n: i * 10 for i, n in enumerate(_BEAN_NAMES)}
_TEMP_LEVELS = {s: i * 10 for i, s in enumerate(_TEMP_SUFFIXES)}

_BEAN_PREFIX = "ConsumerProducts.CoffeeMaker.EnumType.BeanAmount."
_TEMP_PREFIX = "ConsumerProducts.CoffeeMaker.EnumType.CoffeeTemperature."

_BEAN_API = {i * 10: n for i, n in enumerate(_BEAN_NAMES)}
_TEMP_API = {i * 10: s for i, s in enumerate(_TEMP_SUFFIXES)}

_COFFEE_ALERT_EVENTS = {
    "BSH.Common.Event.ProgramFinished": ("Beverage ready.", 1),
    "ConsumerProducts.CoffeeMaker.Event.BeanContainerEmpty": ("Bean container empty.", 3),
    "ConsumerProducts.CoffeeMaker.Event.WaterTankEmpty": ("Water tank empty.", 3),
    "ConsumerProducts.CoffeeMaker.Event.DripTrayFull": ("Drip tray full.", 3),
    "ConsumerProducts.CoffeeMaker.Event.DescalingNecessary": ("Descaling necessary.", 2),
}

_ACTION_REQUIRED_ALERT_KEYS = frozenset({
    "ConsumerProducts.CoffeeMaker.Event.BeanContainerEmpty",
    "ConsumerProducts.CoffeeMaker.Event.WaterTankEmpty",
    "ConsumerProducts.CoffeeMaker.Event.DripTrayFull",
})
_ACTION_REQUIRED_CLEAR_STATES = frozenset({"Ready", "Inactive", "Running"})


def _event_is_present(value):
    if isinstance(value, bool):
        return value
    short = str(value).rsplit(".", 1)[-1].strip().lower()
    return short in ("present", "true", "1", "on")



class CoffeeMakerAppliance(BaseAppliance):
    """Handles CoffeeMaker Home Connect appliances."""

    SUPPORTED_TYPES = ("CoffeeMaker",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._programs = []  # list of full program key strings

    def _programs_short(self):
        return [k.rsplit(".", 1)[-1] for k in self._programs]

    def _fetch_programs(self):
        """Fetch available beverage programs from the API."""
        try:
            resp = self.api.get(f"/api/homeappliances/{self.ha_id}/programs/available")
            programs = resp.get("data", {}).get("programs", [])
            self._programs = [p["key"] for p in programs if "key" in p]
        except Exception as exc:
            self.log(f"HomeConnect: Could not fetch programs for {self.name}: {exc}")
            self._programs = []

    def _clear_action_required_alerts(self, domoticz_devices):
        """Home Connect doesn't reliably send an explicit "resolved" event for
        action-required conditions (empty tank/bean container, full drip tray) -
        the appliance just starts running again once they're fixed. So clear our
        tracked state for them here whenever OperationState returns to
        Ready/Inactive/Running, instead of waiting for an event that may never come.
        """
        for key in _ACTION_REQUIRED_ALERT_KEYS:
            if key in self._active_alerts:
                message, level = _COFFEE_ALERT_EVENTS[key]
                self._set_alert_state(domoticz_devices, key, False, message, level)

    def create_devices(self, domoticz_devices):
        super().create_devices(domoticz_devices)

        if not self._programs:
            self._fetch_programs()
        prog_options = dev.make_selector_options(self._programs_short() or ["None"])
        dev.ensure_selector(domoticz_devices, self.u(OFFSET_PROGRAM), f"{self.name} - Beverage Program", prog_options)
        dev.ensure_selector(domoticz_devices, self.u(OFFSET_BEAN_AMOUNT), f"{self.name} - Bean Amount",
                            dev.make_selector_options(_BEAN_NAMES))
        dev.ensure_selector(domoticz_devices, self.u(OFFSET_COFFEE_TEMP), f"{self.name} - Coffee Temperature",
                            dev.make_selector_options(_TEMP_NAMES))
        dev.ensure_custom(domoticz_devices, self.u(OFFSET_COFFEE_COUNT), f"{self.name} - Coffee Counter", "cups")
        dev.ensure_custom(domoticz_devices, self.u(OFFSET_HOTWATER_COUNT), f"{self.name} - Hot Water Counter", "cups")

    def _handle_status_key(self, domoticz_devices, key, value):
        if key in ("BSH.Common.Root.ActiveProgram", "BSH.Common.Root.SelectedProgram"):
            short = str(value).rsplit(".", 1)[-1]
            names = self._programs_short()
            if short in names:
                level = names.index(short) * 10
                dev.update_selector(domoticz_devices, self.u(OFFSET_PROGRAM), level)

        elif key == "ConsumerProducts.CoffeeMaker.Option.BeanAmount":
            short = str(value).rsplit(".", 1)[-1]
            level = _BEAN_LEVELS.get(short, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_BEAN_AMOUNT), level)

        elif key == "ConsumerProducts.CoffeeMaker.Option.CoffeeTemperature":
            short = str(value).rsplit(".", 1)[-1]
            level = _TEMP_LEVELS.get(short, 0)
            dev.update_selector(domoticz_devices, self.u(OFFSET_COFFEE_TEMP), level)

        elif key == "ConsumerProducts.CoffeeMaker.Status.BeverageCounterCoffee":
            dev.update_custom(domoticz_devices, self.u(OFFSET_COFFEE_COUNT), value)

        elif key == "ConsumerProducts.CoffeeMaker.Status.BeverageCounterHotWater":
            dev.update_custom(domoticz_devices, self.u(OFFSET_HOTWATER_COUNT), value)

        elif key in _COFFEE_ALERT_EVENTS:
            message, level = _COFFEE_ALERT_EVENTS[key]
            active = _event_is_present(value)
            self._set_alert_state(domoticz_devices, key, active, message, level)

        elif key == "BSH.Common.Status.OperationState":
            super()._handle_status_key(domoticz_devices, key, value)
            state = str(value).rsplit(".", 1)[-1]
            if state in _ACTION_REQUIRED_CLEAR_STATES:
                self._clear_action_required_alerts(domoticz_devices)

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

        elif offset == OFFSET_BEAN_AMOUNT:
            self.log("HomeConnect: Bean amount change requires restarting the program.")

        elif offset == OFFSET_COFFEE_TEMP:
            self.log("HomeConnect: Coffee temperature change requires restarting the program.")

        else:
            super().handle_command(domoticz_devices, unit, command, level)

    def poll(self, domoticz_devices, connected: bool):
        super().poll(domoticz_devices, connected)
