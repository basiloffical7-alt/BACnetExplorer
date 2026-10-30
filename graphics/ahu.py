"""Air Handling Unit (100 % fresh air) graphic."""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from graphics.base import (AMBER, GREEN, GREY, STEEL_DARK, WATER_RETURN, WATER_SUPPLY, Drawer,
                           GraphicPoint, GraphicTemplate, PointState)


class AHUGraphic(GraphicTemplate):
    TEMPLATE_ID = "ahu"
    NAME = "Air Handling Unit"
    DESCRIPTION = "Fresh-air AHU: damper, filter + DPS, cooling coil + valve, supply fan + flow DPS"
    WIDTH, HEIGHT = 1000, 520
    POINTS = [
        GraphicPoint("supply_fan", "Supply Fan", "any",
                     "Fan status/command (binary) or speed % (analog) - blades rotate when active"),
        GraphicPoint("cooling_valve", "Cooling Valve", "analog",
                     "Valve position 0-100 % (binary = open/closed) - chilled water flows when open"),
        GraphicPoint("flow_dps", "Air Flow DPS", "binary",
                     "Air flow switch - diaphragm moves and turns green when air flow is proven"),
        GraphicPoint("filter_dps", "Filter DPS", "binary",
                     "Filter dirty switch - flashes red when active", alarm_when_active=True),
        GraphicPoint("fresh_damper", "Fresh Air Damper", "any",
                     "Damper position 0-100 % (binary = open/closed) - blades rotate"),
        GraphicPoint("supply_temp", "Supply Air Temp", "analog", "Display only (optional)"),
        GraphicPoint("fresh_temp", "Fresh Air Temp", "analog", "Display only (optional)"),
    ]

    def demo_value(self, key: str, t: float) -> Tuple[Any, bool]:
        cycle = (t % 40) / 40
        running = cycle < 0.8
        if key == "supply_fan":
            return (1 if running else 0), False
        if key == "flow_dps":
            return (1 if running and (t % 40) > 3 else 0), False
        if key == "fresh_damper":
            return (100.0 if running else 0.0), True
        if key == "cooling_valve":
            return (max(0.0, 50 + 45 * math.sin(t / 6)) if running else 0.0), True
        if key == "filter_dps":
            return (1 if 20 < (t % 60) < 32 else 0), False
        if key == "supply_temp":
            return 13.5 + 1.5 * math.sin(t / 6), True
        return 34.0 + math.sin(t / 30), True

    def draw(self, d: Drawer, s: Dict[str, PointState], t: float):
        fan, valve, flow = s["supply_fan"], s["cooling_valve"], s["flow_dps"]
        filt, damper = s["filter_dps"], s["fresh_damper"]
        blink = int(t * 2.5) % 2 == 0
        damper_pct = damper.percent if (damper.linked or damper.override) else 100.0
        air_speed = fan.speed * (0.25 + 0.75 * damper_pct / 100) if fan.active else 0.0

        # ---- casing and ducts
        d.duct(30, 190, 170, 330, "FRESH AIR")
        d.rect(170, 165, 860, 355, fill="#f7f9fa", outline=STEEL_DARK, width=3)
        d.text(515, 150, "AIR HANDLING UNIT", 10, True, STEEL_DARK)
        d.duct(860, 205, 980, 315, "SUPPLY AIR")

        # ---- moving air
        rows = (-50, 0, 50)
        for x1, x2 in ((32, 98), (300, 392), (462, 578), (728, 856)):
            d.air_arrows(x1, x2, 260, t, air_speed, rows, 45)
        d.air_arrows(866, 978, 260, t, air_speed, (-25, 25), 45)

        # ---- fresh air damper
        d.damper(130, 190, 330, damper_pct if (damper.linked or damper.override) else 0,
                 point="fresh_damper")

        # ---- filter + DPS
        d.filter(238, 180, 278, 340, filt.active, blink, point="filter_dps")
        d.line([226, 180, 226, 95, 227, 95], fill=GREY, width=2)
        d.line([290, 180, 290, 95, 287, 95], fill=GREY, width=2)
        d.dps(257, 95, filt.active, True, blink, point="filter_dps", label="FILTER")
        if filt.active:
            d.text(257, 58, "FILTER DIRTY", 9, True, "#c62828" if blink else "#ef9a9a")

        # ---- cooling coil + valve + chilled water
        d.coil(400, 180, 450, 340, valve.percent / 100 if valve.active else 0.0,
               point="cooling_valve")
        flowing = valve.active
        d.pipe([330, 490, 412, 490, 412, 342], WATER_SUPPLY, flowing, t, valve.speed)
        d.pipe([438, 342, 438, 440, 600, 440], WATER_RETURN, flowing, t, valve.speed)
        d.text(316, 490, "CHWS", 9, True, WATER_SUPPLY, anchor="e")
        d.text(612, 440, "CHWR", 9, True, WATER_RETURN, anchor="w")
        d.valve(515, 440, valve.percent if valve.active else 0, point="cooling_valve")
        d.text(425, 173, "COOLING COIL", 7, True, STEEL_DARK)

        # ---- supply fan + flow DPS
        d.fan(650, 260, 58, fan.active, fan.speed, t, point="supply_fan",
              fault=fan.active and flow.linked and not flow.active and (t % 1 < 0.5))
        d.line([592, 165, 592, 95, 620, 95], fill=GREY, width=2)
        d.line([712, 165, 712, 95, 680, 95], fill=GREY, width=2)
        d.dps(650, 95, flow.active, False, blink, point="flow_dps", label="FLOW")
        if fan.active and flow.linked and not flow.active:
            d.text(650, 58, "NO AIR FLOW", 9, True, AMBER)
        elif flow.active:
            d.text(650, 58, "AIR FLOW OK", 9, True, GREEN)

        # ---- value badges
        d.value_box(30, 375, "Fresh Air Damper", damper, point="fresh_damper")
        d.value_box(30, 110, "Fresh Air Temp", s["fresh_temp"], 140, point="fresh_temp")
        d.value_box(305, 75, "Filter DPS", filt, point="filter_dps")
        d.value_box(600, 380, "Cooling Valve", valve, 140, point="cooling_valve")
        d.value_box(745, 75, "Air Flow DPS", flow, point="flow_dps")
        d.value_box(755, 380, "Supply Fan", fan, 140, point="supply_fan")
        d.value_box(866, 330, "Supply Air Temp", s["supply_temp"], 128, point="supply_temp")


TEMPLATE = AHUGraphic
