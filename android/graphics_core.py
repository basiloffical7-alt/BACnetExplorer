"""
Equipment graphics for the Android app - pages, links, live states and a drawing recorder.

The desktop templates (graphics/*.py) draw through graphics.base.Drawer onto a Tk-like canvas.
`OpRecorder` is a stand-in for that canvas: it records every create_* call so the Kivy widget can
replay the drawing (and so taps can be hit-tested against the clickable elements).
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from bacnet import codec as X
from bacnet import constants as C
from bacnet.client import BACnetException
from bacnet.codec import ObjectId
from graphics import load_templates
from graphics.base import Drawer, GraphicTemplate, PointState

from core import UNIT_SHORT, Core

LinkKey = Tuple[int, int, int]


class OpRecorder:
    """Records Tk canvas drawing calls: ops = [(kind, coords, options), ...]."""

    def __init__(self, width: float, height: float):
        self.w, self.h = int(width), int(height)
        self.ops: List[Tuple[str, List[float], Dict[str, Any]]] = []

    def winfo_width(self):
        return self.w

    def winfo_height(self):
        return self.h

    def _add(self, kind, coords, kw):
        self.ops.append((kind, [float(c) for c in coords], kw))
        return len(self.ops)

    def create_rectangle(self, *c, **k):
        return self._add("rect", c, k)

    def create_oval(self, *c, **k):
        return self._add("oval", c, k)

    def create_line(self, *c, **k):
        return self._add("line", c, k)

    def create_polygon(self, *c, **k):
        return self._add("poly", c, k)

    def create_text(self, *c, **k):
        return self._add("text", c, k)

    def point_at(self, x: float, y: float, slop: float = 10) -> Optional[str]:
        """Topmost clickable element ('pt:<key>' tag) under (x, y) in canvas coordinates."""
        for kind, c, k in reversed(self.ops):
            tags = k.get("tags") or ()
            key = next((t[3:] for t in tags if t.startswith("pt:") and len(t) > 3), None)
            if not key or kind not in ("rect", "oval", "poly"):
                continue
            xs, ys = c[0::2], c[1::2]
            if min(xs) - slop <= x <= max(xs) + slop and min(ys) - slop <= y <= max(ys) + slop:
                return key
        return None


def interpret(value: Any, oid: ObjectId, link: Dict[str, Any], units: Any,
              state_text: Optional[List[str]] = None) -> PointState:
    st = PointState(linked=True, value=value, online=value is not None)
    if value is None:
        st.text = "waiting…"
        return st
    invert = bool(link.get("invert", False))
    threshold = float(link.get("threshold", 1.0))
    if oid.type in C.BINARY_TYPES or isinstance(value, (bool, X.Enumerated)):
        st.active = int(value) == 1
        st.text = "ACTIVE" if int(value) == 1 else "INACTIVE"
    elif oid.type in C.MULTISTATE_TYPES:
        n = int(value)
        st.active = n > 1
        st.text = state_text[n - 1] if state_text and 0 < n <= len(state_text) else f"state {n}"
    elif isinstance(value, (int, float)):
        v = float(value)
        st.is_analog = True
        st.percent = max(0.0, min(100.0, v))
        st.active = v > threshold
        u = UNIT_SHORT.get(int(units)) if units is not None else None
        fmt = f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}"
        st.text = f"{fmt} {u}" if u else fmt
    else:
        st.text = X.format_plain(value)[:20]
    if invert:
        st.active = not st.active
        if st.is_analog:
            st.percent = 100.0 - st.percent
    if not st.is_analog:
        st.percent = 100.0 if st.active else 0.0
    return st


class GraphicsModel:
    def __init__(self, core: Core):
        self.core = core
        self.templates, self.errors = load_templates()
        self.ids = sorted(self.templates, key=lambda i: self.templates[i].NAME)
        pages = core.settings.get("graphic_pages")
        if not isinstance(pages, list) or not pages:
            pages = [self.new_page_dict("AHU-01", "ahu_sr" if "ahu_sr" in self.templates else self.ids[0])]
            core.settings["graphic_pages"] = pages
        self.pages: List[Dict[str, Any]] = pages
        self.instances: Dict[str, GraphicTemplate] = {}
        self.subs: Dict[LinkKey, int] = {}
        self.pending: Set[LinkKey] = set()
        self.current = 0
        cur = core.settings.get("graphic_page_current")
        for i, p in enumerate(self.pages):
            if p.get("id") == cur:
                self.current = i
        self._migrate()

    # ------------------------------------------------------------------ pages
    @staticmethod
    def new_page_dict(name: str, template: str) -> Dict[str, Any]:
        return {"id": uuid.uuid4().hex[:8], "name": name, "template": template, "links": {}}

    def page(self) -> Optional[Dict[str, Any]]:
        return self.pages[self.current] if 0 <= self.current < len(self.pages) else None

    def template(self, page: Optional[Dict[str, Any]] = None) -> Optional[GraphicTemplate]:
        page = page or self.page()
        if not page:
            return None
        if page["id"] not in self.instances:
            cls = self.templates.get(page["template"])
            if cls is None:
                return None
            self.instances[page["id"]] = cls(page.get("options"))
        return self.instances[page["id"]]

    def select(self, index: int):
        self.current = max(0, min(index, len(self.pages) - 1))
        p = self.page()
        self.core.settings["graphic_page_current"] = p["id"] if p else None
        self.core.save()

    def add_page(self, name: str, template: str):
        p = self.new_page_dict(name, template)
        self.pages.append(p)
        self.select(len(self.pages) - 1)
        self.sync()

    def delete_page(self):
        p = self.page()
        if p and len(self.pages) > 1:
            self.pages.remove(p)
            self.instances.pop(p["id"], None)
            self.select(0)
            self.cleanup()

    def rename(self, name: str):
        p = self.page()
        if p and name.strip():
            p["name"] = name.strip()
            self.core.save()

    def set_equipment(self, template: str) -> int:
        """Change the current page's equipment; returns the number of links dropped."""
        p = self.page()
        if not p or template not in self.templates:
            return 0
        inst = self.templates[template](p.get("options"))
        valid = {q.key for q in inst.POINTS}
        lost = [k for k in p["links"] if k not in valid]
        for k in lost:
            del p["links"][k]
        p["template"] = template
        self.instances.pop(p["id"], None)
        self.core.save()
        self.cleanup()
        return len(lost)

    def set_options(self, opts: Dict[str, int]) -> int:
        p = self.page()
        cls = self.templates.get(p["template"]) if p else None
        if not p or cls is None:
            return 0
        inst = cls({**(p.get("options") or {}), **opts})
        valid = {q.key for q in inst.POINTS}
        lost = [k for k in p["links"] if k not in valid]
        for k in lost:
            del p["links"][k]
        p["options"] = dict(inst.options)
        self.instances[p["id"]] = inst
        self.core.save()
        self.cleanup()
        return len(lost)

    def _migrate(self):
        for page in self.pages:
            cls = self.templates.get(page.get("template", ""))
            if cls is None:
                continue
            try:
                valid = {p.key for p in cls(page.get("options")).POINTS}
            except Exception:
                continue
            legacy = getattr(cls, "LEGACY_KEYS", {})
            links = page.setdefault("links", {})
            for old in list(links):
                if old in valid:
                    continue
                link = links.pop(old)
                new = legacy.get(old)
                if new and new in valid and new not in links:
                    links[new] = link

    # ------------------------------------------------------------------ links
    @staticmethod
    def link_key(link: Dict[str, Any]) -> LinkKey:
        return int(link["device"]), int(link["object"][0]), int(link["object"][1])

    def set_link(self, key: str, dev: int, oid: ObjectId, name: str):
        p = self.page()
        if not p:
            return
        old = p["links"].get(key, {})
        p["links"][key] = {"device": dev, "object": [oid.type, oid.instance], "name": name,
                           "invert": old.get("invert", False), "threshold": old.get("threshold", 1.0)}
        self.core.save()
        self.cleanup()
        self.sync()

    def unlink(self, key: str):
        p = self.page()
        if p and key in p["links"]:
            del p["links"][key]
            self.core.save()
            self.cleanup()

    @staticmethod
    def _tokens(name: str) -> List[str]:
        name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
        return [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w]

    def suggest_links(self, names: Dict[ObjectId, str]) -> List[Tuple[str, ObjectId, str]]:
        page, tpl = self.page(), self.template()
        if not page or not tpl:
            return []
        objs = [(o, n, self._tokens(n)) for o, n in names.items() if n and o.type != C.OBJ_DEVICE]
        cands = []
        for gp in tpl.POINTS:
            if gp.key in page["links"]:
                continue
            for pi, pat in enumerate(gp.match or [gp.label]):
                words = self._tokens(pat)
                for o, n, toks in objs:
                    if all(w in toks for w in words):
                        score = pi * 10 + len(toks) - len(words)
                        binary_obj = o.type in C.BINARY_TYPES or o.type in C.MULTISTATE_TYPES
                        if (gp.kind == "binary") != binary_obj and gp.kind != "any":
                            score += 25
                        cands.append((score, gp.key, o, n))
        cands.sort(key=lambda c: c[0])
        taken_p: Set[str] = set()
        taken_o: Set[ObjectId] = set()
        out = []
        for _s, key, o, n in cands:
            if key in taken_p or o in taken_o:
                continue
            taken_p.add(key)
            taken_o.add(o)
            out.append((key, o, n))
        return out

    def apply_links(self, dev: int, sugg: List[Tuple[str, ObjectId, str]]):
        p = self.page()
        if not p:
            return
        for key, o, n in sugg:
            old = p["links"].get(key, {})
            p["links"][key] = {"device": dev, "object": [o.type, o.instance], "name": n,
                               "invert": old.get("invert", False), "threshold": old.get("threshold", 1.0)}
        self.core.save()
        self.cleanup()
        self.sync()

    # ------------------------------------------------------------------ live values
    def all_links(self):
        for page in self.pages:
            for key, link in page["links"].items():
                yield page, key, link

    def sync(self):
        """Make sure every linked point has a (polled) subscription."""
        core, cl = self.core, self.core.client
        if cl is None or not cl.running:
            self.subs.clear()
            self.pending.clear()
            return
        for _p, _k, link in self.all_links():
            k = self.link_key(link)
            sid = self.subs.get(k)
            if k in self.pending or (sid is not None and sid in cl.subscriptions):
                continue
            dev = cl.devices.get(k[0])
            if dev is None:
                continue
            self.pending.add(k)
            oid = ObjectId(k[1], k[2])

            def work(dev=dev, oid=oid):
                if (dev.instance, oid) not in core.units_cache and oid.type in C.ANALOG_TYPES:
                    try:
                        core.units_cache[(dev.instance, oid)] = cl.read_property(dev.address, oid, C.PROP_UNITS)
                    except BACnetException:
                        core.units_cache[(dev.instance, oid)] = None
                if oid.type in C.MULTISTATE_TYPES:
                    core.state_text(dev, oid)
                sub = cl.add_subscription(dev, oid, False, 300, True, cl.refresh_interval,
                                          name=f"[Graphic] {oid.short}")
                sub.graph = False
                return sub

            def done(sub, k=k):
                self.subs[k] = sub.sub_id
                self.pending.discard(k)

            def err(e, k=k):
                self.pending.discard(k)
            core._bg(work, done, err)

    def cleanup(self):
        used = {self.link_key(l) for _p, _k, l in self.all_links()}
        cl = self.core.client
        for k in list(self.subs):
            if k not in used:
                sid = self.subs.pop(k)
                if cl and sid in cl.subscriptions:
                    self.core.pool.submit(cl.remove_subscription, sid)

    def raw_value(self, link: Dict[str, Any]) -> Any:
        cl = self.core.client
        sub = cl.subscriptions.get(self.subs.get(self.link_key(link), -1)) if cl else None
        return sub.value if sub is not None and sub.last_update else None

    def states(self, demo: bool, t: float) -> Dict[str, PointState]:
        page, tpl = self.page(), self.template()
        out: Dict[str, PointState] = {}
        if not page or not tpl:
            return out
        for gp in tpl.POINTS:
            link = page["links"].get(gp.key)
            if demo:
                val, analog = tpl.demo_value(gp.key, t)
                if analog:
                    st = PointState(value=val, is_analog=True, percent=max(0.0, min(100.0, val)),
                                    active=val > 1.0, text=f"{val:.1f}")
                else:
                    st = PointState(value=val, active=bool(val), percent=100.0 if val else 0.0,
                                    text="ACTIVE" if val else "INACTIVE")
                st.override = st.online = True
                st.linked = link is not None
                out[gp.key] = st
                continue
            if not link:
                out[gp.key] = PointState()
                continue
            k = self.link_key(link)
            oid = ObjectId(k[1], k[2])
            out[gp.key] = interpret(self.raw_value(link), oid, link,
                                    self.core.units_cache.get((k[0], oid)),
                                    self.core.units_cache.get((k[0], oid, "st")))
        return out

    def render(self, width: float, height: float, dark: bool, demo: bool, t: float,
               zoom: Optional[float] = None, highlight: Optional[str] = None) -> Tuple[OpRecorder, Drawer]:
        """Run the template's draw() into a recorder (Tk coordinates, y down)."""
        rec = OpRecorder(width, height)
        tpl = self.template()
        page = self.page()
        if not tpl or not page:
            return rec, Drawer(rec, 100, 100)
        d = Drawer(rec, tpl.WIDTH, tpl.HEIGHT, highlight=highlight, dark=dark, scale=zoom)
        tpl.draw(d, self.states(demo, t), t)
        return rec, d

    def point_rows(self, demo: bool = False) -> List[Dict[str, Any]]:
        page, tpl = self.page(), self.template()
        if not page or not tpl:
            return []
        st = self.states(demo, time.time())
        rows = []
        for gp in tpl.POINTS:
            link = page["links"].get(gp.key)
            s = st.get(gp.key, PointState())
            rows.append({"key": gp.key, "label": gp.label, "help": gp.help,
                         "linked": f"{link['device']} {ObjectId(*link['object']).short} {link.get('name', '')}"
                         if link else "not linked",
                         "value": s.text if (s.linked or s.override) else "",
                         "is_linked": link is not None})
        return rows
