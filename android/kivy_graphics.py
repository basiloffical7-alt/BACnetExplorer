"""Kivy widget that replays the equipment drawings (recorded by graphics_core.OpRecorder)."""
from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, Mesh, Rectangle
from kivy.graphics.tesselator import TYPE_POLYGONS, WINDING_ODD, Tesselator
from kivy.uix.widget import Widget

from graphics_core import GraphicsModel, OpRecorder


def rgba(color: Any, alpha: float = 1.0) -> Optional[Tuple[float, float, float, float]]:
    if not color or not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
        return None
    return (int(color[1:3], 16) / 255, int(color[3:5], 16) / 255, int(color[5:7], 16) / 255, alpha)


class GraphicWidget(Widget):
    """Draws the current graphics page. Tap an element -> on_point(key)."""
    FPS = 8

    def __init__(self, model: GraphicsModel, on_point: Callable[[str], None], **kw):
        super().__init__(**kw)
        self.model = model
        self.on_point = on_point
        self.dark = False
        self.demo = False
        self.zoom: Optional[float] = None          # None = fit
        self.highlight: Optional[str] = None
        self.background = (1, 1, 1, 1)
        self.t0 = time.time()
        self._rec: Optional[OpRecorder] = None
        self._tex: Dict[tuple, Any] = {}
        self._ev = None
        self.bind(size=lambda *a: self.redraw(), pos=lambda *a: self.redraw())

    def start(self):
        if self._ev is None:
            self._ev = Clock.schedule_interval(lambda dt: self.redraw(), 1.0 / self.FPS)

    def stop(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None

    # ---- text textures (cached; CoreLabel rendering is the slow part)
    def _texture(self, text: str, px: int, bold: bool, color):
        key = (text, px, bold, color)
        tex = self._tex.get(key)
        if tex is None:
            lbl = CoreLabel(text=text, font_size=px, bold=bold, color=color)
            lbl.refresh()
            tex = lbl.texture
            if len(self._tex) > 800:
                self._tex.clear()
            self._tex[key] = tex
        return tex

    # ---- drawing
    def redraw(self):
        if self.width < 20 or self.height < 20:
            return
        t = time.time() - self.t0
        rec, _d = self.model.render(self.width, self.height, self.dark, self.demo, t, self.zoom,
                                    self.highlight)
        self._rec = rec
        x0, y0, H = self.x, self.y, self.height

        def P(x, y):
            return x0 + x, y0 + H - y

        cv = self.canvas
        cv.clear()
        with cv:
            Color(*self.background)
            Rectangle(pos=self.pos, size=self.size)
            for kind, c, k in rec.ops:
                try:
                    if kind == "text":
                        self._draw_text(c, k, P)
                    elif kind == "rect":
                        self._draw_rect(c, k, P)
                    elif kind == "oval":
                        self._draw_oval(c, k, P)
                    elif kind == "line":
                        self._draw_line(c, k, P)
                    elif kind == "poly":
                        self._draw_poly(c, k, P)
                except Exception:
                    continue

    @staticmethod
    def _w(k) -> float:
        try:
            return max(1.0, float(k.get("width", 1) or 1) * 0.55)
        except (TypeError, ValueError):
            return 1.0

    def _draw_rect(self, c, k, P):
        (ax, ay), (bx, by) = P(c[0], c[1]), P(c[2], c[3])
        x, y, w, h = min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay)
        f = rgba(k.get("fill"))
        if f:
            Color(*f)
            Rectangle(pos=(x, y), size=(w, h))
        o = rgba(k.get("outline"))
        if o and k.get("width", 1):
            Color(*o)
            if k.get("dash"):
                Line(rectangle=(x, y, w, h), width=1, dash_length=5, dash_offset=4)
            else:
                Line(rectangle=(x, y, w, h), width=self._w(k))

    def _draw_oval(self, c, k, P):
        (ax, ay), (bx, by) = P(c[0], c[1]), P(c[2], c[3])
        x, y, w, h = min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay)
        f = rgba(k.get("fill"))
        if f:
            Color(*f)
            Ellipse(pos=(x, y), size=(w, h))
        o = rgba(k.get("outline"))
        if o and k.get("width", 1):
            Color(*o)
            Line(ellipse=(x, y, w, h), width=self._w(k))

    def _draw_line(self, c, k, P):
        col = rgba(k.get("fill") or "#000000")
        if not col or len(c) < 4:
            return
        pts: List[float] = []
        for i in range(0, len(c) - 1, 2):
            pts += list(P(c[i], c[i + 1]))
        Color(*col)
        w = self._w(k)
        cap = "round" if k.get("capstyle") == "round" else "none"
        dash = k.get("dash")
        if dash:
            on, off = float(dash[0]), float(dash[1] if len(dash) > 1 else dash[0])
            phase = -float(k.get("dashoffset", 0) or 0) % (on + off)
            for i in range(0, len(pts) - 2, 2):
                ax, ay, bx, by = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
                L = math.hypot(bx - ax, by - ay) or 1.0
                s = -phase
                while s < L:
                    a, b = max(s, 0.0), min(s + on, L)
                    if b > a:
                        Line(points=[ax + (bx - ax) * a / L, ay + (by - ay) * a / L,
                                     ax + (bx - ax) * b / L, ay + (by - ay) * b / L], width=w)
                    s += on + off
            return
        Line(points=pts, width=w, cap=cap, joint="round")

    def _draw_poly(self, c, k, P):
        pts: List[float] = []
        for i in range(0, len(c) - 1, 2):
            pts += list(P(c[i], c[i + 1]))
        if len(pts) < 6:
            return
        f = rgba(k.get("fill"))
        if f:
            tess = Tesselator()
            tess.add_contour(pts)
            if tess.tesselate(WINDING_ODD, TYPE_POLYGONS):
                Color(*f)
                for vertices, indices in tess.meshes:
                    Mesh(vertices=vertices, indices=indices, mode="triangle_fan")
        o = rgba(k.get("outline"))
        if o and k.get("width", 1):
            Color(*o)
            Line(points=pts, width=self._w(k), close=True)

    def _draw_text(self, c, k, P):
        text = str(k.get("text", ""))
        if not text:
            return
        font = k.get("font") or ("", 10, "normal")
        size = float(font[1]) if len(font) > 1 else 10
        px = int(-size if size < 0 else size * 1.33)
        if px < 5:
            return
        col = rgba(k.get("fill") or "#000000") or (0, 0, 0, 1)
        tex = self._texture(text, px, len(font) > 2 and font[2] == "bold", col)
        x, y = P(c[0], c[1])
        tw, th = tex.size
        anchor = k.get("anchor", "center")
        if anchor == "w":
            pos = (x, y - th / 2)
        elif anchor == "e":
            pos = (x - tw, y - th / 2)
        else:
            pos = (x - tw / 2, y - th / 2)
        Color(1, 1, 1, 1)
        Rectangle(texture=tex, pos=pos, size=tex.size)

    # ---- taps
    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos) and self._rec is not None and not touch.is_mouse_scrolling \
                and abs(touch.x - touch.ox) < 12 and abs(touch.y - touch.oy) < 12:
            key = self._rec.point_at(touch.x - self.x, self.height - (touch.y - self.y), slop=14)
            if key:
                self.highlight = key
                self.on_point(key)
                return True
        return super().on_touch_up(touch)
