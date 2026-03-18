# Copyright (c) 2025 GizMoCuz (Domoticz) - SPDX-License-Identifier: MIT
"""
devices.py - Helper functions for creating and updating Domoticz devices
            for the Home Connect plugin.
"""

import Domoticz


def _effective_log_level(mode: int) -> int:
    if mode in (3, 4):
        return 2
    return mode


# Selector switch Options dicts
POWER_OPTIONS = {
    "LevelActions": "||",
    "LevelNames": "Off|On|Standby",
    "LevelOffHidden": "false",
    "SelectorStyle": "0",
}

OPERATION_OPTIONS = {
    "LevelActions": "||||||||",
    "LevelNames": "Inactive|Ready|DelayedStart|Running|Paused|ActionRequired|Finished|Error|Aborting",
    "LevelOffHidden": "false",
    "SelectorStyle": "1",
}

# Maps state string -> selector level value (multiples of 10)
POWER_LEVELS = {"Off": 0, "On": 10, "Standby": 20}
OPERATION_LEVELS = {
    "Inactive": 0,
    "Ready": 10,
    "DelayedStart": 20,
    "Running": 30,
    "Paused": 40,
    "ActionRequired": 50,
    "Finished": 60,
    "Error": 70,
    "Aborting": 80,
}


# ---------------------------------------------------------------------------
# Device creation helpers
# ---------------------------------------------------------------------------

def ensure_switch(devices, unit, name):
    """Create a Switch device for *unit* if it does not already exist."""
    if unit not in devices:
        Domoticz.Device(Name=name, Unit=unit, TypeName="Switch").Create()


def ensure_selector(devices, unit, name, options):
    """Create a Selector Switch device for *unit* if it does not already exist."""
    if unit not in devices:
        Domoticz.Device(Name=name, Unit=unit, TypeName="Selector Switch", Options=options).Create()


def ensure_contact(devices, unit, name):
    """Create a Contact Sensor device for *unit* if it does not already exist."""
    if unit not in devices:
        Domoticz.Device(Name=name, Unit=unit, TypeName="Contact").Create()


def ensure_kwh(devices, unit, name):
    """Create a kWh electricity meter device if it does not already exist."""
    if unit not in devices:
        Domoticz.Device(Name=name, Unit=unit, Type=243, Subtype=29, Switchtype=0).Create()


def ensure_temperature(devices, unit, name):
    """Create a Temperature sensor device if it does not already exist."""
    if unit not in devices:
        Domoticz.Device(Name=name, Unit=unit, TypeName="Temperature").Create()


def ensure_text(devices, unit, name):
    """Create a Text device if it does not already exist."""
    if unit not in devices:
        Domoticz.Device(Name=name, Unit=unit, TypeName="Text").Create()


def ensure_alert(devices, unit, name):
    """Create an Alert sensor device if it does not already exist."""
    if unit not in devices:
        Domoticz.Device(Name=name, Unit=unit, TypeName="Alert").Create()


def ensure_percentage(devices, unit, name):
    """Create a Percentage device if it does not already exist."""
    if unit not in devices:
        Domoticz.Device(Name=name, Unit=unit, TypeName="Percentage").Create()


def ensure_custom(devices, unit, name, unit_label=""):
    """Create a Custom sensor device if it does not already exist.
    unit_label: displayed after the value, e.g. '°C' or 'cups'.
    """
    if unit not in devices:
        Domoticz.Device(
            Name=name, Unit=unit, TypeName="Custom",
            Options={"Custom": f"1;{unit_label}"},
        ).Create()


def make_selector_options(names: list) -> dict:
    """Build a Selector Switch Options dict from a list of level name strings.
    Level 0 = names[0], Level 10 = names[1], etc.
    Uses menu style (dropdown) when there are more than 4 options.
    """
    pipes = "|" * (len(names) - 1)
    return {
        "LevelActions": pipes,
        "LevelNames": "|".join(names),
        "LevelOffHidden": "false",
        "SelectorStyle": "1" if len(names) > 4 else "0",
    }


# ---------------------------------------------------------------------------
# Device update helpers
# ---------------------------------------------------------------------------

def update_switch(devices, unit, on: bool):
    """Update a Switch device: nValue=1 when on, nValue=0 when off."""
    if unit not in devices:
        return
    nvalue = 1 if on else 0
    devices[unit].Update(nValue=nvalue, sValue="")


def update_selector(devices, unit, level: int):
    """Update a Selector Switch device to the given level value.
    Always uses nValue=2 so level 0 ('Off') shows as selected rather than greyed out.
    """
    if unit not in devices:
        return
    devices[unit].Update(nValue=2, sValue=str(level))


def update_contact(devices, unit, open: bool):
    """Update a Contact Sensor device: nValue=1 (open) or nValue=0 (closed)."""
    if unit not in devices:
        return
    if open:
        devices[unit].Update(nValue=1, sValue="Open")
    else:
        devices[unit].Update(nValue=0, sValue="Closed")


def update_kwh(devices, unit, watts: float, total_wh: float):
    """Update a kWh device. sValue format: 'instant_watts;total_wh'"""
    if unit not in devices:
        return
    devices[unit].Update(nValue=0, sValue=f"{watts:.1f};{int(total_wh)}")


def update_temperature(devices, unit, temp: float):
    """Update a Temperature sensor device."""
    if unit not in devices:
        return
    devices[unit].Update(nValue=0, sValue=f"{temp:.1f}")


def update_text(devices, unit, text: str):
    """Update a Text device."""
    if unit not in devices:
        return
    devices[unit].Update(nValue=0, sValue=str(text))


def update_alert(devices, unit, level: int, text: str):
    """Update an Alert sensor. level: 0=grey, 1=green, 2=yellow, 3=orange, 4=red."""
    if unit not in devices:
        return
    devices[unit].Update(nValue=level, sValue=str(text))


def update_percentage(devices, unit, pct: float):
    """Update a Percentage device (0-100)."""
    if unit not in devices:
        return
    devices[unit].Update(nValue=int(pct), sValue=str(int(pct)))


def update_custom(devices, unit, value):
    """Update a Custom sensor device."""
    if unit not in devices:
        return
    devices[unit].Update(nValue=0, sValue=str(value))
