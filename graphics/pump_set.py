"""Duty / standby pump set with VFDs, differential pressure and flow."""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from graphics.base import (GREEN, GREY, RED, STEEL_DARK, WATER_RETURN, WATER_SUPPLY, Drawer,
                           GraphicPoint, GraphicTemplate, PointState)

P = GraphicPoint


class PumpSetGraphic(GraphicTemplate):
    TEMPLATE_ID = "pump_set"
    NAME = "Pump Set (Duty / Standby)"
    DESCRIPTION = "Two pumps in parallel with VFD speed, faults, differential pressure and flow"
    WIDTH, HEIGHT = 1200, 560
    POINTS = [
        P("p1_status", "Pump 1 Status", "binary", "Impeller rotates when running",
          match=["pump 1 status", "p1 status", "pump1 status", "pump 1 run", "pump 1"]),
        P("p1_fault", "Pump 1 Fault", "binary", "Trip / fault",
          alarm_when_active=True, match=["pump 1 fault", "p1 fault", "pump 1 trip", "pump1 fault"]),
        P("p1_speed", "Pump 1 Speed", "analog", "Optional VFD speed %",
          match=["pump 1 speed", "p1 speed", "pump1 speed", "vfd 1"]),
        P("p2_status", "Pump 2 Status", "binary", "Impeller rotates when running",
          match=["pump 2 status", "p2 status", "pump2 status", "pump 2 run", "pump 2"]),
        P("p2_fault", "Pump 2 Fault", "binary", "Trip / fault",
          alarm_when_active=True, match=["pump 2 fault", "p2 fault", "pump 2 trip", "pump2 fault"]),
        P("p2_speed", "Pump 2 Speed", "analog", "Optional VFD speed %",
          match=["pump 2 speed", "p2 speed", "pump2 speed", "vfd 2"]),
        P("dp", "Differential Pressure", "analog", "System DP (kPa / bar)",
          match=["differential pressure", "dp sensor", "dpt", "diff press", "dp"]),
        P("dp_sp", "DP Setpoint", "analog", "Optional",
          match=["dp setpoint", "dp sp", "pressure setpoint"]),
        P("flow", "Flow Rate", "analog", "Optional (l/s, m3/h, gpm)",
          match=["flow rate", "flow", "flow meter"]),
    ]

    def demo_value(self, key: str, t: float) -> Tuple[Any, bool]:
        c = t % 60
        p1 = c < 28
        p2 = c > 31
        return {
            "p1_status": (int(p1), False), "p1_fault": (int(28 < c < 34), False),
            "p1_speed": ((65 + 20 * math.sin(t / 6)) if p1 else 0.0, True),
            "p2_status": (int(p2), False), "p2_fault": (0, False),
            "p2_speed": ((65 + 20 * math.sin(t / 6)) if p2 else 0.0, True),
            "dp": ((120 + 8 * math.sin(t / 4)) if (p1 or p2) else 15.0, True),
            "dp_sp": (120.0, True),
            "flow": ((28 + 6 * math.sin(t / 6)) if (p1 or p2) else 0.0, True),
        }[key]

    def _pump(self, d: Drawer, x: float, n: int, s: Dict[str, PointState], t: float, blink: bool):
        st, ft, spd = s[f"p{n}_status"], s[f"p{n}_fault"], s[f"p{n}_speed"]
        on = st.active
        k = spd.percent / 100 if (spd.linked or spd.override) and spd.is_analog else 1.0
        d.pipe([x, 440, x, 330], WATER_RETURN, on, t, k, width=6)
        d.pipe([x, 250, x, 110], WATER_SUPPLY, on, t, k, width=6)
        d.iso_valve(x, 400)
        d.check_valve(x, 195)
        d.iso_valve(x, 150)
        d.pump(x, 290, 40, on, max(k, 0.3), t, point=f"p{n}_status", fault=ft.active and blink)
        d.text(x, 470, f"PUMP {n}", 10, True, STEEL_DARK)
        d.lamp(x + 75, 250, ft.active, blink, RED, "FAULT", point=f"p{n}_fault")
        d.line([x - 40, 290, x - 70, 290], fill=GREY, width=2)
        d.vfd(x - 140, 260, spd, on, point=f"p{n}_speed")
        if on:
            d.tag(x + 48, 345, "RUNNING", GREEN, 8, anchor="w")

    def draw(self, d: Drawer, s: Dict[str, PointState], t: float):
        blink = int(t * 2.5) % 2 == 0
        any_on = s["p1_status"].active or s["p2_status"].active

        d.pipe([940, 440, 330, 440], WATER_RETURN, any_on, t, width=10)
        d.tag(940, 470, "FROM SYSTEM (RETURN)", WATER_RETURN, 8, anchor="e")
        d.pipe([330, 110, 940, 110], WATER_SUPPLY, any_on, t, width=10)
        d.tag(940, 85, "TO SYSTEM (SUPPLY)", WATER_SUPPLY, 8, anchor="e")
        d.text(470, 70, "DISCHARGE HEADER", 8, True, STEEL_DARK)
        d.text(470, 500, "SUCTION HEADER", 8, True, STEEL_DARK)
        d.text(760, 520, "SYSTEM DP measured between supply and return", 8, False, GREY)

        self._pump(d, 330, 1, s, t, blink)
        self._pump(d, 600, 2, s, t, blink)

        # differential pressure across the headers (system side)
        dp, dsp = s["dp"], s["dp_sp"]
        d.line([800, 110, 800, 255], fill=GREY, width=2)
        d.line([800, 440, 800, 295], fill=GREY, width=2)
        d.sensor(800, 275, "DPT", dp, point="dp")
        v = dp.num if (dp.linked and dp.online) or dp.override else None
        spv = dsp.num if (dsp.linked and dsp.online) or dsp.override else None
        if v is not None:
            d.tag(825, 268, f"{v:.0f} kPa", "#2e5c8a", 10, anchor="w")
        if spv is not None:
            d.tag(825, 290, f"SP {spv:.0f}", STEEL_DARK, 8, anchor="w")
        d.hotspot(820, 282, 890, 300, "dp_sp")

        # flow meter on the discharge header
        fl = s["flow"]
        d.rect(880, 96, 920, 124, fill="#e3f2fd" if (fl.linked or fl.override) else "#f5f5f5",
               outline=STEEL_DARK, width=2, point="flow")
        d.text(900, 110, "FM", 8, True, point="flow")
        fv = fl.num if (fl.linked and fl.online) or fl.override else None
        if fv is not None:
            d.tag(900, 145, f"{fv:.1f}", "#2e5c8a", 10)

        d.legend(975, 30, [(p.key, p.label) for p in self.POINTS], s, width=210, step=46)


TEMPLATE = PumpSetGraphic
