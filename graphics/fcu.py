"""Fan Coil Unit (ceiling concealed, chilled water)."""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from graphics.base import (AMBER, GREY, RED, STEEL_DARK, WATER_RETURN, WATER_SUPPLY, Drawer,
                           GraphicPoint, GraphicTemplate, PointState)

P = GraphicPoint


def fan_level(spd: PointState, status: PointState) -> int:
    """0..3 speed level from a speed point (multi-state 1=off..4=high, %, or binary)."""
    if spd.linked or spd.override:
        if spd.is_analog:
            v = spd.percent
            return 0 if v < 1 else 1 if v < 40 else 2 if v < 75 else 3
        n = spd.num
        from bacnet.codec import Enumerated  # binary values arrive as Enumerated
        if n is not None and not isinstance(spd.value, (bool, Enumerated)):
            return max(0, min(3, int(n) - 1))
        return 3 if spd.active else 0
    return 3 if status.active else 0


class FCUGraphic(GraphicTemplate):
    TEMPLATE_ID = "fcu"
    NAME = "Fan Coil Unit (FCU)"
    DESCRIPTION = "Ceiling FCU: fan status + speed (L/M/H), chilled water valve, filter, room thermostat"
    WIDTH, HEIGHT = 1200, 560
    POINTS = [
        P("fan_status", "Fan Status", "binary", "Blower rotates when active",
          match=["fan status", "fan sts", "fan run", "fcu fan", "fan"]),
        P("fan_speed", "Fan Speed", "any",
          "Multi-state (1 Off, 2 Low, 3 Med, 4 High), speed % or binary",
          match=["fan speed", "speed", "fan mode"]),
        P("cooling_valve", "Cooling Valve", "analog", "0-100 % (binary = open/closed)",
          match=["cooling valve", "chw valve", "valve"]),
        P("room_temp", "Room Temp", "analog", "Shown on the thermostat",
          match=["room temp", "space temp", "zone temp", "rt"]),
        P("setpoint", "Setpoint", "analog", "Room temperature setpoint",
          match=["setpoint", "set point", "sp"]),
        P("supply_temp", "Supply Air Temp", "analog", "Optional",
          match=["supply air temp", "supply temp", "sat", "discharge temp"]),
        P("filter_alarm", "Filter Alarm", "binary", "Filter dirty - flashes red",
          alarm_when_active=True, match=["filter"]),
        P("occupancy", "Occupancy", "binary", "Occupied / unoccupied",
          match=["occupancy", "occupied", "occ"]),
        P("fault", "FCU Alarm", "binary", "Common fault / condensate alarm",
          alarm_when_active=True, match=["alarm", "fault", "condensate", "trip"]),
    ]

    def demo_value(self, key: str, t: float) -> Tuple[Any, bool]:
        on = (t % 45) < 38
        return {
            "fan_status": (int(on), False),
            "fan_speed": ((25.0 if (t % 45) < 12 else 60.0 if (t % 45) < 25 else 95.0) if on else 0.0, True),
            "cooling_valve": ((50 + 45 * math.sin(t / 6)) if on else 0.0, True),
            "room_temp": (23.4 + 0.5 * math.sin(t / 10), True),
            "setpoint": (23.0, True),
            "supply_temp": (14.5 + math.sin(t / 6), True),
            "filter_alarm": (int(20 < (t % 70) < 28), False),
            "occupancy": (int(on), False),
            "fault": (0, False),
        }[key]

    def draw(self, d: Drawer, s: Dict[str, PointState], t: float):
        blink = int(t * 2.5) % 2 == 0
        st, spd, v = s["fan_status"], s["fan_speed"], s["cooling_valve"]
        level = fan_level(spd, st) if st.active or not st.linked else 0
        running = st.active or (not st.linked and not st.override and level > 0)
        air = (level / 3.0) if running else 0.0

        d.line([20, 90, 950, 90], fill="#b0bec5", width=3)
        d.text(30, 76, "CEILING", 8, True, GREY, anchor="w")
        d.text(30, 108, "CEILING VOID", 8, False, GREY, anchor="w")
        d.line([20, 380, 950, 380], fill="#b0bec5", width=3)
        d.text(30, 396, "FALSE CEILING / ROOM BELOW", 8, False, GREY, anchor="w")

        # casing
        d.rect(190, 150, 760, 330, fill="#f7f9fa", outline=STEEL_DARK, width=3)
        d.text(475, 138, "FAN COIL UNIT", 10, True, STEEL_DARK)
        d.grille(165, 170, 310, "RETURN")
        d.air_arrows(40, 150, 240, t, air, (-40, 40), 40)
        d.air_arrows(290, 352, 240, t, air, (-45, 45), 40)
        d.air_arrows(425, 485, 240, t, air, (-45, 45), 40)

        # filter
        fa = s["filter_alarm"]
        d.filter(235, 165, 265, 315, fa.active, blink, point="filter_alarm")
        if fa.active:
            d.tag(250, 345, "FILTER DIRTY", RED if blink else "#ef9a9a", 8)

        # coil, drain pan, valve
        vp = v.percent if v.active else 0.0
        d.coil(360, 165, 410, 315, vp / 100, point="cooling_valve")
        d.rect(345, 318, 425, 328, fill="#cfd8dc", outline=STEEL_DARK, width=1)
        d.pipe([300, 470, 372, 470, 372, 335], WATER_SUPPLY, v.active, t, v.speed, width=5)
        d.pipe([398, 335, 398, 430, 520, 430], WATER_RETURN, v.active, t, v.speed, width=5)
        d.valve(460, 430, vp, point="cooling_valve", size=18)
        d.tag(290, 470, "CHWS", WATER_SUPPLY, 8, anchor="e")
        d.tag(530, 430, "CHWR", WATER_RETURN, 8, anchor="w")
        d.tag(460, 460, f"{vp:.0f} %", WATER_SUPPLY, 9)

        # blower
        fault = s["fault"]
        d.fan(590, 240, 62, running, max(air, 0.3), t, point="fan_status", fault=fault.active and blink)
        d.speed_bars(560, 352, level if running else 0)
        d.hotspot(552, 330, 620, 372, "fan_speed")
        d.tag(650, 345, ["OFF", "LOW", "MED", "HIGH"][level if running else 0], STEEL_DARK, 9, anchor="w")

        # supply duct + diffuser
        d.duct(760, 180, 900, 300, "")
        d.grille(905, 185, 295, "SUPPLY")
        d.air_arrows(770, 895, 240, t, air, (-35, 35), 40)
        d.air_arrows(915, 948, 240, t, air, (-35, 35), 30)
        d.sensor(830, 135, "TT", s["supply_temp"], point="supply_temp", stem=29)

        # room thermostat + status lamps
        d.thermostat(720, 420, s["room_temp"], s["setpoint"], point="room_temp")
        d.hotspot(720, 470, 816, 494, "setpoint")
        occ = s["occupancy"]
        d.lamp(860, 440, occ.active, True, "#43a047", "OCCUPIED" if occ.active else "UNOCC.",
               point="occupancy")
        d.lamp(860, 500, fault.active, blink, RED, "ALARM", point="fault")
        if st.linked and spd.linked and not st.active and level > 0:
            d.tag(590, 120, "SPEED SET BUT FAN NOT RUNNING", AMBER, 8)

        d.legend(975, 30, [(p.key, p.label) for p in self.POINTS], s, width=210, step=46)


TEMPLATE = FCUGraphic
