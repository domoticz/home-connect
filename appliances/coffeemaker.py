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
_TEMP_NAMES  = ["88°C", "90°C", "92°C", "94°C", "95°C", "97°C"]
_TEMP_SUFFIXES = ["88C", "90C", "92C", "94C", "95C", "97C"]

_BEAN_LEVELS = {n: i * 10 for i, n in enumerate(_BEAN_NAMES)}
_TEMP_LEVELS = {s: i * 10 for i, s in enumerate(_TEMP_SUFFIXES)}

_BEAN_PREFIX = "ConsumerProducts.CoffeeMaker.EnumType.BeanAmount."
_TEMP_PREFIX = "ConsumerProducts.CoffeeMaker.EnumType.CoffeeTemperature."

_BEAN_API = {i * 10: n for i, n in enumerate(_BEAN_NAMES)}
_TEMP_API = {i * 10: s for i, s in enumerate(_TEMP_SUFFIXES)}


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

        elif key == "BSH.Common.Event.ProgramFinished":
            self._alert(domoticz_devices, "Beverage ready.", level=1)

        elif key == "ConsumerProducts.CoffeeMaker.Event.BeanContainerEmpty":
            self._alert(domoticz_devices, "Bean container empty.", level=3)

        elif key == "ConsumerProducts.CoffeeMaker.Event.WaterTankEmpty":
            self._alert(domoticz_devices, "Water tank empty.", level=3)

        elif key == "ConsumerProducts.CoffeeMaker.Event.DripTrayFull":
            self._alert(domoticz_devices, "Drip tray full.", level=3)

        elif key == "ConsumerProducts.CoffeeMaker.Event.DescalingNecessary":
            self._alert(domoticz_devices, "Descaling necessary.", level=2)

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
