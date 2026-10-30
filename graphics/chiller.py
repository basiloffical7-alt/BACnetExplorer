"""Primary / secondary chilled water plant with a configurable number of chillers and pumps."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from graphics.base import (AMBER, GREEN, GREY, RED, STEEL_DARK, TEXT, WATER_RETURN, WATER_SUPPLY,
                           Drawer, GraphicPoint, GraphicTemplate, PointState)

P = GraphicPoint
BLUE_LAMP = "#1e88e5"
DECOUPLER = "#5c6bc0"
SPACING = 210          # logical width reserved per chiller / pump


def chiller_points(i: int, single: bool) -> List[GraphicPoint]:
    n = f"Chiller {i}"
    extra = (lambda *p: list(p)) if single else (lambda *p: [])
    return [
        P(f"ch{i}_run", f"{n} Run Status", "binary", "Compressor runs when active",
          match=[f"chiller {i} run status", f"chiller {i} run", f"ch {i} run", f"ch{i} run",
                 f"chiller {i} status", *extra("chiller run status", "chiller run",
                                                "chiller status")]),
        P(f"ch{i}_alarm", f"{n} Alarm", "binary", "Optional common alarm - flashes red",
          alarm_when_active=True,
          match=[f"chiller {i} alarm", f"chiller {i} trip", f"chiller {i} fault", f"ch {i} alarm",
                 f"ch{i} alarm", *extra("chiller alarm", "chiller trip", "chiller fault")]),
        P(f"ch{i}_flow", f"{n} Flow Switch", "binary", "Evaporator water flow proven",
          match=[f"chiller {i} flow switch", f"chiller {i} flow", f"ch {i} flow", f"ch{i} flow",
                 *extra("chiller flow switch", "chiller flow", "evaporator flow")]),
        P(f"ch{i}_temp", f"{n} Leaving Temp", "analog", "Chilled water leaving this chiller",
          match=[f"chiller {i} leaving temp", f"chiller {i} supply temp", f"chiller {i} temp",
                 f"ch {i} temp", f"ch{i} temp", f"ch{i} lwt",
                 *extra("chiller leaving temp", "chiller supply temp", "chiller temp")]),
    ]


def pump_points(prefix: str, i: int, name: str, shorts: Tuple[str, ...],
                single: bool) -> List[GraphicPoint]:
    """Five points per pump: run, trip, flow switch, auto, hand."""
    full = f"{name} {i}"
    lname = name.lower()

    def pats(*words: str) -> List[str]:
        out = []
        for w in words:
            out.append(f"{lname} {i} {w}")
            for sh in shorts:
                out += [f"{sh} {i} {w}", f"{sh}{i} {w}"]
        if single:
            out += [f"{lname} {w}" for w in words] + [f"{sh} {w}" for sh in shorts for w in words]
        return out

    return [
        P(f"{prefix}{i}_run", f"{full} Run Status", "binary", "Impeller rotates when running",
          match=pats("run status", "run", "status")),
        P(f"{prefix}{i}_trip", f"{full} Trip Status", "binary", "Overload trip - pump flashes red",
          alarm_when_active=True, match=pats("trip", "fault")),
        P(f"{prefix}{i}_flow", f"{full} Flow Switch", "binary", "Water flow proven",
          match=pats("flow switch", "flow", "fs")),
        P(f"{prefix}{i}_auto", f"{full} Auto Status", "binary", "H-O-A selector in AUTO",
          match=pats("auto")),
        P(f"{prefix}{i}_hand", f"{full} Hand Status", "binary", "H-O-A selector in HAND",
          match=pats("hand", "manual")),
    ]


NETWORK_POINTS = [
    P("main_supply_temp", "Main Supply Temp", "analog", "Main line chilled water supply",
      match=["main supply temp", "main line supply temp", "secondary supply temp",
             "header supply temp", "chws temp"]),
    P("main_return_temp", "Main Return Temp", "analog", "Main line chilled water return",
      match=["main return temp", "main line return temp", "secondary return temp",
             "header return temp", "chwr temp"]),
    P("dpt", "DPT Sensor", "analog", "Network differential pressure",
      match=["dpt", "differential pressure", "dp sensor", "diff pressure"]),
    P("flow_meter", "Flow Meter", "analog", "Network flow rate",
      match=["flow meter", "flowmeter", "flow rate", "main flow"]),
    P("load", "Building Load", "analog", "Optional cooling load (kW / TR / %)",
      match=["building load", "cooling load", "load"]),
]


class ChillerGraphic(GraphicTemplate):
    TEMPLATE_ID = "chiller"
    NAME = "Chiller System"
    DESCRIPTION = ("Primary / secondary chilled water plant. Choose the number of chillers, primary "
                   "and secondary pumps; each chiller has run, alarm, flow switch and leaving temp, "
                   "each pump run, trip, flow, auto and hand; plus main supply / return temps, DPT, "
                   "flow meter and building load")
    OPTIONS = {"chillers": ("Chillers", 1, 6, 1),
               "primary": ("Primary pumps", 1, 8, 1),
               "secondary": ("Secondary pumps", 1, 8, 1)}
    HEIGHT = 700
    ROW_H = 30
    TABLE_W = 440
    # older versions of this graphic used other keys - keep their links
    LEGACY_KEYS = {
        "chiller_run": "ch1_run", "chiller_alarm": "ch1_alarm", "chiller_flow": "ch1_flow",
        "chiller_temp": "ch1_temp", "chiller_status": "ch1_run", "chw_flow": "ch1_flow",
        "chws_temp": "ch1_temp", "chw_pump": "pp1_run", "chwr_temp": "main_return_temp",
        **{f"{p}_{s}": f"{p}1_{s}" for p in ("pp", "sp")
           for s in ("run", "trip", "flow", "auto", "hand")},
    }

    def configure(self):
        nc, npp, nsp = (self.options[k] for k in ("chillers", "primary", "secondary"))
        self.nc, self.npp, self.nsp = nc, npp, nsp
        pts: List[GraphicPoint] = []
        for i in range(1, nc + 1):
            pts += chiller_points(i, nc == 1)
        for i in range(1, npp + 1):
            pts += pump_points("pp", i, "Primary Pump", ("pchp", "pchwp", "pp"), npp == 1)
        for i in range(1, nsp + 1):
            pts += pump_points("sp", i, "Secondary Pump", ("schp", "schwp", "sp"), nsp == 1)
        self.POINTS = pts + list(NETWORK_POINTS)
        # geometry
        self.x0 = 70
        self.wp = max(nc, npp) * SPACING
        self.xd = self.x0 + self.wp + 20                 # decoupler
        self.sx0 = self.xd + 60                          # secondary section
        self.ws = nsp * SPACING
        self.xm = self.sx0 + self.ws                     # start of network main line
        self.xl = self.xm + 300                          # load
        self.xt = self.xl + 140                          # points table
        self.WIDTH = self.xt + self.TABLE_W + 20
        rows = nc + npp + nsp
        self.HEIGHT = max(700, 70 + self.ROW_H * (rows + 3) + 26 * len(NETWORK_POINTS) + 40)

    # ------------------------------------------------------------------ positions
    def ch_x(self, i: int) -> float:
        return self.x0 + self.wp * (i + 0.5) / self.nc

    def pp_x(self, j: int) -> float:
        return self.x0 + self.wp * (j + 0.5) / self.npp - 50

    def sp_x(self, k: int) -> float:
        return self.sx0 + self.ws * (k + 0.5) / self.nsp - 50

    # ------------------------------------------------------------------ demo
    def demo_value(self, key: str, t: float) -> Tuple[Any, bool]:
        c = t % 90
        if key[:2] in ("ch", "pp", "sp") and key[2].isdigit():
            n = int("".join(ch for ch in key[2:].split("_")[0]))
            what = key.split("_", 1)[1]
            off = n * 23
            run = (c + off) % 90 < 78
            if key.startswith("ch"):
                return {"run": (int(run), False), "alarm": (int(80 < (c + off) % 90 < 86), False),
                        "flow": (int(run), False),
                        "temp": (6.6 + 0.3 * math.sin(t / 8 + n) if run else 11.5, True)}[what]
            trip = 84 < (c + off) % 90 < 89
            hand = key.startswith("sp") and n == 1 and 30 < c < 45
            return {"run": (int(run), False), "trip": (int(trip), False),
                    "flow": (int(run), False), "auto": (int(not hand), False),
                    "hand": (int(hand), False)}[what]
        return {
            "main_supply_temp": (6.9 + 0.3 * math.sin(t / 8), True),
            "main_return_temp": (12.4 + 0.4 * math.sin(t / 10), True),
            "dpt": (95 + 6 * math.sin(t / 4), True),
            "flow_meter": (42 * self.nsp + 5 * math.sin(t / 7), True),
            "load": (520 * self.nc + 180 * math.sin(t / 12), True),
        }[key]

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _live(st: PointState) -> bool:
        return (st.linked and st.online) or st.override

    def _pump_panel(self, d: Drawer, x: float, y: float, prefix: str, title: str,
                    s: Dict[str, PointState], blink: bool):
        """Two-row status panel: RUN TRIP FLOW / AUTO HAND (each lamp clickable for linking)."""
        hand = s[f"{prefix}_hand"].active
        d.rect(x, y, x + 116, y + 104, fill="#fafafa", outline="#b0bec5", width=1.5)
        d.text(x + 58, y + 12, title + ("  HAND" if hand else ""), 8, True,
               (AMBER if blink else "#ffb74d") if hand else STEEL_DARK)
        lamps = [("run", "RUN", GREEN, True), ("trip", "TRIP", RED, False),
                 ("flow", "FLOW", GREEN, True), ("auto", "AUTO", BLUE_LAMP, True),
                 ("hand", "HAND", AMBER, False)]
        for k, (suffix, label, color, steady) in enumerate(lamps):
            key = f"{prefix}_{suffix}"
            st = s[key]
            cx = x + 22 + (k % 3) * 36
            cy = y + 36 + (k // 3) * 40
            on = st.active and (st.linked or st.override)
            d.lamp(cx, cy, on, True if steady else blink, color, "", point=key)
            d.text(cx, cy + 18, label, 7, True, color if on else GREY, point=key)

    def _inline_temp(self, d: Drawer, cx: float, cy: float, key: str, s: Dict[str, PointState],
                     dx: float = 24, dy: float = 0, title: str = "", color: str = TEXT):
        st = s[key]
        d.sensor(cx, cy, "TT", st, point=key)
        val = f"{st.num:.1f} °C" if st.num is not None and self._live(st) else "--"
        if title:
            d.text(cx + dx, cy + dy - 8, title, 8, True, color, anchor="w", point=key)
            d.text(cx + dx, cy + dy + 8, val, 10, True, "#2e5c8a", anchor="w", point=key)
        else:
            d.text(cx + dx, cy + dy, val, 10, True, "#2e5c8a", anchor="w", point=key)

    # ------------------------------------------------------------------ drawing
    def draw(self, d: Drawer, s: Dict[str, PointState], t: float):
        blink = int(t * 2.5) % 2 == 0
        y_sup, y_in, y_ret, y_dis = 90, 430, 640, 320
        pp_on = [s[f"pp{j + 1}_run"].active for j in range(self.npp)]
        sp_on = [s[f"sp{k + 1}_run"].active for k in range(self.nsp)]
        any_pp, any_sp = any(pp_on), any(sp_on)

        def ch_flowing(i: int) -> bool:
            fs = s[f"ch{i}_flow"]
            return fs.active if (fs.linked or fs.override) else any_pp

        chx = [self.ch_x(i) for i in range(self.nc)]
        ppx = [self.pp_x(j) for j in range(self.npp)]
        spx = [self.sp_x(k) for k in range(self.nsp)]

        # titles
        d.text(self.x0 - 40, 52, "PRIMARY CIRCUIT", 10, True, STEEL_DARK, anchor="w")
        d.text(self.sx0 - 20, 52, "SECONDARY", 10, True, STEEL_DARK, anchor="w")
        d.text(self.xm + 30, 52, "NETWORK", 10, True, STEEL_DARK, anchor="w")

        # ---------------- headers
        d.pipe([min(chx) + 55, y_sup, max(spx), y_sup], WATER_SUPPLY, any_pp or any_sp, t)
        d.text(min(chx) + 60, y_sup - 18, "CHW SUPPLY HEADER", 7, True, WATER_SUPPLY, anchor="w")
        d.pipe([min(min(chx) - 55, min(ppx)), y_in, max(max(chx) - 55, max(ppx)), y_in],
               WATER_RETURN, any_pp, t)
        d.text(min(min(chx) - 55, min(ppx)) - 6, y_in, "CHILLER INLET", 7, True, WATER_RETURN,
               anchor="e")
        d.pipe([self.xd, y_ret, min(ppx), y_ret], WATER_RETURN, any_pp, t)
        d.text(min(ppx) - 6, y_ret, "PRIMARY RETURN", 7, True, WATER_RETURN, anchor="e")
        d.pipe([self.xd, y_sup, self.xd, y_ret], DECOUPLER, any_pp or any_sp, t, 0.4, width=5)
        d.text(self.xd + 10, (y_sup + y_ret) / 2, "DECOUPLER", 7, True, DECOUPLER, anchor="w")
        d.pipe([min(spx), y_dis, self.xl, y_dis], WATER_SUPPLY, any_sp, t)
        d.pipe([self.xl, y_ret, self.xd, y_ret], WATER_RETURN, any_sp, t)

        # ---------------- chillers
        for i, cx in enumerate(chx, start=1):
            run, alarm = s[f"ch{i}_run"], s[f"ch{i}_alarm"]
            flowing = ch_flowing(i)
            d.pipe([cx + 55, 200, cx + 55, y_sup], WATER_SUPPLY, flowing, t)
            d.pipe([cx - 55, 330, cx - 55, y_in], WATER_RETURN, flowing, t)
            d.chiller(cx - 85, 200, cx + 85, 330, run.active, alarm.active, blink, 0, t,
                      point=f"ch{i}_run", show_load=False)
            d.text(cx - 80, 188, f"CHILLER {i}", 9, True, STEEL_DARK, anchor="w",
                   point=f"ch{i}_run")
            self._inline_temp(d, cx + 55, 145, f"ch{i}_temp", s, dx=22)
            fs = s[f"ch{i}_flow"]
            d.lamp(cx - 20, 350, fs.active and (fs.linked or fs.override), True, GREEN, "",
                   point=f"ch{i}_flow")
            d.text(cx - 20, 371, "FLOW", 7, True, GREEN if fs.active else GREY, point=f"ch{i}_flow")
            d.lamp(cx + 25, 350, alarm.active, blink, RED, "", point=f"ch{i}_alarm")
            d.text(cx + 25, 371, "ALARM", 7, True, RED if alarm.active else GREY,
                   point=f"ch{i}_alarm")
            if run.active and (fs.linked or fs.override) and not fs.active:
                d.text(cx, 392, "NO FLOW", 8, True, AMBER if blink else "#ffcc80")

        # ---------------- primary pumps
        for j, px in enumerate(ppx, start=1):
            on = pp_on[j - 1]
            d.pipe([px, y_ret, px, y_in], WATER_RETURN, on, t)
            d.pump(px, 535, 26, on, 1.0, t, point=f"pp{j}_run",
                   fault=s[f"pp{j}_trip"].active and blink)
            self._pump_panel(d, px + 38, 470, f"pp{j}", f"PCHP-{j}", s, blink)

        # ---------------- secondary pumps
        for k, sx in enumerate(spx, start=1):
            on = sp_on[k - 1]
            d.pipe([sx, y_sup, sx, y_dis], WATER_SUPPLY, on, t)
            d.pump(sx, 205, 26, on, 1.0, t, point=f"sp{k}_run",
                   fault=s[f"sp{k}_trip"].active and blink)
            self._pump_panel(d, sx + 38, 140, f"sp{k}", f"SCHP-{k}", s, blink)

        # ---------------- network
        self._inline_temp(d, self.xm + 40, y_dis, "main_supply_temp", s, dx=0, dy=-42,
                          title="MAIN SUPPLY", color=WATER_SUPPLY)
        fm = s["flow_meter"]
        fx = self.xm + 150
        d.rect(fx - 20, y_dis - 14, fx + 20, y_dis + 14,
               fill="#e3f2fd" if self._live(fm) else "#f5f5f5", outline=STEEL_DARK, width=2,
               point="flow_meter")
        d.text(fx, y_dis, "FM", 8, True, TEXT, point="flow_meter")
        d.text(fx, y_dis - 40, "FLOW", 8, True, STEEL_DARK, point="flow_meter")
        d.text(fx, y_dis - 26, f"{fm.num:.1f}" if fm.num is not None and self._live(fm) else "--",
               10, True, "#2e5c8a", point="flow_meter")
        dpt = s["dpt"]
        dx = self.xm + 225
        d.line([dx, y_dis + 14, dx, 460], fill=GREY, width=2)
        d.line([dx, y_ret, dx, 500], fill=GREY, width=2)
        d.sensor(dx, 480, "DPT", dpt, point="dpt")
        d.text(dx - 24, 473, f"{dpt.num:.0f} kPa" if dpt.num is not None and self._live(dpt) else "--",
               10, True, "#2e5c8a", anchor="e", point="dpt")
        d.text(dx - 24, 489, "NETWORK DP", 7, True, STEEL_DARK, anchor="e", point="dpt")
        self._inline_temp(d, self.xm + 40, y_ret, "main_return_temp", s, dx=0, dy=42,
                          title="MAIN RETURN", color=WATER_RETURN)

        # ---------------- load
        ld = s["load"]
        d.rect(self.xl, 290, self.xl + 80, 670, fill="#e3f2fd", outline=STEEL_DARK, width=2,
               point="load")
        for k in range(5):
            y = 335 + k * 62
            d.coil(self.xl + 12, y, self.xl + 68, y + 40, 0.6 if any_sp else 0.0, point="load")
        d.text(self.xl + 40, 278, "LOAD", 10, True, STEEL_DARK, point="load")
        if self._live(ld) and ld.num is not None:
            d.text(self.xl + 40, 686, f"{ld.num:.0f}", 10, True, "#2e5c8a", point="load")

        self._points_table(d, s, blink)

    # ------------------------------------------------------------------ points table (right side)
    def _points_table(self, d: Drawer, s: Dict[str, PointState], blink: bool):
        """One row per chiller / pump with a lamp per point, then the network values.
        Every cell is clickable for linking, like the elements of the drawing."""
        x, y, w, rh = self.xt, 40, self.TABLE_W, self.ROW_H
        cols = [("RUN", "run", GREEN), ("ALARM", None, RED), ("FLOW", "flow", GREEN),
                ("AUTO", "auto", BLUE_LAMP), ("HAND", "hand", AMBER), ("TEMP", "temp", None)]
        cx0, cw = x + 92, 58
        d.text(x, y - 12, "POINTS", 9, True, STEEL_DARK, anchor="w")
        d.rect(x, y, x + w, y + rh, fill="#eceff1", outline="#b0bec5", width=1)
        d.text(x + 8, y + rh / 2, "UNIT", 8, True, STEEL_DARK, anchor="w")
        for k, (title, _, _) in enumerate(cols):
            d.text(cx0 + k * cw + cw / 2, y + rh / 2, title, 7, True, STEEL_DARK)

        units = [(f"CHILLER {i}", f"ch{i}", True) for i in range(1, self.nc + 1)] + \
                [(f"PCHP-{j}", f"pp{j}", False) for j in range(1, self.npp + 1)] + \
                [(f"SCHP-{k}", f"sp{k}", False) for k in range(1, self.nsp + 1)]
        yy = y + rh
        for n, (name, pre, is_ch) in enumerate(units):
            d.rect(x, yy, x + w, yy + rh, fill="#ffffff" if n % 2 == 0 else "#f7f9fa",
                   outline="#e0e0e0", width=1)
            d.text(x + 8, yy + rh / 2, name, 8, True, TEXT, anchor="w")
            for k, (_title, suffix, color) in enumerate(cols):
                if suffix is None:
                    suffix, color = ("alarm" if is_ch else "trip"), RED
                key = f"{pre}_{suffix}"
                if key not in s:
                    d.text(cx0 + k * cw + cw / 2, yy + rh / 2, "–", 8, False, GREY)
                    continue
                st = s[key]
                ccx = cx0 + k * cw + cw / 2
                if suffix == "temp":
                    val = f"{st.num:.1f}°" if st.num is not None and self._live(st) else "--"
                    d.text(ccx, yy + rh / 2, val, 9, True, "#2e5c8a", point=key)
                    d.hotspot(ccx - 26, yy + 2, ccx + 26, yy + rh - 2, key)
                    continue
                on = st.active and (st.linked or st.override)
                alarm = suffix in ("alarm", "trip")
                fill = (color if (blink or not alarm) else "#ffcdd2") if on else \
                    ("#ffffff" if (st.linked or st.override) else "#eceff1")
                d.oval(ccx, yy + rh / 2, 8, fill=fill, outline=GREY if not st.linked and not st.override
                       else STEEL_DARK, width=1.5, point=key)
                d.hotspot(ccx - 14, yy + 3, ccx + 14, yy + rh - 3, key)
            yy += rh
        # network values
        yy += 14
        d.text(x, yy, "NETWORK", 9, True, STEEL_DARK, anchor="w")
        yy += 10
        for p in NETWORK_POINTS:
            st = s[p.key]
            d.rect(x, yy, x + w, yy + 26, fill="#ffffff", outline="#e0e0e0", width=1, point=p.key)
            d.text(x + 8, yy + 13, p.label, 8, True, TEXT, anchor="w", point=p.key)
            live = self._live(st)
            txt = st.text if (live and st.text not in ("not linked", "")) else \
                ("waiting…" if st.linked else "not linked")
            d.text(x + w - 10, yy + 13, txt, 9, True, "#2e5c8a" if live else GREY, anchor="e",
                   point=p.key)
            yy += 26


TEMPLATE = ChillerGraphic
