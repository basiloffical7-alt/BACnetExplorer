"""
Base class and drawing toolkit for animated equipment graphics.

To add a new equipment graphic (chiller, FCU, pump set, ...), create a new file in this
folder, e.g. ``graphics/fcu.py``::

    from graphics.base import GraphicTemplate, GraphicPoint

    class FCUGraphic(GraphicTemplate):
        TEMPLATE_ID = "fcu"                    # unique, never change once pages use it
        NAME = "Fan Coil Unit"
        WIDTH, HEIGHT = 1000, 520              # logical drawing size
        POINTS = [
            GraphicPoint("fan", "Fan Status", "binary", "Rotates when active"),
            GraphicPoint("valve", "CHW Valve", "analog", "Opening 0-100 %"),
        ]

        def draw(self, d, states, t):
            # d is a Drawer: draw in logical coordinates, it scales to the canvas.
            fan = states["fan"]
            d.fan(500, 260, 60, running=fan.active, speed=fan.speed, point="fan")
            d.value_box(440, 360, "fan", fan)

    TEMPLATE = FCUGraphic                      # the explorer picks this up automatically

Every element drawn with ``point="key"`` becomes clickable for linking BACnet points.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:  # pragma: no cover
    import tkinter as tk

# palette
STEEL = "#cfd8dc"
STEEL_DARK = "#78909c"
OUTLINE = "#455a64"
AIR = "#4fc3f7"
WATER_SUPPLY = "#1565c0"
WATER_RETURN = "#c62828"
GREEN = "#2e7d32"
GREEN_LIGHT = "#66bb6a"
RED = "#e53935"
AMBER = "#ffa000"
GREY = "#9e9e9e"
TEXT = "#263238"


@dataclass
class GraphicPoint:
    key: str
    label: str
    kind: str = "any"        # 'binary', 'analog' or 'any' - a hint for the user
    help: str = ""
    alarm_when_active: bool = False   # e.g. filter dirty switch
    match: List[str] = field(default_factory=list)
    """Name patterns for Auto-link, e.g. ["supply fan status", "sf sts"]. Every word of a
    pattern must appear in the BACnet object name. Empty -> the label is used."""


@dataclass
class PointState:
    """Interpreted value of a graphic point, ready for drawing."""
    linked: bool = False
    value: Any = None
    text: str = "not linked"
    active: bool = False
    percent: float = 0.0       # 0..100 (binary -> 0 / 100)
    is_analog: bool = False
    online: bool = False       # value received recently
    override: bool = False     # demo / test value

    @property
    def num(self) -> Optional[float]:
        """Raw numeric value (for sensors such as CO2 ppm or pressure), or None."""
        try:
            return float(self.value) if self.value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def speed(self) -> float:
        """0..1 animation speed factor."""
        if not self.active:
            return 0.0
        return max(0.25, self.percent / 100.0) if self.is_analog else 1.0


class Drawer:
    """Draws on a Tk canvas in logical coordinates, scaled and centred."""

    def __init__(self, canvas: "tk.Canvas", width: int, height: int, highlight: Optional[str] = None,
                 dark: bool = False, min_scale: float = 0.0, scale: Optional[float] = None):
        self.cv = canvas
        cw = max(canvas.winfo_width(), 50)
        ch = max(canvas.winfo_height(), 50)
        # scale=None -> fit the whole drawing in the window; otherwise a fixed zoom (canvas scrolls)
        self.k = scale if scale else max(min(cw / width, ch / height), min_scale)
        # centre when it fits, otherwise start at 0 (the canvas scrolls)
        self.ox = max(0.0, (cw - width * self.k) / 2)
        self.oy = max(0.0, (ch - height * self.k) / 2)
        self.width_px = width * self.k + 2 * self.ox
        self.height_px = height * self.k + 2 * self.oy
        self.highlight = highlight
        self.dark = dark
        self._cache: Dict[Tuple[str, str], str] = {}

    # ---- dark mode: light fills become dark, dark text/lines become light
    DARK_BG = (30, 34, 39)

    def c(self, color: Any, role: str = "fill") -> Any:
        if not self.dark or not isinstance(color, str) or len(color) != 7 or color[0] != "#":
            return color
        key = (color, role)
        if key in self._cache:
            return self._cache[key]
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        mx, mn = max(r, g, b), min(r, g, b)
        sat = (mx - mn) / mx if mx else 0.0
        out = color
        if role in ("line", "text") and sat > 0.35:
            # coloured ink (water, alarms, status): keep the hue, just lift it a little
            if lum < 0.5:
                k = 0.30
                out = "#%02x%02x%02x" % (int(r + (255 - r) * k), int(g + (255 - g) * k),
                                         int(b + (255 - b) * k))
        elif role == "line" and lum > 0.85:
            # pale halo / casing lines -> subtle dark grey so pipes keep their colour
            out = "#3a434a"
        elif role == "fill" and lum > 0.72:
            # pale fill -> dark tinted panel keeping a hint of the hue
            k = 0.16 + 0.10 * (1 - lum)
            br, bg_, bb = self.DARK_BG
            out = "#%02x%02x%02x" % (int(br + (r - br) * k), int(bg_ + (g - bg_) * k),
                                     int(bb + (b - bb) * k))
        elif role in ("line", "text") and lum < 0.45:
            # dark ink -> light ink
            k = 0.72
            out = "#%02x%02x%02x" % (int(r + (255 - r) * k), int(g + (255 - g) * k),
                                     int(b + (255 - b) * k))
        self._cache[key] = out
        return out

    # ---- coordinate helpers
    def X(self, x: float) -> float:
        return self.ox + x * self.k

    def Y(self, y: float) -> float:
        return self.oy + y * self.k

    def pts(self, coords: Sequence[float]) -> List[float]:
        return [self.X(v) if i % 2 == 0 else self.Y(v) for i, v in enumerate(coords)]

    def font(self, size: int, bold: bool = False):
        # negative size = pixels: text shrinks with the drawing instead of stopping at 6 pt
        px = max(7, int(round(size * self.k * 1.33)))
        return ("Segoe UI", -px, "bold" if bold else "normal")

    def _tags(self, point: Optional[str]):
        return ("pt", f"pt:{point}") if point else ()

    def lw(self, w: float) -> float:
        return max(1.0, w * self.k)

    # ---- primitives
    def rect(self, x1, y1, x2, y2, fill="", outline=OUTLINE, width: float = 2, point=None, **kw):
        return self.cv.create_rectangle(self.X(x1), self.Y(y1), self.X(x2), self.Y(y2),
                                        fill=self.c(fill), outline=self.c(outline, "line"),
                                        width=self.lw(width),
                                        tags=self._tags(point), **kw)

    def oval(self, cx, cy, r, fill="", outline=OUTLINE, width: float = 2, point=None, **kw):
        return self.cv.create_oval(self.X(cx - r), self.Y(cy - r), self.X(cx + r), self.Y(cy + r),
                                   fill=self.c(fill), outline=self.c(outline, "line"),
                                   width=self.lw(width),
                                   tags=self._tags(point), **kw)

    def line(self, coords: Sequence[float], fill=OUTLINE, width: float = 2, point=None, **kw):
        return self.cv.create_line(*self.pts(coords), fill=self.c(fill, "line"), width=self.lw(width),
                                   tags=self._tags(point), **kw)

    def poly(self, coords: Sequence[float], fill="", outline=OUTLINE, width: float = 2, point=None, **kw):
        return self.cv.create_polygon(*self.pts(coords), fill=self.c(fill), outline=self.c(outline, "line"),
                                      width=self.lw(width), tags=self._tags(point), **kw)

    def text(self, x, y, txt, size=11, bold=False, fill=TEXT, anchor: Any = "center", point=None):
        if size * self.k * 1.33 < 5.0:      # too small to read at this zoom: keep the overview clean
            return None
        return self.cv.create_text(self.X(x), self.Y(y), text=txt, font=self.font(size, bold),
                                   fill=self.c(fill, "text"), anchor=anchor, tags=self._tags(point))

    def hotspot(self, x1, y1, x2, y2, point: str):
        """Invisible clickable area (plus selection frame when highlighted)."""
        sel = self.highlight == point
        self.cv.create_rectangle(self.X(x1), self.Y(y1), self.X(x2), self.Y(y2),
                                 outline="#ff9800" if sel else "", dash=(4, 3) if sel else (),
                                 width=self.lw(2), fill="", tags=self._tags(point))

    # ---- HVAC symbols
    def duct(self, x1, y1, x2, y2, label: str = ""):
        self.rect(x1, y1, x2, y2, fill="#eceff1", outline=STEEL_DARK, width=2)
        if label:
            self.text((x1 + x2) / 2, y1 - 14, label, 10, True, STEEL_DARK)

    def air_arrows(self, x1, x2, y, t: float, speed: float, rows: Sequence[float] = (0,),
                   spacing: float = 60, color: str = AIR, direction: int = 1):
        """Moving chevrons when air flows; static faint arrows otherwise.
        direction: 1 = right, -1 = left, 2 = down, -2 = up (x1..x2 is then the y range, y the x)."""
        offset = (t * 120 * speed) % spacing if speed > 0 else 0
        col = color if speed > 0 else "#cfd8dc"
        for dy in rows:
            k = offset
            while x1 + k < x2 - 12:
                a = x1 + k if direction > 0 else x2 - k
                if direction == 1:
                    c = [a, y + dy - 8, a + 12, y + dy, a, y + dy + 8]
                elif direction == -1:
                    c = [a, y + dy - 8, a - 12, y + dy, a, y + dy + 8]
                elif direction == 2:
                    c = [y + dy - 8, a, y + dy, a + 12, y + dy + 8, a]
                else:
                    c = [y + dy - 8, a, y + dy, a - 12, y + dy + 8, a]
                self.line(c, fill=col, width=3, capstyle="round", joinstyle="round")
                k += spacing

    def fan(self, cx, cy, r, running: bool, speed: float = 1.0, t: float = 0.0,
            point: Optional[str] = None, fault: bool = False):
        housing = GREEN_LIGHT if running else STEEL
        if fault:
            housing = RED
        self.oval(cx, cy, r + 8, fill="#fafafa", outline=OUTLINE, width=3, point=point)
        self.oval(cx, cy, r, fill=housing, outline=OUTLINE, width=2, point=point)
        angle = (t * 6.0 * speed) if running else 0.0
        for k in range(4):
            a = angle + k * math.pi / 2
            p1 = (cx + math.cos(a) * r * 0.15, cy + math.sin(a) * r * 0.15)
            tip = (cx + math.cos(a + 0.25) * r * 0.9, cy + math.sin(a + 0.25) * r * 0.9)
            p2 = (cx + math.cos(a + 0.75) * r * 0.55, cy + math.sin(a + 0.75) * r * 0.55)
            self.poly([*p1, *tip, *p2], fill="#ffffff", outline=OUTLINE, width=1.5, point=point,
                      smooth=True)
        self.oval(cx, cy, r * 0.16, fill=OUTLINE, outline=OUTLINE, width=1, point=point)
        self.hotspot(cx - r - 12, cy - r - 12, cx + r + 12, cy + r + 12, point or "")

    def damper(self, x, y1, y2, open_pct: float, point: Optional[str] = None, blades: int = 4,
               color: str = STEEL_DARK):
        """Opposed-blade damper drawn across a horizontal duct. 0 % = closed (blades vertical)."""
        self.rect(x - 22, y1, x + 22, y2, fill="#f5f5f5", outline=OUTLINE, width=2, point=point)
        h = (y2 - y1) / blades
        ang = math.radians(90 - 90 * max(0.0, min(100.0, open_pct)) / 100)
        for b in range(blades):
            cy = y1 + h * (b + 0.5)
            a = ang if b % 2 == 0 else -ang
            dx, dy = math.cos(a) * h * 0.55, math.sin(a) * h * 0.55
            self.line([x - dx, cy - dy, x + dx, cy + dy], fill=color, width=6, point=point,
                      capstyle="round")
            self.oval(x, cy, 3, fill=OUTLINE, outline=OUTLINE, width=1, point=point)
        self.hotspot(x - 30, y1 - 6, x + 30, y2 + 6, point or "")

    def filter(self, x1, y1, x2, y2, dirty: bool, blink: bool, point: Optional[str] = None):
        fill = "#ffcdd2" if dirty and blink else "#fff8e1"
        self.rect(x1, y1, x2, y2, fill=fill, outline=OUTLINE, width=2, point=point)
        n = 10
        h = (y2 - y1) / n
        coords: List[float] = []
        for k in range(n + 1):
            coords += [x1 + 6 if k % 2 == 0 else x2 - 6, y1 + k * h]
        self.line(coords, fill=RED if dirty else "#a1887f", width=2, point=point)
        self.hotspot(x1 - 6, y1 - 6, x2 + 6, y2 + 6, point or "")

    def coil(self, x1, y1, x2, y2, intensity: float, point: Optional[str] = None):
        """Cooling coil; colour deepens with valve opening (0..1)."""
        i = max(0.0, min(1.0, intensity))
        r = int(227 - 140 * i); g = int(242 - 90 * i); b = int(253 - 20 * i)
        self.rect(x1, y1, x2, y2, fill=f"#{r:02x}{g:02x}{b:02x}", outline=OUTLINE, width=2,
                  point=point)
        for k in range(1, 8):
            x = x1 + (x2 - x1) * k / 8
            self.line([x, y1 + 4, x, y2 - 4], fill="#90caf9" if i < 0.05 else WATER_SUPPLY,
                      width=1, point=point)
        for k in range(1, 6):
            y = y1 + (y2 - y1) * k / 6
            self.line([x1 + 3, y, x2 - 3, y], fill="#b0bec5", width=1, point=point)

    def pipe(self, coords: Sequence[float], color: str, flowing: bool, t: float,
             speed: float = 1.0, width: float = 6):
        self.line(coords, fill="#eceff1" if not flowing else "#e3f2fd", width=width + 4,
                  capstyle="round", joinstyle="round")
        if flowing:
            off = -int(t * 40 * max(speed, 0.3)) % 20
            self.line(coords, fill=color, width=width, dash=(10, 10), dashoffset=off,
                      capstyle="butt", joinstyle="round")
        else:
            self.line(coords, fill=GREY, width=width - 2, capstyle="round", joinstyle="round")

    def valve(self, cx, cy, pct: float, point: Optional[str] = None, size: float = 22):
        """2-way valve (bow-tie) with actuator and opening bar."""
        p = max(0.0, min(100.0, pct)) / 100
        col = WATER_SUPPLY if p > 0.01 else STEEL
        s = size
        self.poly([cx - s, cy - s * 0.7, cx, cy, cx - s, cy + s * 0.7], fill=col, point=point)
        self.poly([cx + s, cy - s * 0.7, cx, cy, cx + s, cy + s * 0.7], fill=col, point=point)
        self.line([cx, cy, cx, cy - s * 1.4], width=3, point=point)
        self.rect(cx - s * 0.8, cy - s * 2.4, cx + s * 0.8, cy - s * 1.4, fill="#eceff1",
                  point=point)
        # opening indicator bar on the actuator
        self.rect(cx - s * 0.7, cy - s * 2.0, cx - s * 0.7 + s * 1.4 * p, cy - s * 1.8,
                  fill=GREEN if p > 0.01 else GREY, outline="", width=0, point=point)
        self.hotspot(cx - s - 8, cy - s * 2.6, cx + s + 8, cy + s + 8, point or "")

    def dps(self, cx, cy, active: bool, alarm_mode: bool, blink: bool,
            point: Optional[str] = None, label: str = "DPS"):
        """Differential pressure switch: diaphragm symbol, coloured by state."""
        if active:
            fill = (RED if blink else "#ffcdd2") if alarm_mode else GREEN_LIGHT
        else:
            fill = "#eceff1"
        self.rect(cx - 30, cy - 22, cx + 30, cy + 22, fill=fill, outline=OUTLINE, width=2,
                  point=point)
        # diaphragm bends when switch is made
        bend = 9 if active else 0
        self.line([cx - 20, cy, cx, cy - bend, cx + 20, cy], width=3, smooth=True, point=point)
        self.text(cx, cy + 12, label, 8, True, TEXT, point=point)
        self.hotspot(cx - 36, cy - 28, cx + 36, cy + 28, point or "")

    def value_box(self, x, y, label: str, st: PointState, width: float = 150,
                  point: Optional[str] = None):
        """Label + value badge. Grey when not linked, orange text when in demo override."""
        if not st.linked and not st.override:
            col, val = GREY, "not linked"
        elif not st.online and not st.override:
            col, val = AMBER, "waiting…"
        else:
            col, val = (AMBER if st.override else TEXT), st.text
        self.rect(x, y, x + width, y + 40, fill="#ffffff", outline="#b0bec5", width=1, point=point)
        self.text(x + 6, y + 12, label, 9, False, STEEL_DARK, anchor="w", point=point)
        self.text(x + 6, y + 29, val, 11, True, col, anchor="w", point=point)
        dot = GREEN if (st.linked and st.online) else (AMBER if st.linked else GREY)
        self.oval(x + width - 10, y + 10, 4, fill=dot, outline="", width=0, point=point)

    # ---- more equipment symbols
    def damper_h(self, x1, x2, y, open_pct: float, point: Optional[str] = None, blades: int = 4):
        """Damper in a horizontal partition (air flows vertically). 0 % = closed."""
        self.rect(x1, y - 20, x2, y + 20, fill="#f5f5f5", outline=OUTLINE, width=2, point=point)
        w = (x2 - x1) / blades
        ang = math.radians(90 * max(0.0, min(100.0, open_pct)) / 100)
        for b in range(blades):
            cx = x1 + w * (b + 0.5)
            a = ang if b % 2 == 0 else -ang
            dx, dy = math.cos(a) * w * 0.55, math.sin(a) * w * 0.55
            self.line([cx - dx, y - dy, cx + dx, y + dy], fill=STEEL_DARK, width=6, point=point,
                      capstyle="round")
            self.oval(cx, y, 3, fill=OUTLINE, outline=OUTLINE, width=1, point=point)
        self.hotspot(x1 - 6, y - 26, x2 + 6, y + 26, point or "")

    def bag_filter(self, x1, y1, x2, y2, dirty: bool, blink: bool, point: Optional[str] = None,
                   bags: int = 4):
        fill = "#ffcdd2" if dirty and blink else "#fff8e1"
        self.rect(x1, y1, x1 + 8, y2, fill=STEEL, outline=OUTLINE, width=1.5, point=point)
        h = (y2 - y1) / bags
        for b in range(bags):
            ya, yb = y1 + b * h + 3, y1 + (b + 1) * h - 3
            self.poly([x1 + 8, ya, x2, (ya + yb) / 2 - 3, x2, (ya + yb) / 2 + 3, x1 + 8, yb],
                      fill=fill, outline=RED if dirty else "#a1887f", width=1.5, point=point)
        self.hotspot(x1 - 6, y1 - 6, x2 + 6, y2 + 6, point or "")

    def pump(self, cx, cy, r, running: bool, speed: float = 1.0, t: float = 0.0,
             point: Optional[str] = None, fault: bool = False, outlet: str = "up"):
        """Centrifugal pump: volute + rotating impeller."""
        body = RED if fault else (GREEN_LIGHT if running else STEEL)
        if outlet == "up":
            self.rect(cx + r * 0.3, cy - r - 14, cx + r * 0.95, cy - r * 0.4, fill=body, point=point)
        elif outlet == "left":
            self.rect(cx - r - 14, cy - r * 0.95, cx - r * 0.4, cy - r * 0.3, fill=body, point=point)
        else:
            self.rect(cx + r * 0.4, cy - r * 0.95, cx + r + 14, cy - r * 0.3, fill=body, point=point)
        self.oval(cx, cy, r, fill=body, outline=OUTLINE, width=2.5, point=point)
        angle = t * 7.0 * speed if running else 0.0
        for k in range(5):
            a = angle + k * 2 * math.pi / 5
            p1 = (cx + math.cos(a) * r * 0.18, cy + math.sin(a) * r * 0.18)
            pm = (cx + math.cos(a + 0.35) * r * 0.55, cy + math.sin(a + 0.35) * r * 0.55)
            p2 = (cx + math.cos(a + 0.8) * r * 0.82, cy + math.sin(a + 0.8) * r * 0.82)
            self.line([*p1, *pm, *p2], fill="#ffffff", width=3, smooth=True, point=point)
        self.oval(cx, cy, r * 0.18, fill=OUTLINE, outline=OUTLINE, width=1, point=point)
        self.hotspot(cx - r - 10, cy - r - 18, cx + r + 18, cy + r + 10, point or "")

    def check_valve(self, cx, cy, vertical: bool = True):
        if vertical:
            self.poly([cx - 10, cy + 8, cx + 10, cy + 8, cx, cy - 8], fill="#eceff1")
            self.line([cx - 10, cy - 8, cx + 10, cy - 8], width=2)
        else:
            self.poly([cx - 8, cy - 10, cx - 8, cy + 10, cx + 8, cy], fill="#eceff1")
            self.line([cx + 8, cy - 10, cx + 8, cy + 10], width=2)

    def iso_valve(self, cx, cy, vertical: bool = True, open_: bool = True):
        col = "#eceff1" if open_ else "#ffcdd2"
        if vertical:
            self.poly([cx - 9, cy - 10, cx + 9, cy - 10, cx - 9, cy + 10, cx + 9, cy + 10], fill=col)
        else:
            self.poly([cx - 10, cy - 9, cx - 10, cy + 9, cx + 10, cy - 9, cx + 10, cy + 9], fill=col)

    def sensor(self, cx, cy, tag: str, st: PointState, point: Optional[str] = None,
               stem: float = 0, color: Optional[str] = None):
        """Instrument bubble (TT, DPT, CO2...). Stem goes down `stem` units into the duct/pipe."""
        live = st.linked and st.online or st.override
        if stem > 0:
            self.line([cx, cy + 16, cx, cy + 16 + stem], fill=OUTLINE, width=2)
        elif stem < 0:
            self.line([cx, cy - 16, cx, cy - 16 + stem], fill=OUTLINE, width=2)
        self.oval(cx, cy, 17, fill=color or ("#e3f2fd" if live else "#f5f5f5"),
                  outline=OUTLINE, width=2, point=point)
        self.text(cx, cy, tag, 8, True, TEXT, point=point)
        self.hotspot(cx - 20, cy - 20, cx + 20, cy + 20, point or "")

    def level_bar(self, x, y, w, h, frac: float, color: str):
        f = max(0.0, min(1.0, frac))
        self.rect(x, y, x + w, y + h, fill="#eceff1", outline="#b0bec5", width=1)
        if f > 0:
            self.rect(x, y, x + w * f, y + h, fill=color, outline="", width=0)

    def lamp(self, cx, cy, on: bool, blink: bool, color: str = RED, label: str = "",
             point: Optional[str] = None):
        fill = (color if blink else "#ffcdd2") if on else "#eceff1"
        self.oval(cx, cy, 11, fill=fill, outline=OUTLINE, width=2, point=point)
        if label:
            self.text(cx, cy + 22, label, 8, True, color if on else GREY, point=point)
        self.hotspot(cx - 16, cy - 16, cx + 16, cy + 16, point or "")

    def vfd(self, x, y, st: PointState, running: bool, point: Optional[str] = None):
        """Variable speed drive box with a Hz read-out (assumes 0-100 % = 0-50 Hz)."""
        self.rect(x, y, x + 70, y + 60, fill="#37474f", outline=OUTLINE, width=2, point=point)
        hz = (st.percent / 2 if st.is_analog else (50.0 if st.active else 0.0)) if (st.linked or st.override) else None
        txt = f"{hz:4.1f}Hz" if hz is not None else "--.-Hz"
        self.rect(x + 8, y + 8, x + 62, y + 28, fill="#102027", outline="", width=0, point=point)
        self.text(x + 35, y + 18, txt, 9, True, "#76ff03" if running else "#90a4ae", point=point)
        self.text(x + 35, y + 44, "VFD", 9, True, "#eceff1", point=point)
        self.hotspot(x - 4, y - 4, x + 74, y + 64, point or "")

    def grille(self, x, y1, y2, label: str = ""):
        self.rect(x - 6, y1, x + 6, y2, fill="#eceff1", outline=OUTLINE, width=1.5)
        k = y1 + 6
        while k < y2 - 3:
            self.line([x - 5, k, x + 5, k + 4], fill=STEEL_DARK, width=1.5)
            k += 9
        if label:
            self.text(x, y2 + 14, label, 8, True, STEEL_DARK)

    def louvre(self, x, y1, y2, label: str = ""):
        self.rect(x - 10, y1, x + 10, y2, fill="#eceff1", outline=OUTLINE, width=2)
        k = y1 + 8
        while k < y2 - 4:
            self.line([x - 9, k + 6, x + 9, k], fill=STEEL_DARK, width=2.5)
            k += 12
        if label:
            self.text(x, y1 - 12, label, 9, True, STEEL_DARK)

    def thermostat(self, x, y, temp: PointState, sp: Optional[PointState] = None,
                   point: Optional[str] = None):
        self.rect(x, y, x + 96, y + 70, fill="#fafafa", outline=OUTLINE, width=2, point=point)
        t = temp.num if (temp.linked and temp.online) or temp.override else None
        self.text(x + 48, y + 26, f"{t:.1f}°" if t is not None else "--.-°", 16, True, TEXT, point=point)
        if sp is not None:
            v = sp.num if (sp.linked and sp.online) or sp.override else None
            self.text(x + 48, y + 54, f"SP {v:.1f}°" if v is not None else "SP --", 9, False,
                      STEEL_DARK, point=point)
        self.hotspot(x - 4, y - 4, x + 100, y + 74, point or "")

    def cooling_tower(self, x1, y1, x2, y2, fan_on: bool, speed: float, t: float,
                      point: Optional[str] = None):
        cx = (x1 + x2) / 2
        self.poly([x1 + 20, y1 + 40, x2 - 20, y1 + 40, x2, y2, x1, y2], fill="#eceff1",
                  outline=OUTLINE, width=2)
        for k in range(1, 6):  # fill media
            y = y1 + 40 + (y2 - y1 - 40) * k / 6
            self.line([x1 + 8, y, x2 - 8, y], fill="#b0bec5", width=1)
        self.rect(x1 + 30, y1 + 6, x2 - 30, y1 + 40, fill=STEEL, outline=OUTLINE, width=2, point=point)
        # fan seen from the side: blade sweep
        w = (x2 - x1 - 70) / 2
        ph = math.cos(t * 9 * max(speed, 0.3)) if fan_on else 1.0
        self.line([cx - w * ph, y1 + 4, cx + w * ph, y1 + 4], fill=GREEN if fan_on else OUTLINE,
                  width=6, point=point, capstyle="round")
        self.line([cx, y1 + 4, cx, y1 + 20], width=3, point=point)
        if fan_on:
            off = (t * 40) % 20
            for dx in (-w * 0.6, 0, w * 0.6):
                self.line([cx + dx, y1 - 8 - off, cx + dx, y1 - 22 - off], fill=AIR, width=3,
                          capstyle="round")
        self.hotspot(x1 + 26, y1 - 30, x2 - 26, y1 + 44, point or "")

    def chiller(self, x1, y1, x2, y2, running: bool, alarm: bool, blink: bool, load: float,
                t: float, point: Optional[str] = None, show_load: bool = True):
        """Water-cooled chiller: condenser barrel (top), evaporator barrel (bottom), compressor."""
        frame = (RED if blink else "#ffcdd2") if alarm else ("#e8f5e9" if running else "#f5f5f5")
        self.rect(x1, y1, x2, y2, fill=frame, outline=OUTLINE, width=3, point=point)
        bh = (y2 - y1) * 0.26
        self.rect(x1 + 20, y1 + 14, x2 - 20, y1 + 14 + bh, fill="#ffccbc", outline=OUTLINE, width=2,
                  point=point)
        self.text((x1 + x2) / 2, y1 + 14 + bh / 2, "CONDENSER", 9, True, "#bf360c", point=point)
        self.rect(x1 + 20, y2 - 14 - bh, x2 - 20, y2 - 14, fill="#bbdefb", outline=OUTLINE, width=2,
                  point=point)
        self.text((x1 + x2) / 2, y2 - 14 - bh / 2, "EVAPORATOR", 9, True, WATER_SUPPLY, point=point)
        cy = (y1 + y2) / 2
        cx = x1 + (x2 - x1) * 0.3
        r = bh * 0.55
        self.oval(cx, cy, r, fill=GREEN_LIGHT if running else STEEL, outline=OUTLINE, width=2,
                  point=point)
        a = t * 8 if running else 0
        self.line([cx - math.cos(a) * r * 0.8, cy - math.sin(a) * r * 0.8,
                   cx + math.cos(a) * r * 0.8, cy + math.sin(a) * r * 0.8], fill="#ffffff", width=3,
                  point=point)
        if show_load:
            self.text(cx, cy + r + 10, "COMPRESSOR", 7, True, STEEL_DARK, point=point)
        # load bar
        if not show_load:
            self.text(x1 + (x2 - x1) * 0.66, cy, "RUN" if running else "OFF", 9, True,
                      GREEN if running else GREY, point=point)
            self.hotspot(x1 - 4, y1 - 4, x2 + 4, y2 + 4, point or "")
            return
        bx = x1 + (x2 - x1) * 0.55
        self.text(bx, cy - 9, "LOAD", 8, True, STEEL_DARK, anchor="w", point=point)
        self.level_bar(bx, cy - 2, (x2 - x1) * 0.35, 12, load / 100, GREEN if running else GREY)
        self.text(bx + (x2 - x1) * 0.35 + 4, cy + 4, f"{load:.0f}%", 8, True, TEXT, anchor="w",
                  point=point)
        self.hotspot(x1 - 4, y1 - 4, x2 + 4, y2 + 4, point or "")

    def flow_switch(self, cx, cy, active: bool, point: Optional[str] = None, label: str = "FS"):
        """Paddle flow switch on a pipe: paddle bends and turns green with flow."""
        self.rect(cx - 14, cy - 34, cx + 14, cy - 14, fill=GREEN_LIGHT if active else "#eceff1",
                  outline=OUTLINE, width=2, point=point)
        self.text(cx, cy - 24, label, 7, True, TEXT, point=point)
        tip = (cx + 9, cy + 6) if active else (cx, cy + 9)
        self.line([cx, cy - 14, *tip], fill=OUTLINE, width=3, point=point)
        self.hotspot(cx - 18, cy - 38, cx + 18, cy + 12, point or "")

    def tag(self, x, y, txt: str, color: str = TEXT, size: int = 9, anchor: Any = "center"):
        """Small inline value label next to an element."""
        self.text(x, y, txt, size, True, color, anchor=anchor)

    def legend(self, x, y, items: Sequence[Tuple[str, str]], states: Dict[str, PointState],
               width: float = 190, step: float = 42, title: str = "POINTS"):
        """Column of value boxes - one per graphic point - clickable for linking."""
        self.text(x, y - 10, title, 9, True, STEEL_DARK, anchor="w")
        for k, (key, label) in enumerate(items):
            self.value_box(x, y + k * step, label, states[key], width, point=key)

    def speed_bars(self, x, y, level: int, levels: int = 3, labels: Sequence[str] = ("L", "M", "H")):
        for k in range(levels):
            on = k < level
            h = 10 + k * 7
            self.rect(x + k * 18, y - h, x + k * 18 + 12, y, fill=GREEN if on else "#eceff1",
                      outline=OUTLINE, width=1)
            self.text(x + k * 18 + 6, y + 9, labels[k] if k < len(labels) else "", 7, True, STEEL_DARK)



class GraphicTemplate:
    """Subclass this in a new module and set TEMPLATE = YourClass."""
    TEMPLATE_ID = "base"
    NAME = "Base"
    DESCRIPTION = ""
    WIDTH = 1000
    HEIGHT = 520
    POINTS: List[GraphicPoint] = []
    # Per-page options shown as spin boxes in the Graphics tab:
    #   {"chillers": ("Chillers", 1, 6, 2), ...}  -> name: (label, minimum, maximum, default)
    OPTIONS: Dict[str, Tuple[str, int, int, int]] = {}
    LEGACY_KEYS: Dict[str, str] = {}

    def __init__(self, options: Optional[Dict[str, Any]] = None):
        self.options: Dict[str, int] = {}
        for name, (_label, lo, hi, default) in self.OPTIONS.items():
            try:
                v = int((options or {}).get(name, default))
            except (TypeError, ValueError):
                v = default
            self.options[name] = max(lo, min(hi, v))
        self.configure()

    def configure(self):
        """Override to build self.POINTS / WIDTH / HEIGHT from self.options."""

    def point(self, key: str) -> GraphicPoint:
        for p in self.POINTS:
            if p.key == key:
                return p
        raise KeyError(key)

    def draw(self, d: Drawer, s: Dict[str, PointState], t: float):  # pragma: no cover
        raise NotImplementedError

    def demo_value(self, key: str, t: float) -> Tuple[Any, bool]:
        """Value used in demo mode -> (value, is_analog). Override for realistic demos."""
        p = self.point(key)
        seed = sum(map(ord, key)) % 7
        if p.kind == "analog":
            return 50 + 45 * math.sin(t / 4 + seed), True
        if p.alarm_when_active:
            return (1 if (t + seed * 9) % 60 < 8 else 0), False
        return (1 if (t % 40) < 34 else 0), False
