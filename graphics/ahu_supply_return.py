"""AHU with supply and return fans, mixing box, pre + bag filters and cooling coil."""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from graphics.base import (AMBER, GREEN, GREY, RED, STEEL_DARK, WATER_RETURN, WATER_SUPPLY,
                           Drawer, GraphicPoint, GraphicTemplate, PointState)

P = GraphicPoint


class AHUSupplyReturnGraphic(GraphicTemplate):
    TEMPLATE_ID = "ahu_sr"
    NAME = "AHU Supply & Return"
    DESCRIPTION = ("Two-deck AHU: supply & return fans with flow DPS, pre + bag filters, cooling "
                   "valve, fresh / return / exhaust / supply air dampers, duct DPT and CO2 sensor")
    WIDTH, HEIGHT = 1330, 680
    POINTS = [
        P("supply_fan", "Supply Fan", "any", "Status/command (binary) or speed % - rotates when active",
          match=["supply fan status", "sf status", "supply fan sts", "supply fan run", "supply fan"]),
        P("return_fan", "Return Fan", "any", "Status/command (binary) or speed % - rotates when active",
          match=["return fan status", "rf status", "return fan sts", "return fan run", "return fan"]),
        P("supply_flow", "DPS Flow Supply", "binary", "Supply air flow switch - green when proven",
          match=["supply flow", "supply air flow", "sf dps", "supply dps", "dps flow supply"]),
        P("return_flow", "DPS Flow Return", "binary", "Return air flow switch - green when proven",
          match=["return flow", "return air flow", "rf dps", "return dps", "dps flow return"]),
        P("pre_filter", "Pre Filter", "binary", "Pre-filter DPS - flashes red when dirty",
          alarm_when_active=True, match=["pre filter", "prefilter", "panel filter"]),
        P("bag_filter", "Bag Filter", "binary", "Bag-filter DPS - flashes red when dirty",
          alarm_when_active=True, match=["bag filter", "final filter", "secondary filter"]),
        P("cooling_valve", "Cooling Valve", "analog", "0-100 % - chilled water flows when open",
          match=["cooling valve", "chw valve", "chilled water valve", "cool valve", "ccv"]),
        P("fresh_damper", "Fresh Air Damper", "any", "Position 0-100 % or open/closed",
          match=["fresh air damper", "outside air damper", "oa damper", "fa damper", "fresh damper"]),
        P("return_damper", "Return Air Damper", "any", "Position 0-100 % or open/closed",
          match=["return air damper", "ra damper", "return damper", "mixing damper"]),
        P("exhaust_damper", "Exhaust Air Damper", "any", "Position 0-100 % or open/closed",
          match=["exhaust air damper", "ea damper", "exhaust damper", "relief damper"]),
        P("supply_damper", "Supply Air Damper", "any", "Position 0-100 % or open/closed",
          match=["supply air damper", "sa damper", "supply damper"]),
        P("dpt", "DPT Air Sensor", "analog", "Duct static / differential pressure (Pa)",
          match=["dpt", "static pressure", "duct pressure", "differential pressure", "air pressure"]),
        P("co2", "CO2 Sensor", "analog", "Return air CO2 (ppm): green < 800, amber < 1200, red above",
          match=["co2", "carbon dioxide"]),
        P("supply_temp", "Supply Air Temp", "analog", "Optional display",
          match=["supply air temp", "sat", "supply temp", "discharge air temp"]),
        P("return_temp", "Return Air Temp", "analog", "Optional display",
          match=["return air temp", "rat", "return temp"]),
    ]

    def demo_value(self, key: str, t: float) -> Tuple[Any, bool]:
        on = (t % 60) < 50
        if key in ("supply_fan", "return_fan"):
            return int(on), False
        if key in ("supply_flow", "return_flow"):
            return int(on and (t % 60) > 3), False
        if key == "pre_filter":
            return int(30 < (t % 60) < 42), False
        if key == "bag_filter":
            return 0, False
        if key == "cooling_valve":
            return (55 + 40 * math.sin(t / 7)) if on else 0.0, True
        if key == "fresh_damper":
            return (35.0 + 10 * math.sin(t / 9)) if on else 0.0, True
        if key == "exhaust_damper":
            return (30.0 + 10 * math.sin(t / 9)) if on else 0.0, True
        if key == "return_damper":
            return (65.0 - 10 * math.sin(t / 9)) if on else 0.0, True
        if key == "supply_damper":
            return 100.0 if on else 0.0, True
        if key == "dpt":
            return (250 + 15 * math.sin(t / 3)) if on else 0.0, True
        if key == "co2":
            return 650 + 450 * (0.5 + 0.5 * math.sin(t / 15)), True
        if key == "supply_temp":
            return 13.0 + 1.2 * math.sin(t / 7), True
        return 24.0 + 0.6 * math.sin(t / 11), True

    @staticmethod
    def _pct(st: PointState) -> float:
        return st.percent if (st.linked or st.override) else 0.0

    def draw(self, d: Drawer, s: Dict[str, PointState], t: float):
        blink = int(t * 2.5) % 2 == 0
        sf, rf = s["supply_fan"], s["return_fan"]
        fa, ra, ea, sa = (self._pct(s[k]) for k in ("fresh_damper", "return_damper",
                                                     "exhaust_damper", "supply_damper"))
        sup_speed = sf.speed if sf.active else 0.0
        ret_speed = rf.speed if rf.active else 0.0

        # ---------------- casing, decks, ducts
        d.rect(180, 110, 980, 470, fill="#f7f9fa", outline=STEEL_DARK, width=3)
        d.line([360, 290, 980, 290], fill=STEEL_DARK, width=3)
        d.text(670, 96, "AIR HANDLING UNIT - SUPPLY & RETURN", 10, True, STEEL_DARK)
        d.duct(40, 130, 160, 270, "EXHAUST AIR")
        d.duct(40, 310, 160, 450, "FRESH AIR")
        d.duct(1002, 130, 1095, 270, "")
        d.text(1048, 285, "", 8)
        d.duct(1002, 320, 1095, 440, "")
        d.text(1048, 457, "SUPPLY AIR", 9, True, STEEL_DARK)
        d.text(1048, 122, "RETURN AIR", 9, True, STEEL_DARK)

        # ---------------- air movement
        d.air_arrows(1004, 1092, 200, t, ret_speed, (-35, 35), 40, direction=-1)
        d.air_arrows(820, 976, 200, t, ret_speed, (-45, 0, 45), 45, direction=-1)
        d.air_arrows(370, 700, 200, t, ret_speed, (-45, 0, 45), 45, direction=-1)
        d.air_arrows(42, 132, 200, t, ret_speed * ea / 100, (-40, 40), 40, direction=-1)
        d.air_arrows(42, 132, 380, t, sup_speed * max(fa, 5) / 100, (-40, 40), 40)
        d.air_arrows(215, 340, 270, t, ret_speed * ra / 100 if ra else 0, (0,), 40, direction=2)
        d.air_arrows(215, 320, 380, t, sup_speed, (-45, 45), 45)
        d.air_arrows(625, 700, 380, t, sup_speed, (-45, 0, 45), 40)
        d.air_arrows(820, 950, 380, t, sup_speed, (-45, 0, 45), 45)
        d.air_arrows(1004, 1092, 380, t, sup_speed * sa / 100, (-30, 30), 40)

        # ---------------- dampers
        d.damper(180, 132, 268, ea, point="exhaust_damper")
        d.tag(180, 284, f"EA {ea:.0f}%", STEEL_DARK, 8)
        d.damper(180, 312, 448, fa, point="fresh_damper")
        d.tag(180, 488, f"FA {fa:.0f}%", STEEL_DARK, 8)
        d.damper_h(205, 335, 290, ra, point="return_damper")
        d.tag(270, 318, f"RA {ra:.0f}%", STEEL_DARK, 8)
        d.damper(980, 312, 448, sa, point="supply_damper")
        d.tag(980, 488, f"SA {sa:.0f}%", STEEL_DARK, 8)

        # ---------------- return fan + DPS
        d.fan(760, 200, 52, rf.active, rf.speed, t, point="return_fan",
              fault=rf.active and s["return_flow"].linked and not s["return_flow"].active and blink)
        d.line([700, 110, 700, 60, 730, 60], fill=GREY, width=2)
        d.line([820, 110, 820, 60, 790, 60], fill=GREY, width=2)
        d.dps(760, 60, s["return_flow"].active, False, blink, point="return_flow", label="FLOW")
        d.tag(760, 26, "RETURN FLOW DPS", STEEL_DARK, 8)

        # ---------------- filters + DPS
        pre, bag = s["pre_filter"], s["bag_filter"]
        d.filter(392, 300, 422, 460, pre.active, blink, point="pre_filter")
        d.bag_filter(452, 300, 525, 460, bag.active, blink, point="bag_filter")
        d.line([382, 470, 382, 545, 375, 545], fill=GREY, width=2)
        d.line([440, 470, 440, 545, 435, 545], fill=GREY, width=2)
        d.dps(405, 545, pre.active, True, blink, point="pre_filter", label="PRE")
        d.line([448, 470, 448, 615, 458, 615], fill=GREY, width=2)
        d.line([532, 470, 532, 615, 518, 615], fill=GREY, width=2)
        d.dps(488, 615, bag.active, True, blink, point="bag_filter", label="BAG")
        if pre.active:
            d.tag(405, 508, "PRE FILTER DIRTY", RED if blink else "#ef9a9a", 8)
        if bag.active:
            d.tag(488, 650, "BAG FILTER DIRTY", RED if blink else "#ef9a9a", 8)

        # ---------------- cooling coil + valve
        v = s["cooling_valve"]
        vp = v.percent if v.active else 0.0
        d.coil(568, 300, 618, 460, vp / 100, point="cooling_valve")
        d.pipe([555, 640, 580, 640, 580, 472], WATER_SUPPLY, v.active, t, v.speed)
        d.pipe([606, 472, 606, 570, 690, 570], WATER_RETURN, v.active, t, v.speed)
        d.valve(650, 570, vp, point="cooling_valve")
        d.tag(545, 640, "CHWS", WATER_SUPPLY, 8, anchor="e")
        d.tag(690, 590, "CHWR", WATER_RETURN, 8, anchor="e")
        d.tag(650, 600, f"{vp:.0f} %", WATER_SUPPLY, 9)

        # ---------------- supply fan + DPS
        d.fan(760, 380, 52, sf.active, sf.speed, t, point="supply_fan",
              fault=sf.active and s["supply_flow"].linked and not s["supply_flow"].active and blink)
        d.line([722, 470, 722, 600, 730, 600], fill=GREY, width=2)
        d.line([800, 470, 800, 600, 790, 600], fill=GREY, width=2)
        d.dps(760, 600, s["supply_flow"].active, False, blink, point="supply_flow", label="FLOW")
        d.tag(760, 640, "SUPPLY FLOW DPS", STEEL_DARK, 8)

        # ---------------- duct sensors
        dpt = s["dpt"]
        d.sensor(1048, 300, "DPT", dpt, point="dpt", stem=4)
        if dpt.num is not None and (dpt.linked or dpt.override):
            d.tag(1048, 494, f"{dpt.num:.0f} Pa", "#2e5c8a", 9)
        co2 = s["co2"]
        c = co2.num if (co2.linked and co2.online) or co2.override else None
        col = None if c is None else ("#c8e6c9" if c < 800 else "#ffe0b2" if c < 1200 else "#ffcdd2")
        d.sensor(1020, 60, "CO2", co2, point="co2", stem=54, color=col)
        if c is not None:
            d.tag(1020, 30, f"{c:.0f} ppm", GREEN if c < 800 else AMBER if c < 1200 else RED, 9)
        d.sensor(1075, 60, "TT", s["return_temp"], point="return_temp", stem=54)
        d.sensor(1075, 520, "TT", s["supply_temp"], point="supply_temp", stem=-64)

        # ---------------- legend
        d.legend(1120, 30, [(p.key, p.label) for p in self.POINTS], s, width=200, step=42.5)


TEMPLATE = AHUSupplyReturnGraphic
