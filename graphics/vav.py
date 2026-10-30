"""VAV box with flow sensor, damper actuator, reheat coil and room thermostat."""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from graphics.base import (AMBER, GREEN, GREY, STEEL_DARK, WATER_RETURN, Drawer, GraphicPoint,
                           GraphicTemplate, PointState)

P = GraphicPoint


class VAVGraphic(GraphicTemplate):
    TEMPLATE_ID = "vav"
    NAME = "VAV Box"
    DESCRIPTION = "Pressure-independent VAV: air flow vs setpoint, damper, optional reheat, thermostat"
    WIDTH, HEIGHT = 1200, 540
    POINTS = [
        P("airflow", "Air Flow", "analog", "Measured air flow (l/s or cfm)",
          match=["air flow", "airflow", "flow"]),
        P("airflow_sp", "Air Flow Setpoint", "analog", "Flow setpoint",
          match=["flow setpoint", "flow sp", "airflow sp", "air flow setpoint"]),
        P("damper", "Damper Position", "analog", "0-100 %",
          match=["damper", "dmp"]),
        P("reheat", "Reheat Valve", "analog", "Optional hot water / electric reheat 0-100 %",
          match=["reheat", "heating valve", "heat"]),
        P("room_temp", "Room Temp", "analog", "Shown on the thermostat",
          match=["room temp", "space temp", "zone temp"]),
        P("room_sp", "Room Setpoint", "analog", "Room temperature setpoint",
          match=["room setpoint", "temp setpoint", "zone setpoint", "setpoint"]),
        P("discharge_temp", "Discharge Air Temp", "analog", "Optional",
          match=["discharge", "supply air temp", "dat"]),
        P("occupancy", "Occupancy", "binary", "Occupied / unoccupied",
          match=["occupancy", "occupied", "occ"]),
    ]

    def demo_value(self, key: str, t: float) -> Tuple[Any, bool]:
        sp = 300 + 150 * (0.5 + 0.5 * math.sin(t / 12))
        return {
            "airflow": (sp + 15 * math.sin(t / 2), True), "airflow_sp": (sp, True),
            "damper": (25 + 60 * (sp - 300) / 150, True),
            "reheat": (max(0.0, 40 * math.sin(t / 15)), True),
            "room_temp": (23.2 + 0.6 * math.sin(t / 12), True), "room_sp": (23.0, True),
            "discharge_temp": (14.0 + 2 * max(0.0, math.sin(t / 15)), True),
            "occupancy": (1, False),
        }[key]

    def draw(self, d: Drawer, s: Dict[str, PointState], t: float):
        flow, fsp, dmp, rh = s["airflow"], s["airflow_sp"], s["damper"], s["reheat"]
        f = flow.num if (flow.linked and flow.online) or flow.override else None
        sp = fsp.num if (fsp.linked and fsp.online) or fsp.override else None
        dpos = dmp.percent if (dmp.linked or dmp.override) else 0.0
        if f is not None:
            ref = max(sp or 0, f, 1.0) * 1.25
            air = max(0.15, min(1.0, f / ref * 1.4)) if f > 1 else 0.0
        else:
            air = dpos / 100

        d.text(30, 170, "PRIMARY AIR", 9, True, STEEL_DARK, anchor="w")
        d.duct(30, 200, 220, 280, "")
        d.air_arrows(40, 140, 240, t, air, (-20, 20), 40)

        # flow cross sensor + tubes to controller
        d.line([170, 202, 170, 278], fill="#5d4037", width=3)
        for yy in (215, 240, 265):
            d.oval(170, yy, 4, fill="#5d4037", outline="", width=0)
        d.line([164, 202, 164, 110, 300, 110], fill=GREY, width=2)
        d.line([176, 202, 176, 120, 300, 120], fill=GREY, width=2)
        d.hotspot(150, 196, 190, 284, "airflow")

        # VAV casing with damper and reheat coil
        d.rect(220, 190, 560, 290, fill="#f7f9fa", outline=STEEL_DARK, width=3)
        d.text(390, 304, "VAV TERMINAL", 9, True, STEEL_DARK)
        d.damper(285, 194, 286, dpos, point="damper", blades=2)
        d.rect(268, 140, 302, 172, fill="#eceff1", outline=STEEL_DARK, width=2, point="damper")
        d.line([285, 172, 285, 194], width=3)
        d.tag(285, 130, f"{dpos:.0f} %", STEEL_DARK, 9)
        d.air_arrows(315, 440, 240, t, air, (-25, 25), 40)
        rpos = rh.percent if (rh.linked or rh.override) and rh.active else 0.0
        heat = rpos / 100
        r_, g_, b_ = 255, int(243 - 120 * heat), int(224 - 170 * heat)
        d.rect(455, 198, 485, 282, fill=f"#{r_:02x}{g_:02x}{b_:02x}", outline=STEEL_DARK, width=2,
               point="reheat")
        for k in range(1, 5):
            d.line([455, 198 + k * 17, 485, 198 + k * 17], fill="#bcaaa4", width=1)
        if rh.linked or rh.override:
            d.pipe([440, 400, 462, 400, 462, 292], WATER_RETURN, rpos > 0.5, t, heat, width=4)
            d.pipe([478, 292, 478, 360, 560, 360], "#ef6c00", rpos > 0.5, t, heat, width=4)
            d.valve(520, 360, rpos, point="reheat", size=14)
            d.tag(520, 385, f"REHEAT {rpos:.0f}%", "#bf360c", 8)
        d.air_arrows(492, 552, 240, t, air, (-25, 25), 30)

        # outlet duct + diffuser to room
        d.duct(560, 205, 760, 275, "")
        d.air_arrows(570, 750, 240, t, air, (-15, 15), 45)
        d.sensor(660, 160, "TT", s["discharge_temp"], point="discharge_temp", stem=29)
        dt = s["discharge_temp"]
        if dt.num is not None and (dt.linked or dt.override):
            d.tag(700, 160, f"{dt.num:.1f} °C", "#2e5c8a", 9, anchor="w")
        d.rect(760, 215, 800, 265, fill="#eceff1", outline=STEEL_DARK, width=2)
        d.rect(735, 265, 825, 278, fill="#cfd8dc", outline=STEEL_DARK, width=2)
        d.air_arrows(285, 345, 760, t, air, (-30, 30), 30, direction=2)
        d.line([600, 360, 950, 360], fill="#b0bec5", width=2)
        d.text(610, 378, "ROOM", 9, True, GREY, anchor="w")

        # controller with flow vs setpoint
        d.rect(300, 60, 520, 135, fill="#263238", outline=STEEL_DARK, width=2, point="airflow")
        d.text(410, 74, "VAV CONTROLLER", 8, True, "#b0bec5", point="airflow")
        d.text(310, 96, f"FLOW  {f:6.0f}" if f is not None else "FLOW    ----", 10, True, "#76ff03",
               anchor="w", point="airflow")
        d.text(310, 118, f"SP    {sp:6.0f}" if sp is not None else "SP      ----", 10, True,
               "#ffd740", anchor="w", point="airflow_sp")
        if f is not None and sp:
            err = abs(f - sp) / max(sp, 1)
            d.level_bar(440, 90, 70, 10, f / (sp * 1.5), GREEN if err < 0.1 else AMBER)
            d.line([440 + 70 / 1.5, 86, 440 + 70 / 1.5, 104], fill="#ffd740", width=2)
            d.text(475, 118, f"{f / sp * 100:.0f}%", 8, True, "#eceff1", point="airflow")

        d.thermostat(830, 400, s["room_temp"], s["room_sp"], point="room_temp")
        d.hotspot(830, 450, 926, 474, "room_sp")
        occ = s["occupancy"]
        d.lamp(700, 430, occ.active, True, "#43a047", "OCCUPIED" if occ.active else "UNOCC.",
               point="occupancy")

        d.legend(975, 30, [(p.key, p.label) for p in self.POINTS], s, width=210, step=46)


TEMPLATE = VAVGraphic
