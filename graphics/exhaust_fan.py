"""Exhaust fan with motorized damper, flow DPS, VFD and fault."""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from graphics.base import (AMBER, GREEN, GREY, RED, STEEL_DARK, Drawer, GraphicPoint,
                           GraphicTemplate, PointState)

P = GraphicPoint


class ExhaustFanGraphic(GraphicTemplate):
    TEMPLATE_ID = "exhaust_fan"
    NAME = "Exhaust Fan"
    DESCRIPTION = "Exhaust fan: command, run status, flow DPS, trip/fault, VFD speed, motorized damper"
    WIDTH, HEIGHT = 1200, 520
    POINTS = [
        P("fan_cmd", "Fan Command", "binary", "Start/stop command",
          match=["fan command", "fan cmd", "start stop", "ss", "command"]),
        P("fan_status", "Fan Status", "binary", "Run status - blades rotate when active",
          match=["fan status", "fan sts", "run status", "fan run"]),
        P("flow_dps", "Air Flow DPS", "binary", "Air flow proven",
          match=["flow", "dps", "air flow"]),
        P("fault", "Fan Trip / Fault", "binary", "Overload trip / VFD fault - flashes red",
          alarm_when_active=True, match=["trip", "fault", "alarm", "overload"]),
        P("speed", "VFD Speed", "analog", "Speed 0-100 % (Hz shown on the VFD)",
          match=["speed", "vfd", "frequency", "hz"]),
        P("damper", "Motorized Damper", "any", "Damper position % or open/closed",
          match=["damper", "mod"]),
    ]

    def demo_value(self, key: str, t: float) -> Tuple[Any, bool]:
        c = t % 50
        cmd = c < 40
        run = 3 < c < 42
        return {
            "fan_cmd": (int(cmd), False), "fan_status": (int(run), False),
            "flow_dps": (int(run and c > 6), False), "fault": (int(44 < c < 49), False),
            "speed": ((70 + 20 * math.sin(t / 5)) if run else 0.0, True),
            "damper": (100.0 if cmd else 0.0, True),
        }[key]

    def draw(self, d: Drawer, s: Dict[str, PointState], t: float):
        blink = int(t * 2.5) % 2 == 0
        cmd, st, flow, fault = s["fan_cmd"], s["fan_status"], s["flow_dps"], s["fault"]
        speed, dmp = s["speed"], s["damper"]
        running = st.active if (st.linked or st.override) else cmd.active
        k = (speed.percent / 100 if (speed.linked or speed.override) and speed.is_analog else 1.0)
        dpos = dmp.percent if (dmp.linked or dmp.override) else 100.0
        air = (max(k, 0.3) * (0.2 + 0.8 * dpos / 100)) if running else 0.0

        # room + exhaust grille
        d.rect(20, 120, 140, 360, fill="#fafafa", outline="#b0bec5", width=2)
        d.text(80, 110, "ROOM / TOILET", 9, True, GREY)
        d.grille(140, 180, 300, "")
        d.air_arrows(30, 130, 240, t, air, (-50, 0, 50), 40)

        # duct, damper, fan, outlet
        d.duct(146, 180, 820, 300, "EXHAUST DUCT")
        d.air_arrows(160, 235, 240, t, air, (-35, 35), 40)
        d.damper(270, 182, 298, dpos if (dmp.linked or dmp.override) else 100.0, point="damper")
        d.tag(270, 318, f"DAMPER {dpos:.0f}%" if (dmp.linked or dmp.override) else "DAMPER",
              STEEL_DARK, 8)
        d.air_arrows(305, 425, 240, t, air, (-35, 35), 40)
        d.rect(420, 160, 580, 320, fill="#eceff1", outline=STEEL_DARK, width=3)
        d.fan(500, 240, 62, running, max(k, 0.3), t, point="fan_status", fault=fault.active and blink)
        d.air_arrows(590, 810, 240, t, air, (-35, 35), 45)
        d.louvre(835, 175, 305, "OUTSIDE")
        d.air_arrows(855, 945, 240, t, air, (-45, 0, 45), 40)

        # flow DPS
        d.line([440, 160, 440, 90, 470, 90], fill=GREY, width=2)
        d.line([560, 160, 560, 90, 530, 90], fill=GREY, width=2)
        d.dps(500, 90, flow.active, False, blink, point="flow_dps", label="FLOW")
        if running and flow.linked and not flow.active:
            d.tag(500, 52, "NO AIR FLOW", AMBER, 9)
        elif flow.active:
            d.tag(500, 52, "AIR FLOW OK", GREEN, 9)

        # motor control: command, VFD, fault
        d.line([500, 320, 500, 370], fill=GREY, width=2)
        d.vfd(465, 370, speed, running, point="speed")
        d.rect(300, 380, 420, 430, fill="#fafafa", outline=STEEL_DARK, width=2, point="fan_cmd")
        d.text(360, 395, "COMMAND", 8, True, STEEL_DARK, point="fan_cmd")
        live_cmd = cmd.linked or cmd.override
        d.text(360, 416, ("START" if cmd.active else "STOP") if live_cmd else "--", 11, True,
               GREEN if cmd.active else GREY, point="fan_cmd")
        d.lamp(620, 400, fault.active, blink, RED, "TRIP / FAULT", point="fault")
        if live_cmd and (st.linked or st.override) and cmd.active != st.active and not fault.active:
            d.tag(500, 468, "COMMAND / STATUS MISMATCH", AMBER if blink else "#ffcc80", 9)

        d.legend(975, 30, [(p.key, p.label) for p in self.POINTS], s, width=210, step=46)


TEMPLATE = ExhaustFanGraphic
