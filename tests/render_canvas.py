"""A minimal Tk-Canvas look-alike that records drawing calls and renders them with Pillow."""
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

class RecCanvas:
    def __init__(self, *a, w=1200, h=620, **k):
        self.w, self.h, self.ops, self.tags = w, h, [], {}
    def __getattr__(self, n): return lambda *a, **k: None
    def winfo_width(self): return self.w
    def winfo_height(self): return self.h
    def winfo_ismapped(self): return True
    def delete(self, *a): self.ops.clear(); self.tags.clear()
    def _add(self, kind, coords, kw):
        self.ops.append((kind, [float(c) for c in coords], kw)); i = len(self.ops)
        self.tags[i] = kw.get("tags", ()); return i
    def create_rectangle(self, *c, **k): return self._add("rect", c, k)
    def create_oval(self, *c, **k): return self._add("oval", c, k)
    def create_line(self, *c, **k): return self._add("line", c, k)
    def create_polygon(self, *c, **k): return self._add("poly", c, k)
    def create_text(self, *c, **k): return self._add("text", c, k)
    def gettags(self, i): return self.tags.get(i, ())
    def find_overlapping(self, x1, y1, x2, y2):
        out = []
        for i, (kind, c, k) in enumerate(self.ops, 1):
            if kind in ("rect", "oval") and c[0] <= x2 and c[2] >= x1 and c[1] <= y2 and c[3] >= y1:
                out.append(i)
        return out
    def render(self, path):
        im = Image.new("RGB", (self.w, self.h), "white"); d = ImageDraw.Draw(im)
        for kind, c, k in self.ops:
            fill = k.get("fill") or None; out = k.get("outline", "black") or None
            w = max(1, int(round(k.get("width", 1) or 1)))
            if kind == "rect":
                x1, y1, x2, y2 = c; d.rectangle([min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2)], fill=fill, outline=out, width=w if out else 0)
            elif kind == "oval":
                d.ellipse(c, fill=fill, outline=out, width=w if out else 0)
            elif kind == "poly":
                d.polygon(list(zip(c[::2], c[1::2])), fill=fill, outline=out)
            elif kind == "line":
                pts = list(zip(c[::2], c[1::2]))
                if k.get("dash"):  # approximate dashes
                    import math
                    on, off = k["dash"][:2]; phase = -k.get("dashoffset", 0) % (on + off)
                    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                        L = math.hypot(bx-ax, by-ay) or 1; t = -phase
                        while t < L:
                            s0, s1 = max(t, 0), min(t+on, L)
                            if s1 > s0: d.line([(ax+(bx-ax)*s0/L, ay+(by-ay)*s0/L), (ax+(bx-ax)*s1/L, ay+(by-ay)*s1/L)], fill=fill, width=w)
                            t += on + off
                else:
                    d.line(pts, fill=fill, width=w, joint="curve")
            elif kind == "text":
                fam, size, wt = k.get("font", ("x", 10, "normal"))
                f = ImageFont.truetype(FONT_B if wt == "bold" else FONT, int(-size if size < 0 else size * 1.33))
                anchor = {"center": "mm", "w": "lm", "e": "rm"}.get(k.get("anchor", "center"), "mm")
                d.text((c[0], c[1]), k.get("text", ""), fill=k.get("fill") or "black", font=f, anchor=anchor)
        im.save(path)
