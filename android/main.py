"""
Basil BACnet - Android version of Basil BACnet Explorer (Kivy).

Bottom tabs: Devices · Watch · Graphics · Report · Settings
  Devices  -> tap a device -> its points (live values) -> tap a point -> details + write
  Watch    -> your favourite points, live every second, value flashes 3 s on change,
              tap the value to write, tap the name to open the point
  Graphics -> the desktop equipment graphics (AHU, FCU, chiller plant ...), tap an element
  Report   -> how many devices / points are online, export to Excel and share
"""
from __future__ import annotations

import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.dirname(HERE)):          # desktop: shared code lives one folder up
    if p not in sys.path:
        sys.path.append(p)

from typing import Any, Callable, Dict, List, Optional  # noqa: E402

from kivy.app import App  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.graphics import Color, Rectangle  # noqa: E402
from kivy.metrics import dp, sp  # noqa: E402
from kivy.properties import ListProperty  # noqa: E402
from kivy.uix.behaviors import ButtonBehavior  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.button import Button  # noqa: E402
from kivy.uix.checkbox import CheckBox  # noqa: E402
from kivy.uix.gridlayout import GridLayout  # noqa: E402
from kivy.uix.image import Image  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.popup import Popup  # noqa: E402
from kivy.uix.recycleboxlayout import RecycleBoxLayout  # noqa: E402
from kivy.uix.recycleview import RecycleView  # noqa: E402
from kivy.uix.recycleview.views import RecycleDataViewBehavior  # noqa: E402
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager  # noqa: E402
from kivy.uix.scrollview import ScrollView  # noqa: E402
from kivy.uix.spinner import Spinner  # noqa: E402
from kivy.uix.textinput import TextInput  # noqa: E402
from kivy.uix.togglebutton import ToggleButton  # noqa: E402

import authcore  # noqa: E402
import platform_android as PA  # noqa: E402
from bacnet import codec as X  # noqa: E402
from bacnet import constants as C  # noqa: E402
from bacnet.codec import ObjectId  # noqa: E402
from core import APP_NAME, APP_VERSION, TYPE_FILTERS, Core, PointInfo, WatchItem, parse_value, value_text  # noqa: E402
from graphics_core import GraphicsModel  # noqa: E402
from kivy_graphics import GraphicWidget  # noqa: E402

# ---------------------------------------------------------------------------- theme
THEMES = {
    "light": {"bg": (0.95, 0.96, 0.97, 1), "card": (1, 1, 1, 1), "card2": (0.97, 0.98, 0.98, 1),
              "fg": (0.12, 0.16, 0.19, 1), "muted": (0.42, 0.47, 0.50, 1),
              "accent": (0.30, 0.69, 0.20, 1), "accent_fg": (1, 1, 1, 1),
              "button": (0.89, 0.92, 0.94, 1), "button_fg": (0.12, 0.16, 0.19, 1),
              "danger": (0.90, 0.22, 0.21, 1), "addr": (0.78, 0.16, 0.16, 1),
              "bar": (1, 1, 1, 1), "flash": (1.0, 0.84, 0.0, 1), "flash2": (1.0, 0.96, 0.62, 1),
              "input": (1, 1, 1, 1), "pv": (0.05, 0.28, 0.63, 1), "good": (0.18, 0.49, 0.20, 1),
              "warn": (0.94, 0.42, 0.0, 1), "graphic_bg": (1, 1, 1, 1)},
    "dark": {"bg": (0.12, 0.14, 0.15, 1), "card": (0.15, 0.17, 0.19, 1), "card2": (0.17, 0.19, 0.21, 1),
             "fg": (0.89, 0.91, 0.92, 1), "muted": (0.60, 0.65, 0.69, 1),
             "accent": (0.36, 0.79, 0.24, 1), "accent_fg": (0.05, 0.08, 0.05, 1),
             "button": (0.19, 0.22, 0.24, 1), "button_fg": (0.89, 0.91, 0.92, 1),
             "danger": (0.94, 0.33, 0.31, 1), "addr": (1.0, 0.42, 0.42, 1),
             "bar": (0.09, 0.10, 0.11, 1), "flash": (0.79, 0.64, 0.0, 1), "flash2": (0.30, 0.25, 0.0, 1),
             "input": (0.17, 0.19, 0.21, 1), "pv": (0.56, 0.79, 0.98, 1), "good": (0.65, 0.84, 0.65, 1),
             "warn": (1.0, 0.72, 0.30, 1), "graphic_bg": (0.118, 0.133, 0.153, 1)},
}
T: Dict[str, Any] = dict(THEMES["light"])


def hexc(c) -> str:
    return "%02x%02x%02x" % (int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))


def lbl(text="", size=15, color=None, bold=False, halign="left", **kw) -> Label:
    w = Label(text=text, font_size=sp(size), color=color or T["fg"], bold=bold, halign=halign,
              valign="middle", markup=True, **kw)
    w.bind(size=lambda inst, s: setattr(inst, "text_size", (s[0], None)))
    return w


def btn(text, on_press: Optional[Callable] = None, kind="normal", size=15, **kw) -> Button:
    bg = {"accent": T["accent"], "danger": T["danger"]}.get(kind, T["button"])
    fg = T["accent_fg"] if kind == "accent" else ((1, 1, 1, 1) if kind == "danger" else T["button_fg"])
    b = Button(text=text, font_size=sp(size), background_normal="", background_down="",
               background_color=bg, color=fg, **kw)
    if on_press:
        b.bind(on_release=lambda *_: on_press())
    return b


def inp(text="", hint="", password=False, number=False, **kw) -> TextInput:
    return TextInput(text=text, hint_text=hint, password=password, multiline=False,
                     font_size=sp(16), padding=(dp(10), dp(10)),
                     input_filter="float" if number else None, input_type="number" if number else "text",
                     background_normal="", background_active="", background_color=T["input"],
                     foreground_color=T["fg"], cursor_color=T["fg"], hint_text_color=T["muted"],
                     write_tab=False, **kw)


def spinner(values, text, on_change: Optional[Callable[[str], None]] = None, **kw) -> Spinner:
    s = Spinner(text=text, values=values, font_size=sp(14), background_normal="",
                background_color=T["button"], color=T["button_fg"], **kw)
    if on_change:
        s.bind(text=lambda inst, v: on_change(v))
    return s


class Flash:
    """Remembers the last text of each value and reports it as 'flashing' for 3 s after it changes
    (the first value seen never flashes)."""
    SECONDS = 3.0

    def __init__(self):
        self.last: Dict[Any, str] = {}
        self.until: Dict[Any, float] = {}

    def update(self, key, text: str) -> bool:
        old = self.last.get(key)
        self.last[key] = text
        if old is not None and text not in ("", "…") and old != text:
            self.until[key] = time.time() + self.SECONDS
        return self.on(key)

    def on(self, key) -> bool:
        return time.time() < self.until.get(key, 0.0)

    def any(self) -> bool:
        now = time.time()
        return any(t > now for t in self.until.values())


def blink() -> bool:
    return int(time.time() * 4) % 2 == 0


def flash_row(row: Dict[str, Any], on: bool) -> Dict[str, Any]:
    """Highlight a list row's value (yellow, blinking) while it is flashing."""
    if on:
        b = blink()
        row["bg"] = T["flash"] if b else T["flash2"]
        if b:
            row["value_color"] = (0, 0, 0, 1)
    return row


class FlashTicker:
    """Redraws a screen 4x a second while something flashes (and once more when it stops)."""

    def __init__(self, flash: Flash, redraw: Callable[[], None]):
        self.flash, self.redraw, self.ev, self.was = flash, redraw, None, False

    def start(self):
        if self.ev is None:
            self.ev = Clock.schedule_interval(self._tick, 0.25)

    def stop(self):
        if self.ev is not None:
            self.ev.cancel()
            self.ev = None

    def _tick(self, dt):
        on = self.flash.any()
        if on or self.was:
            self.redraw()
        self.was = on


class Card(BoxLayout):
    """BoxLayout with a coloured background."""
    bg = ListProperty([1, 1, 1, 1])

    def __init__(self, bg=None, **kw):
        super().__init__(**kw)
        self.bg = list(bg or T["card"])
        with self.canvas.before:
            self._c = Color(*self.bg)
            self._r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd, bg=lambda *a: setattr(self._c, "rgba", self.bg))

    def _upd(self, *a):
        self._r.pos, self._r.size = self.pos, self.size


def toast(text: str, seconds: float = 2.5):
    app = App.get_running_app()
    if app and app.status_label is not None:
        app.status_label.text = text
        Clock.schedule_once(lambda dt: app.update_status(), seconds)


def message(title: str, text: str):
    box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
    box.add_widget(lbl(text, 15))
    pop = Popup(title=title, content=box, size_hint=(0.9, None), height=dp(260))
    box.add_widget(btn("OK", pop.dismiss, "accent", size_hint_y=None, height=dp(48)))
    pop.open()


# ---------------------------------------------------------------------------- list rows
class Row(RecycleDataViewBehavior, ButtonBehavior, Card):
    """A list row: title / subtitle on the left, value on the right, optional action at the end.
    data keys: title, sub, value, action, bg, value_color, on_tap(zone, data)"""

    def __init__(self, **kw):
        super().__init__(orientation="horizontal", padding=(dp(12), dp(4)), spacing=dp(6), **kw)
        self.data: Dict[str, Any] = {}
        self.t = lbl("", 16, shorten=True, shorten_from="right")
        self.v = lbl("", 16, bold=True, halign="right", size_hint_x=0.42)
        self.a = lbl("", 18, bold=True, halign="center", size_hint_x=None, width=dp(44))
        self.add_widget(self.t)
        self.add_widget(self.v)
        self.add_widget(self.a)

    def refresh_view_attrs(self, rv, index, data):
        self.data = data
        sub = data.get("sub", "")
        subc = hexc(data.get("sub_color", T["muted"]))
        self.t.text = f"[b]{data.get('title', '')}[/b]" + (
            f"\n[size={int(sp(12))}][color={subc}]{sub}[/color][/size]" if sub else "")
        self.t.color = T["fg"]
        self.v.text = str(data.get("value", ""))
        self.v.color = data.get("value_color", T["fg"])
        self.v.size_hint_x = 0.42 if data.get("value", "") != "" else 0.001
        self.a.text = data.get("action", "")
        self.a.color = T["muted"]
        self.a.width = dp(44) if data.get("action") else 0
        self.bg = list(data.get("bg", T["card"] if index % 2 == 0 else T["card2"]))

    def on_release(self):
        cb = self.data.get("on_tap")
        if not cb:
            return
        x = self.last_touch.x if self.last_touch is not None else self.center_x
        if self.data.get("action") and x > self.right - dp(50):
            zone = "action"
        elif self.data.get("value", "") != "" and x > self.x + self.width * 0.55:
            zone = "value"
        else:
            zone = "title"
        cb(zone, self.data)


def make_list() -> RecycleView:
    rv = RecycleView(do_scroll_x=False, bar_width=dp(4), scroll_type=["bars", "content"])
    lay = RecycleBoxLayout(default_size=(None, dp(62)), default_size_hint=(1, None), size_hint_y=None,
                           orientation="vertical", spacing=dp(1))
    lay.bind(minimum_height=lay.setter("height"))
    rv.add_widget(lay)
    rv.viewclass = Row
    return rv


# ---------------------------------------------------------------------------- write popup
def write_popup(app: "BasilApp", dev, oid: ObjectId, name: str, current: Any, units: Any = None,
                state_text: Optional[List[str]] = None, after: Optional[Callable[[Any], None]] = None):
    box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
    pop = Popup(title=f"Write  {oid.short}  {name}"[:60], content=box, size_hint=(0.94, None),
                height=dp(470), separator_color=T["accent"])
    box.add_widget(lbl(f"Now: [b]{value_text(current, oid, units, state_text)}[/b]", 17))
    commandable = oid.type in C.COMMANDABLE_TYPES
    prio = spinner([f"{k} - {C.PRIORITY_NAMES[k - 1]}" for k in range(1, 17)],
                   f"{app.core.priority} - {C.PRIORITY_NAMES[app.core.priority - 1]}",
                   size_hint_y=None, height=dp(44))
    status = lbl("", 14, color=T["muted"], size_hint_y=None, height=dp(30))

    def send(value):
        p = int(prio.text.split(" ")[0]) if commandable else None
        status.text = "Writing…"

        def ok(v):
            pop.dismiss()
            toast(f"{oid.short} = {value_text(v, oid, units, state_text)}")
            if after:
                after(v)

        def bad(e):
            status.text = f"[color={hexc(T['danger'])}]Failed: {e}[/color]"
        app.core.write(dev, oid, value, p, ok, bad)

    grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None)
    grid.bind(minimum_height=grid.setter("height"))
    if oid.type in C.BINARY_TYPES:
        for text, v in (("ACTIVE / ON", 1), ("INACTIVE / OFF", 0)):
            grid.add_widget(btn(text, lambda v=v: send(X.Enumerated(v)), "accent" if v else "normal",
                                size=17, size_hint_y=None, height=dp(64)))
    elif oid.type in C.MULTISTATE_TYPES:
        names = state_text or [f"State {k}" for k in range(1, 5)]
        for k, nm in enumerate(names, start=1):
            grid.add_widget(btn(f"{k} - {nm}", lambda k=k: send(X.Unsigned(k)), size=15,
                                size_hint_y=None, height=dp(54)))
    else:
        cur = ""
        if isinstance(current, float):
            cur = f"{current:.2f}".rstrip("0").rstrip(".")
        elif current is not None and not isinstance(current, X.Null):
            cur = X.format_plain(current)
        field = inp(cur, "New value", number=oid.type in C.ANALOG_TYPES, size_hint_y=None, height=dp(52))
        step = 1.0

        def nudge(d):
            try:
                field.text = f"{float(field.text or 0) + d:.2f}".rstrip("0").rstrip(".")
            except ValueError:
                pass
        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        row.add_widget(btn("-", lambda: nudge(-step), size=22, size_hint_x=None, width=dp(56)))
        row.add_widget(field)
        row.add_widget(btn("+", lambda: nudge(step), size=22, size_hint_x=None, width=dp(56)))
        box.add_widget(row)

        def write_text():
            try:
                send(parse_value(oid, field.text, current))
            except ValueError as e:
                status.text = f"[color={hexc(T['danger'])}]{e}[/color]"
        grid.add_widget(btn("WRITE", write_text, "accent", size=17, size_hint_y=None, height=dp(60)))
        field.bind(on_text_validate=lambda *_: write_text())
    if commandable:
        grid.add_widget(btn("RELEASE (NULL)", lambda: send(X.NULL), size=15, size_hint_y=None, height=dp(54)))
    sc = ScrollView(do_scroll_x=False)
    sc.add_widget(grid)
    box.add_widget(sc)
    if commandable:
        box.add_widget(lbl("Priority", 13, color=T["muted"], size_hint_y=None, height=dp(20)))
        box.add_widget(prio)
    box.add_widget(status)
    box.add_widget(btn("Cancel", pop.dismiss, size_hint_y=None, height=dp(48)))
    pop.open()
    return pop


# ---------------------------------------------------------------------------- screens
class BaseScreen(Screen):
    title = ""

    def __init__(self, app: "BasilApp", **kw):
        super().__init__(**kw)
        self.app = app
        self.root_box = BoxLayout(orientation="vertical", spacing=dp(6), padding=(dp(8), dp(6)))
        with self.canvas.before:
            Color(*T["bg"])
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *a: setattr(self._bg, "pos", self.pos),
                  size=lambda *a: setattr(self._bg, "size", self.size))
        self.add_widget(self.root_box)

    def header(self, title: str, back: bool = True) -> BoxLayout:
        bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        if back:
            bar.add_widget(btn("<", self.app.go_back, size=22, size_hint_x=None, width=dp(52)))
        self.title_lbl = lbl(f"[b]{title}[/b]", 18, shorten=True)
        bar.add_widget(self.title_lbl)
        self.root_box.add_widget(bar)
        return bar

    def refresh(self):
        pass


class DevicesScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="devices", **kw)
        top = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(6))
        self.search = inp("", "Search devices…")
        self.search.bind(text=lambda *a: self.refresh())
        top.add_widget(self.search)
        top.add_widget(btn("Discover", app.discover, "accent", size_hint_x=None, width=dp(104)))
        top.add_widget(btn("+ IP", self.add_ip, size_hint_x=None, width=dp(64)))
        self.root_box.add_widget(top)
        self.count = lbl("", 13, color=T["muted"], size_hint_y=None, height=dp(22))
        self.root_box.add_widget(self.count)
        self.rv = make_list()
        self.root_box.add_widget(self.rv)

    def refresh(self):
        q = self.search.text.strip().lower()
        rows = []
        devs = self.app.core.devices()
        for d in devs:
            a = d.address
            addr = f"{a.ip}:{a.port}" if a.net is None else f"net {a.net}  mac {a.mac[0] if len(a.mac) == 1 else a.mac.hex()}  via {a.ip}"
            title = f"{d.name or 'Device'}  [{d.instance}]"
            if q and q not in title.lower() and q not in addr.lower():
                continue
            rows.append({"title": title, "sub": addr, "sub_color": T["addr"], "value": "", "action": ">",
                         "on_tap": lambda zone, data, d=d: self.app.open_device(d)})
        self.rv.data = rows
        self.count.text = f"{len(rows)} of {len(devs)} devices" if devs else \
            "No devices yet - press Discover (phone and controllers must be on the same network)"

    def add_ip(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        ip = inp("", "Device / router IP address")
        port = inp("47808", "UDP port", number=True)
        box.add_widget(ip)
        box.add_widget(port)
        msg = lbl("", 14, color=T["muted"], size_hint_y=None, height=dp(40))
        box.add_widget(msg)
        pop = Popup(title="Add device by IP", content=box, size_hint=(0.92, None), height=dp(330))

        def go():
            msg.text = "Contacting…"
            try:
                p = int(float(port.text or "47808"))
            except ValueError:
                p = 47808
            self.app.core.add_device_by_ip(ip.text.strip(), p, lambda d: (pop.dismiss(), self.app.open_device(d)),
                                           lambda e: setattr(msg, "text", f"Failed: {e}"))
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        row.add_widget(btn("Cancel", pop.dismiss))
        row.add_widget(btn("Add", go, "accent"))
        box.add_widget(row)
        pop.open()


class DeviceScreen(BaseScreen):
    """Points of one device with live values."""

    def __init__(self, app, **kw):
        super().__init__(app, name="device", **kw)
        self.dev = None
        self.items: List[PointInfo] = []
        bar = self.header("Device")
        bar.add_widget(btn("Reload", lambda: self.load(True), size_hint_x=None, width=dp(84)))
        flt = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.type_sp = spinner([n for n, _ in TYPE_FILTERS], "All", lambda v: self.show(),
                               size_hint_x=None, width=dp(120))
        self.search = inp("", "Search points…")
        self.search.bind(text=lambda *a: self.show())
        flt.add_widget(self.type_sp)
        flt.add_widget(self.search)
        self.root_box.add_widget(flt)
        self.info = lbl("", 13, color=T["muted"], size_hint_y=None, height=dp(22))
        self.root_box.add_widget(self.info)
        self.rv = make_list()
        self.root_box.add_widget(self.rv)
        self._ev = None
        self.flash = Flash()                       # value highlighted 3 s when it changes
        self.ticker = FlashTicker(self.flash, self.show)

    def open(self, dev):
        self.dev = dev
        self.title_lbl.text = f"[b]{dev.name or 'Device'} [{dev.instance}][/b]"
        self.items = []
        self.rv.data = []
        self.load(False)

    def load(self, reload: bool):
        dev = self.dev
        if dev is None:
            return
        self.info.text = "Loading…"

        def done(items):
            if self.dev is dev:
                self.items = items
                self.show()

        def bad(e):
            self.info.text = f"[color={hexc(T['danger'])}]Could not read the device: {e}[/color]"
        self.app.core.load_objects(dev, lambda m: setattr(self.info, "text", m), done, bad, reload)

    def show(self):
        if self.dev is None:
            return
        types = dict(TYPE_FILTERS).get(self.type_sp.text)
        q = self.search.text.strip().lower()
        core = self.app.core
        rows = []
        for p in self.items:
            if types is not None and p.oid.type not in types:
                continue
            if q and q not in p.name.lower() and q not in p.oid.short.lower():
                continue
            fault = isinstance(p.flags, X.BitString) and any(p.flags.bits[:2])
            txt = p.text()
            on = self.flash.update((self.dev.instance, p.oid), txt)
            rows.append(flash_row({"title": p.name or str(p.oid), "sub": p.oid.short, "value": txt,
                                   "value_color": T["danger"] if fault else T["pv"],
                                   "action": "*" if core.in_watch(self.dev.instance, p.oid) else "+",
                                   "on_tap": lambda zone, data, p=p: self.tap(zone, p)}, on))
        self.rv.data = rows
        self.info.text = f"{len(rows)} of {len(self.items)} points  ·  tap value = write  ·  + = add to Watch"

    def tap(self, zone: str, p: PointInfo):
        dev = self.dev
        if zone == "value":
            write_popup(self.app, dev, p.oid, p.name, p.value, p.units, p.state_text,
                        after=lambda v: self.show())
        elif zone == "action":
            if self.app.core.in_watch(dev.instance, p.oid):
                toast("Already on the Watch list")
            else:
                self.app.core.add_watch(dev, p.oid, p.name)
                toast(f"{p.name} added to Watch")
            self.show()
        else:
            self.app.open_point(dev, p.oid, p.name)

    def on_enter(self, *a):
        self._ev = Clock.schedule_interval(lambda dt: self.live(), max(2.0, self.app.core.refresh * 2))
        self.ticker.start()

    def on_leave(self, *a):
        self.ticker.stop()
        if self._ev:
            self._ev.cancel()
            self._ev = None

    def live(self):
        if self.dev is None or not self.items or not self.app.core.online:
            return
        shown = [p for p in self.items if (dict(TYPE_FILTERS).get(self.type_sp.text) is None
                                           or p.oid.type in dict(TYPE_FILTERS)[self.type_sp.text])]
        self.app.core.refresh_values(self.dev, shown[:60], lambda _r: self.show())


class PointScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="point", **kw)
        self.dev = None
        self.oid: Optional[ObjectId] = None
        self.name_ = ""
        self.props: Dict[int, Any] = {}
        self.header("Point")
        card = Card(orientation="vertical", size_hint_y=None, height=dp(120), padding=dp(12))
        self.pv_card = card
        self.pv_row = None
        self.flash = Flash()                       # present value highlighted 3 s when it changes
        self.ticker = FlashTicker(self.flash, self.paint_flash)
        self.big = lbl("", 34, color=T["pv"], bold=True, halign="center")
        self.state_lbl = lbl("", 14, color=T["muted"], halign="center", size_hint_y=None, height=dp(24))
        card.add_widget(self.big)
        card.add_widget(self.state_lbl)
        self.root_box.add_widget(card)
        acts = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
        acts.add_widget(btn("WRITE", self.write, "accent", size=17))
        self.watch_btn = btn("+ Watch", self.watch)
        acts.add_widget(self.watch_btn)
        acts.add_widget(btn("Refresh", self.load))
        self.root_box.add_widget(acts)
        self.grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(1))
        self.grid.bind(minimum_height=self.grid.setter("height"))
        sc = ScrollView(do_scroll_x=False)
        sc.add_widget(self.grid)
        self.root_box.add_widget(sc)
        self._ev = None

    def open(self, dev, oid: ObjectId, name: str):
        self.dev, self.oid, self.name_ = dev, oid, name
        self.title_lbl.text = f"[b]{oid.short}  {name}[/b]"
        self.big.text = "…"
        self.state_lbl.text = ""
        self.grid.clear_widgets()
        self.watch_btn.text = "On Watch" if self.app.core.in_watch(dev.instance, oid) else "+ Watch"
        self.load()

    def load(self):
        dev, oid = self.dev, self.oid
        if dev is None or oid is None:
            return

        def done(results):
            if self.oid != oid:
                return
            self.props = {r.prop: r.value for r in results if r.error is None}
            self.fill(results)

        def bad(e):
            self.state_lbl.text = f"[color={hexc(T['danger'])}]{e}[/color]"
        self.app.core.read_point(dev, oid, done, bad)

    def fill(self, results):
        oid = self.oid
        core = self.app.core
        units = self.props.get(C.PROP_UNITS)
        st = core.units_cache.get((self.dev.instance, oid, "st"))
        self.big.text = value_text(self.props.get(C.PROP_PRESENT_VALUE), oid, units, st)
        self.flash.update((self.dev.instance, oid), self.big.text)
        self.pv_row = None
        flags = self.props.get(C.PROP_STATUS_FLAGS)
        on = [C.STATUS_FLAGS_BITS[i] for i, b in enumerate(flags.bits[:4]) if b] \
            if isinstance(flags, X.BitString) else []
        self.state_lbl.text = ("[color=%s]%s[/color]" % (hexc(T["danger"]), ", ".join(on))) if on \
            else "[color=%s]normal[/color]" % hexc(T["good"])
        self.grid.clear_widgets()
        colors = {C.PROP_PRESENT_VALUE: T["pv"], 65: (0.85, 0.26, 0.08, 1), 69: (0.0, 0.51, 0.56, 1),
                  C.PROP_OBJECT_IDENTIFIER: (0.42, 0.11, 0.60, 1), 84: (0.68, 0.08, 0.34, 1)}
        order = {75: 0, 77: 1, 79: 2, 85: 3}
        for r in sorted(results, key=lambda r: (order.get(r.prop, 10), C.property_name(r.prop))):
            if r.error is not None:
                continue
            if r.prop == C.PROP_PRIORITY_ARRAY and isinstance(r.value, list):
                self.grid.add_widget(self._row("priority-array", "", T["fg"], bold=True))
                active = next((k for k, v in enumerate(r.value) if not isinstance(v, X.Null)), None)
                for k, v in enumerate(r.value):
                    txt = "" if isinstance(v, X.Null) else value_text(v, oid, units, st)
                    col = T["good"] if k == active else (T["pv"] if txt else T["muted"])
                    self.grid.add_widget(self._row(f"   {k + 1}  {C.PRIORITY_NAMES[k] if k < 16 else ''}",
                                                   txt + ("  < in control" if k == active else ""), col,
                                                   bold=bool(txt), prio=k + 1))
                continue
            if r.prop == C.PROP_PROPERTY_LIST:
                continue
            val = value_text(r.value, oid, units, st) if r.prop in (85, 104, 65, 69) else \
                X.format_value(r.value, oid.type, r.prop)
            col = colors.get(r.prop, T["fg"])
            if r.prop == C.PROP_RELIABILITY:
                col = T["good"] if not r.value else T["danger"]
            row = self._row(C.property_name(r.prop), val, col,
                            bold=r.prop in colors or r.prop == C.PROP_RELIABILITY)
            if r.prop == C.PROP_PRESENT_VALUE:
                self.pv_row = row
            self.grid.add_widget(row)
        self.paint_flash()

    def paint_flash(self):
        """Yellow, blinking present value for 3 s after it changes."""
        on = self.oid is not None and self.dev is not None and self.flash.on((self.dev.instance, self.oid))
        b = blink()
        self.pv_card.bg = list((T["flash"] if b else T["flash2"]) if on else T["card"])
        self.big.color = (0, 0, 0, 1) if on and b else T["pv"]
        if self.pv_row is not None:
            self.pv_row.bg = list((T["flash"] if b else T["flash2"]) if on else T["card"])

    def _row(self, name, value, color, bold=False, prio: Optional[int] = None):
        row = Card(size_hint_y=None, height=dp(44), padding=(dp(10), 0), spacing=dp(6))
        row.add_widget(lbl(name, 14, color=color if bold else T["muted"], bold=bold, size_hint_x=0.5,
                           shorten=True))
        row.add_widget(lbl(value[:200], 14, color=color, bold=bold, size_hint_x=0.5, shorten=True))
        if prio is not None and self.oid is not None and self.oid.type in C.COMMANDABLE_TYPES:
            row.bind(on_touch_up=lambda w, t, p=prio: self._prio_tap(w, t, p))
        return row

    def _prio_tap(self, w, touch, prio):
        if w.collide_point(*touch.pos) and abs(touch.y - touch.oy) < 10:
            old = self.app.core.settings.get("priority", 8)
            self.app.core.settings["priority"] = prio      # open the write box at that level
            self.write()
            self.app.core.settings["priority"] = old
            return True
        return False

    def write(self):
        if self.dev is None or self.oid is None:
            return
        write_popup(self.app, self.dev, self.oid, self.name_, self.props.get(C.PROP_PRESENT_VALUE),
                    self.props.get(C.PROP_UNITS), self.app.core.units_cache.get((self.dev.instance, self.oid, "st")),
                    after=lambda v: Clock.schedule_once(lambda dt: self.load(), 0.3))

    def watch(self):
        if self.dev is None or self.oid is None:
            return
        self.app.core.add_watch(self.dev, self.oid, self.name_)
        self.watch_btn.text = "On Watch"
        toast("Added to Watch")

    def on_enter(self, *a):
        self._ev = Clock.schedule_interval(lambda dt: self.load(), max(2.0, self.app.core.refresh * 2))
        self.ticker.start()

    def on_leave(self, *a):
        self.ticker.stop()
        if self._ev:
            self._ev.cancel()
            self._ev = None


class WatchScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="watch", **kw)
        self.info = lbl("", 13, color=T["muted"], size_hint_y=None, height=dp(36))
        self.root_box.add_widget(self.info)
        self.rv = make_list()
        self.root_box.add_widget(self.rv)
        self._ev = None

    def refresh(self):
        core = self.app.core
        blink = int(time.time() * 4) % 2 == 0
        rows = []
        for w in core.watch:
            dev = core.device(w.dev)
            fault = isinstance(w.flags, X.BitString) and any(w.flags.bits[:2])
            bg = (T["flash"] if blink else T["flash2"]) if w.flashing else None
            row = {"title": w.name, "sub": f"{w.dev}  {w.oid.short}" + ("" if dev else "  (device not found yet)"),
                   "value": w.text, "value_color": (0, 0, 0, 1) if w.flashing and blink else
                   (T["danger"] if fault else T["pv"]), "action": "x",
                   "on_tap": lambda zone, data, w=w: self.tap(zone, w)}
            if bg:
                row["bg"] = bg
            rows.append(row)
        self.rv.data = rows
        self.info.text = (f"{len(rows)} points, live every {core.refresh:g} s  ·  tap value = write  ·  "
                          "tap name = open  ·  x = remove") if rows else \
            "Your Watch list is empty - open a device and press + next to a point."

    def tap(self, zone, w: WatchItem):
        core = self.app.core
        dev = core.device(w.dev)
        if zone == "action":
            core.remove_watch(w)
            self.refresh()
            return
        if dev is None:
            toast("Device not discovered yet - press Discover")
            return
        if zone == "value":
            write_popup(self.app, dev, w.oid, w.name, w.value, core.units_cache.get((w.dev, w.oid)),
                        core.units_cache.get((w.dev, w.oid, "st")))
        else:
            self.app.open_point(dev, w.oid, w.name)

    def on_enter(self, *a):
        self.refresh()
        self._ev = Clock.schedule_interval(lambda dt: self.refresh(), 0.25)

    def on_leave(self, *a):
        if self._ev:
            self._ev.cancel()
            self._ev = None


class GraphicsScreen(BaseScreen):
    ZOOMS = ["Fit", "75%", "100%", "150%", "200%"]

    def __init__(self, app, **kw):
        super().__init__(app, name="graphics", **kw)
        self.model = app.graphics
        self.flash = Flash()                       # points-list values highlighted 3 s on change
        r1 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.page_sp = spinner([], "", self._page_chosen)
        r1.add_widget(self.page_sp)
        r1.add_widget(btn("+", self.new_page, size=20, size_hint_x=None, width=dp(46)))
        r1.add_widget(btn("...", self.page_menu, size=18, size_hint_x=None, width=dp(46)))
        self.root_box.add_widget(r1)
        r2 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.eq_sp = spinner([self.model.templates[i].NAME for i in self.model.ids], "", self._equip_chosen)
        r2.add_widget(self.eq_sp)
        r2.add_widget(btn("Auto-link", self.auto_link, "accent", size_hint_x=None, width=dp(100)))
        self.root_box.add_widget(r2)
        self.opts = BoxLayout(size_hint_y=None, height=dp(0), spacing=dp(6))
        self.root_box.add_widget(self.opts)
        r3 = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        self.zoom_sp = spinner(self.ZOOMS, "Fit", self._zoom_chosen, size_hint_x=None, width=dp(90))
        r3.add_widget(self.zoom_sp)
        self.demo_tb = ToggleButton(text="Demo", font_size=sp(14), background_normal="", background_down="",
                                    background_color=T["button"], color=T["button_fg"], size_hint_x=None, width=dp(80))
        self.demo_tb.bind(state=lambda w, s: self._demo(s == "down"))
        r3.add_widget(self.demo_tb)
        r3.add_widget(btn("Points list", self.points_list))
        self.root_box.add_widget(r3)
        self.scroll = ScrollView(do_scroll_x=True, do_scroll_y=True, bar_width=dp(5))
        self.gw = GraphicWidget(self.model, self.tap_point, size_hint=(1, 1))
        self.scroll.add_widget(self.gw)
        self.root_box.add_widget(self.scroll)
        self.root_box.add_widget(lbl("Tap an element to link it, write it or open the point", 12,
                                     color=T["muted"], size_hint_y=None, height=dp(20), halign="center"))
        self.sync_controls()

    # ---- controls
    def sync_controls(self):
        m = self.model
        self.page_sp.values = [f"{i + 1}. {p['name']}" for i, p in enumerate(m.pages)]
        p = m.page()
        self.page_sp.text = f"{m.current + 1}. {p['name']}" if p else ""
        tpl = m.template()
        self.eq_sp.text = tpl.NAME if tpl else ""
        self.opts.clear_widgets()
        if tpl and tpl.OPTIONS:
            self.opts.height = dp(46)
            for name, (label, lo, hi, _d) in tpl.OPTIONS.items():
                short = label.replace("Primary pumps", "Pri. pumps").replace("Secondary pumps", "Sec. pumps")
                self.opts.add_widget(lbl(short, 13, color=T["muted"], halign="right"))
                self.opts.add_widget(spinner([str(k) for k in range(lo, hi + 1)], str(tpl.options[name]),
                                             lambda v, n=name: self._opt(n, v), size_hint_x=None, width=dp(56)))
        else:
            self.opts.height = 0
        self.gw.dark = self.app.theme == "dark"
        self.gw.background = T["graphic_bg"]
        self._zoom_chosen(self.zoom_sp.text)

    def _page_chosen(self, text):
        try:
            idx = int(text.split(".")[0]) - 1
        except ValueError:
            return
        if idx != self.model.current:
            self.model.select(idx)
            self.sync_controls()

    def _equip_chosen(self, name):
        tid = next((i for i in self.model.ids if self.model.templates[i].NAME == name), None)
        p = self.model.page()
        if tid and p and tid != p["template"]:
            lost = self.model.set_equipment(tid)
            if lost:
                toast(f"{lost} links removed (not on the new equipment)")
            self.sync_controls()

    def _opt(self, name, value):
        tpl = self.model.template()
        if tpl and str(tpl.options.get(name)) != value:
            lost = self.model.set_options({name: int(value)})
            if lost:
                toast(f"{lost} links removed")
            self.sync_controls()

    def _zoom_chosen(self, z):
        tpl = self.model.template()
        if z == "Fit" or not tpl:
            self.gw.zoom = None
            self.gw.size_hint = (1, 1)
        else:
            f = float(z.rstrip("%")) / 100 * dp(1)
            self.gw.zoom = f
            self.gw.size_hint = (None, None)
            self.gw.size = (tpl.WIDTH * f, tpl.HEIGHT * f)
        self.gw.redraw()

    def _demo(self, on):
        self.gw.demo = on

    def new_page(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        name = inp(f"PAGE-{len(self.model.pages) + 1:02d}", "Page name")
        eq = spinner([self.model.templates[i].NAME for i in self.model.ids],
                     self.model.templates[self.model.ids[0]].NAME, size_hint_y=None, height=dp(48))
        box.add_widget(name)
        box.add_widget(eq)
        pop = Popup(title="New graphic page", content=box, size_hint=(0.92, None), height=dp(300))

        def ok():
            tid = next(i for i in self.model.ids if self.model.templates[i].NAME == eq.text)
            self.model.add_page(name.text or "Page", tid)
            pop.dismiss()
            self.sync_controls()
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        row.add_widget(btn("Cancel", pop.dismiss))
        row.add_widget(btn("Create", ok, "accent"))
        box.add_widget(row)
        pop.open()

    def page_menu(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        name = inp(self.model.page()["name"] if self.model.page() else "", "Page name")
        box.add_widget(name)
        pop = Popup(title="Page", content=box, size_hint=(0.92, None), height=dp(300))

        def rename():
            self.model.rename(name.text)
            pop.dismiss()
            self.sync_controls()

        def delete():
            self.model.delete_page()
            pop.dismiss()
            self.sync_controls()
        box.add_widget(btn("Rename", rename, "accent", size_hint_y=None, height=dp(50)))
        box.add_widget(btn("Delete page", delete, "danger", size_hint_y=None, height=dp(50)))
        box.add_widget(btn("Close", pop.dismiss, size_hint_y=None, height=dp(50)))
        pop.open()

    def choose_device(self, title: str, then: Callable[[Any], None]):
        devs = self.app.core.devices()
        if not devs:
            message(title, "No devices discovered yet - go to Devices and press Discover.")
            return
        box = BoxLayout(orientation="vertical", padding=dp(6), spacing=dp(6))
        pop = Popup(title=title, content=box, size_hint=(0.94, 0.8))
        rv = make_list()
        rv.data = [{"title": f"{d.name or 'Device'} [{d.instance}]", "sub": str(d.address),
                    "sub_color": T["addr"], "value": "",
                    "on_tap": lambda z, data, d=d: (pop.dismiss(), then(d))} for d in devs]
        box.add_widget(rv)
        box.add_widget(btn("Cancel", pop.dismiss, size_hint_y=None, height=dp(48)))
        pop.open()

    def auto_link(self):
        def with_dev(dev):
            def names_ready(_r=None):
                sugg = self.model.suggest_links(dev.object_names)
                tpl = self.model.template()
                labels = {p.key: p.label for p in tpl.POINTS} if tpl else {}
                if not sugg:
                    message("Auto-link", "No matching point names found in this device.")
                    return
                box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
                pop = Popup(title=f"Link {len(sugg)} points to {dev.name}?"[:60], content=box,
                            size_hint=(0.95, 0.85))
                rv = make_list()
                rv.data = [{"title": labels.get(k, k), "sub": f"{o.short}  {n}", "value": ""}
                           for k, o, n in sugg]
                box.add_widget(rv)
                row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
                row.add_widget(btn("Cancel", pop.dismiss))
                row.add_widget(btn("Link all", lambda: (self.model.apply_links(dev.instance, sugg),
                                                        pop.dismiss(), toast(f"{len(sugg)} points linked")),
                                   "accent"))
                box.add_widget(row)
                pop.open()
            if dev.object_names and len(dev.object_names) >= len([o for o in dev.objects if o.type != 8]) > 0:
                names_ready()
            else:
                toast("Reading point names…", 6)
                self.app.core.load_objects(dev, lambda m: toast(m, 6), names_ready,
                                           lambda e: message("Auto-link", f"Could not read the device: {e}"))
        self.choose_device("Auto-link from which device?", with_dev)

    def tap_point(self, key: str):
        m = self.model
        page, tpl = m.page(), m.template()
        if not page or not tpl:
            return
        gp = tpl.point(key)
        link = page["links"].get(key)
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        pop = Popup(title=gp.label, content=box, size_hint=(0.92, None), height=dp(420))
        box.add_widget(lbl(gp.help, 13, color=T["muted"]))
        if link:
            st = m.states(self.gw.demo, time.time()).get(key)
            box.add_widget(lbl(f"Linked: [b]{link['device']} {ObjectId(*link['object']).short} "
                               f"{link.get('name', '')}[/b]", 14))
            box.add_widget(lbl(f"Value: [b]{st.text if st else '-'}[/b]", 16, color=T["pv"]))
            core = self.app.core
            k = m.link_key(link)
            oid = ObjectId(k[1], k[2])
            dev = core.device(k[0])

            def wr():
                pop.dismiss()
                if dev is None:
                    toast("Device not discovered yet")
                    return
                write_popup(self.app, dev, oid, link.get("name", ""), m.raw_value(link),
                            core.units_cache.get((k[0], oid)), core.units_cache.get((k[0], oid, "st")))

            def go():
                pop.dismiss()
                if dev is not None:
                    self.app.open_point(dev, oid, link.get("name", ""))
            box.add_widget(btn("Write value", wr, "accent", size_hint_y=None, height=dp(50)))
            box.add_widget(btn("Open point", go, size_hint_y=None, height=dp(48)))
            box.add_widget(btn("Unlink", lambda: (m.unlink(key), pop.dismiss()), size_hint_y=None, height=dp(48)))
        else:
            box.add_widget(lbl("Not linked yet.", 15))
            box.add_widget(btn("Link a point…", lambda: (pop.dismiss(), self.pick_object(key)), "accent",
                               size_hint_y=None, height=dp(52)))
        box.add_widget(btn("Close", pop.dismiss, size_hint_y=None, height=dp(48)))
        pop.open()

    def pick_object(self, key: str):
        def with_dev(dev):
            def show(items):
                box = BoxLayout(orientation="vertical", padding=dp(6), spacing=dp(6))
                pop = Popup(title=f"Choose the point in {dev.name}"[:60], content=box, size_hint=(0.95, 0.9))
                q = inp("", "Search…", size_hint_y=None, height=dp(48))
                rv = make_list()

                def fill(*_a):
                    t = q.text.lower()
                    rv.data = [{"title": p.name or str(p.oid), "sub": p.oid.short, "value": p.text(),
                                "value_color": T["pv"],
                                "on_tap": lambda z, d, p=p: (self.model.set_link(key, dev.instance, p.oid, p.name),
                                                             pop.dismiss(), toast("Linked"))}
                               for p in items if not t or t in p.name.lower() or t in p.oid.short.lower()]
                q.bind(text=fill)
                fill()
                box.add_widget(q)
                box.add_widget(rv)
                box.add_widget(btn("Cancel", pop.dismiss, size_hint_y=None, height=dp(48)))
                pop.open()
            toast("Reading points…", 6)
            self.app.core.load_objects(dev, lambda m: toast(m, 6), show,
                                       lambda e: message("Link", f"Could not read the device: {e}"))
        self.choose_device("Which device?", with_dev)

    def points_list(self):
        box = BoxLayout(orientation="vertical", padding=dp(6), spacing=dp(6))
        pop = Popup(title="Points of this graphic", content=box, size_hint=(0.95, 0.9))
        rv = make_list()

        def fill(*_a):
            page = self.model.current
            rv.data = [flash_row({"title": r["label"], "sub": r["linked"], "value": r["value"],
                                  "value_color": T["pv"],
                                  "on_tap": lambda z, d, r=r: (pop.dismiss(), self.tap_point(r["key"]))},
                                 self.flash.update((page, r["key"]), r["value"]))
                       for r in self.model.point_rows(self.gw.demo)]
        fill()
        ev = Clock.schedule_interval(fill, 0.25)
        pop.bind(on_dismiss=lambda *a: ev.cancel())
        box.add_widget(rv)
        box.add_widget(btn("Close", pop.dismiss, size_hint_y=None, height=dp(48)))
        pop.open()

    def on_enter(self, *a):
        self.model.sync()
        self.gw.start()

    def on_leave(self, *a):
        self.gw.stop()


class ReportScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="report", **kw)
        self.rep: Optional[Dict[str, Any]] = None
        self.cancel = threading.Event()
        self.cards = GridLayout(cols=3, size_hint_y=None, height=dp(150), spacing=dp(6))
        self.card_lbls: Dict[str, Label] = {}
        for k, t in (("dev_total", "Devices"), ("dev_on", "Online"), ("dev_off", "Offline"),
                     ("pt_total", "Points"), ("pt_on", "Points online"), ("pt_bad", "Fault / no reply")):
            c = Card(orientation="vertical", padding=dp(6))
            c.add_widget(lbl(t, 12, color=T["muted"], halign="center"))
            v = lbl("-", 24, bold=True, halign="center")
            c.add_widget(v)
            self.card_lbls[k] = v
            self.cards.add_widget(c)
        self.root_box.add_widget(self.cards)
        r = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        r.add_widget(btn("Count devices", lambda: self.start(False), "accent", size=14))
        r.add_widget(btn("Devices + points", lambda: self.start(True), "accent", size=14))
        self.root_box.add_widget(r)
        r2 = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.whois = CheckBox(active=True, size_hint_x=None, width=dp(40), color=T["accent"])
        r2.add_widget(self.whois)
        r2.add_widget(lbl("Who-Is first", 13))
        r2.add_widget(btn("Stop", self.cancel.set, size_hint_x=None, width=dp(70)))
        r2.add_widget(btn("Excel", self.export, size_hint_x=None, width=dp(80)))
        self.root_box.add_widget(r2)
        self.status = lbl("Count how many devices and points are online.", 13, color=T["muted"],
                          size_hint_y=None, height=dp(24))
        self.root_box.add_widget(self.status)
        self.rv = make_list()
        self.root_box.add_widget(self.rv)
        self.running = False

    def start(self, with_points: bool):
        if self.running or not self.app.core.online:
            return
        self.running = True
        self.cancel.clear()
        self.app.core.scan(with_points, self.whois.active,
                           lambda t, i, n: setattr(self.status, "text", t), self.done, self.cancel)

    def done(self, rep):
        self.running = False
        self.rep = rep
        if rep.get("error"):
            self.status.text = f"Error: {rep['error']}"
            return
        c = Core.report_counts(rep)
        c["pt_bad"] = c["pt_fault"] + c["pt_noresp"]
        for k, w in self.card_lbls.items():
            if k.startswith("pt") and not rep.get("points"):
                w.text = "-"
                continue
            w.text = str(c[k])
            w.color = T["good"] if k in ("dev_on", "pt_on") else (T["danger"] if k in ("dev_off", "pt_bad") and c[k] else T["fg"])
        self.status.text = ("Stopped. " if rep.get("cancelled") else "") + f"Finished {rep.get('time', '')}"
        rows = []
        for d in sorted(rep["devices"].values(), key=lambda r: r["inst"]):
            online = d["status"] == "Online"
            pts = f"   {d['ok']}/{d['points']} points online" if d["points"] != "" else ""
            rows.append({"title": f"{d['name'] or 'Device'} [{d['inst']}]", "sub": f"{d['addr']}{pts}",
                         "value": d["status"], "value_color": T["good"] if online else T["danger"]})
        self.rv.data = rows

    def export(self):
        if not self.rep or not self.rep.get("devices"):
            toast("Count the devices first")
            return
        name = f"BACnet_online_report_{time.strftime('%Y%m%d_%H%M')}.xlsx"
        path = os.path.join(self.app.core.data_dir, name)
        try:
            self.app.core.export_report(self.rep, path)
            where, uri = PA.save_to_downloads(path)
        except Exception as e:
            message("Export", f"Could not save: {e}")
            return
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        box.add_widget(lbl(f"Saved [b]{name}[/b]\nto {where}", 15))
        pop = Popup(title="Excel report", content=box, size_hint=(0.92, None), height=dp(300))
        if PA.IS_ANDROID:
            box.add_widget(btn("Share (WhatsApp, e-mail ...)", lambda: PA.share(uri or path), "accent",
                               size_hint_y=None, height=dp(52)))
        box.add_widget(btn("OK", pop.dismiss, size_hint_y=None, height=dp(48)))
        pop.open()


class SettingsScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="settings", **kw)
        core = app.core
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(8), padding=(0, dp(4)))
        grid.bind(minimum_height=grid.setter("height"))

        def section(t):
            grid.add_widget(lbl(f"[b]{t}[/b]", 15, color=T["accent"], size_hint_y=None, height=dp(30)))

        def line(label, widget):
            r = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
            r.add_widget(lbl(label, 14, size_hint_x=0.45))
            r.add_widget(widget)
            grid.add_widget(r)

        section("Display")
        line("View", spinner(["Light", "Dark"], app.theme.capitalize(), lambda v: app.set_theme(v.lower())))
        line("Live refresh", spinner(["1 s", "2 s", "5 s", "10 s"], f"{core.refresh:g} s",
                                     lambda v: core.set_refresh(float(v.split()[0]))))
        line("Write priority", spinner([str(k) for k in range(1, 17)], str(core.priority),
                                       lambda v: (core.settings.__setitem__("priority", int(v)), core.save())))
        section("Network")
        net = core.settings.get("net", {})
        self.adapter_sp = spinner([], "Automatic", self.adapter_chosen)
        self.adapter_name = net.get("adapter", "")
        self.fill_adapters()
        line("Adapter", self.adapter_sp)
        grid.add_widget(lbl("Choose the USB-C Ethernet adapter or Wi-Fi to use for BACnet. "
                            "Automatic = Android's current network.", 12, color=T["muted"],
                            size_hint_y=None, height=dp(36)))
        ip, prefix, bc = PA.network_info(self.adapter_name)
        self.ip = inp(net.get("ip", "") or ip, "Phone IP")
        self.bc = inp(net.get("broadcast", "") or bc, "Broadcast")
        self.port = inp(str(net.get("port", 47808)), "Local UDP port", number=True)
        self.rport = inp(str(net.get("remote_port", 47808)), "Device UDP port", number=True)
        self.bbmd = inp(net.get("bbmd", ""), "BBMD IP (optional)")
        line("Phone IP", self.ip)
        line("Broadcast", self.bc)
        line("Local port", self.port)
        line("Device port", self.rport)
        line("BBMD (other subnet)", self.bbmd)
        grid.add_widget(lbl(f"Detected network: {ip}/{prefix}, broadcast {bc}", 12, color=T["muted"],
                            size_hint_y=None, height=dp(22)))
        grid.add_widget(btn("Rescan adapters / Auto-detect", self.autodetect, size_hint_y=None, height=dp(46)))
        grid.add_widget(btn("Apply & reconnect", self.apply, "accent", size_hint_y=None, height=dp(52)))
        section("Account")
        r = BoxLayout(size_hint_y=None, height=dp(48))
        auto = CheckBox(active=core.auth.autologin_ok(), size_hint_x=None, width=dp(48), color=T["accent"])
        auto.bind(active=lambda w, v: (core.auth.enable_autologin() if v else core.auth.disable_autologin(), core.save()))
        r.add_widget(auto)
        r.add_widget(lbl("Auto login on this phone", 14))
        grid.add_widget(r)
        grid.add_widget(btn("Change password", self.change_password, size_hint_y=None, height=dp(48)))
        grid.add_widget(btn("Log out", app.logout, "danger", size_hint_y=None, height=dp(48)))
        section("Log")
        grid.add_widget(btn("Show communication log", self.show_log, size_hint_y=None, height=dp(46)))
        grid.add_widget(lbl(f"{APP_NAME} {APP_VERSION} - Android version of Basil BACnet Explorer",
                            12, color=T["muted"], size_hint_y=None, height=dp(40)))
        sc = ScrollView(do_scroll_x=False)
        sc.add_widget(grid)
        self.root_box.add_widget(sc)

    def fill_adapters(self):
        """(Re)list the phone's adapters - plug the USB-C adapter in, then press Rescan."""
        self.adapters = {PA.adapter_label(a): a for a in PA.list_adapters()}
        self.adapter_sp.values = ["Automatic"] + list(self.adapters)
        cur = next((lab for lab, a in self.adapters.items() if a["name"] == self.adapter_name), None)
        if self.adapter_name and cur is None:
            cur = f"{self.adapter_name} (not connected)"
        self._filling = True
        self.adapter_sp.text = cur or "Automatic"
        self._filling = False

    def adapter_chosen(self, label: str):
        if getattr(self, "_filling", False):
            return
        a = self.adapters.get(label)
        self.adapter_name = a["name"] if a else ("" if label == "Automatic" else self.adapter_name)
        if a:
            self.ip.text, self.bc.text = a["ip"], a["broadcast"]
        elif label == "Automatic":
            ip, _p, bc = PA.network_info()
            self.ip.text, self.bc.text = ip, bc

    def autodetect(self):
        self.fill_adapters()
        ip, _p, bc = PA.network_info(self.adapter_name)
        self.ip.text, self.bc.text = ip, bc
        toast(f"{len(self.adapters)} adapter(s) found")

    def apply(self):
        def num(w, d):
            try:
                return int(float(w.text))
            except ValueError:
                return d
        self.app.core.settings["net"] = {"ip": self.ip.text.strip(), "broadcast": self.bc.text.strip(),
                                         "port": num(self.port, 47808), "remote_port": num(self.rport, 47808),
                                         "bbmd": self.bbmd.text.strip(), "adapter": self.adapter_name}
        self.app.core.save()
        self.app.connect()

    def change_password(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        old, new, new2 = inp("", "Current password", True), inp("", "New password", True), inp("", "Repeat new password", True)
        msg = lbl("At least 8 characters, upper + lower case and a number.", 12, color=T["muted"],
                  size_hint_y=None, height=dp(40))
        for w in (old, new, new2, msg):
            box.add_widget(w)
        pop = Popup(title="Change password", content=box, size_hint=(0.92, None), height=dp(420))

        def ok():
            if new.text != new2.text:
                msg.text = "The new passwords do not match."
                return
            err = self.app.core.auth.change_password(old.text, new.text)
            if err:
                msg.text = err
                return
            self.app.core.save()
            pop.dismiss()
            toast("Password changed")
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        row.add_widget(btn("Cancel", pop.dismiss))
        row.add_widget(btn("Change", ok, "accent"))
        box.add_widget(row)
        pop.open()

    def show_log(self):
        box = BoxLayout(orientation="vertical", padding=dp(6), spacing=dp(6))
        ti = TextInput(text="\n".join(self.app.core.log_lines[-300:]), readonly=True, font_size=sp(11),
                       background_color=T["input"], foreground_color=T["fg"])
        box.add_widget(ti)
        pop = Popup(title="Communication log", content=box, size_hint=(0.96, 0.9))
        box.add_widget(btn("Close", pop.dismiss, size_hint_y=None, height=dp(48)))
        pop.open()


# ---------------------------------------------------------------------------- login
class LoginView(BoxLayout):
    def __init__(self, app: "BasilApp", **kw):
        super().__init__(orientation="vertical", padding=(dp(28), dp(40)), spacing=dp(12), **kw)
        self.app = app
        self.tries = 0
        self.locked_until = 0.0
        with self.canvas.before:
            Color(*T["bg"])
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *a: setattr(self._bg, "pos", self.pos), size=lambda *a: setattr(self._bg, "size", self.size))
        logo = os.path.join(app.assets, "logo_256.png")
        if os.path.exists(logo):
            self.add_widget(Image(source=logo, size_hint_y=None, height=dp(96)))
        self.add_widget(lbl(f"[b]{APP_NAME}[/b]", 26, halign="center", size_hint_y=None, height=dp(40)))
        self.add_widget(lbl("BACnet/IP discovery & commissioning", 14, color=T["muted"], halign="center",
                            size_hint_y=None, height=dp(24)))
        self.user = inp(app.core.auth.record()["user"], "Username", size_hint_y=None, height=dp(52))
        self.pw = inp("", "Password", password=True, size_hint_y=None, height=dp(52))
        self.pw.bind(on_text_validate=lambda *_: self.login())
        self.add_widget(self.user)
        self.add_widget(self.pw)
        r = BoxLayout(size_hint_y=None, height=dp(44))
        self.remember = CheckBox(active=True, size_hint_x=None, width=dp(44), color=T["accent"])
        r.add_widget(self.remember)
        r.add_widget(lbl("Remember me on this phone (auto login)", 14))
        self.add_widget(r)
        self.msg = lbl("", 14, color=T["danger"], halign="center", size_hint_y=None, height=dp(28))
        self.add_widget(self.msg)
        self.add_widget(btn("LOGIN", self.login, "accent", size=18, size_hint_y=None, height=dp(56)))
        self.add_widget(Label())

    def login(self):
        now = time.time()
        if now < self.locked_until:
            self.msg.text = f"Too many attempts - wait {int(self.locked_until - now) + 1} s"
            return
        auth = self.app.core.auth
        if auth.check(self.user.text, self.pw.text):
            if self.remember.active:
                auth.enable_autologin()
            self.app.core.save()
            self.app.show_main()
            return
        self.tries += 1
        self.pw.text = ""
        if self.tries >= authcore.MAX_TRIES:
            self.tries = 0
            self.locked_until = now + authcore.LOCK_SECONDS
            self.msg.text = f"Too many attempts - locked for {authcore.LOCK_SECONDS} s"
        else:
            self.msg.text = f"Wrong username or password ({authcore.MAX_TRIES - self.tries} tries left)"


# ---------------------------------------------------------------------------- app
class BasilApp(App):
    title = APP_NAME
    TABS = [("devices", "Devices"), ("watch", "Watch"), ("graphics", "Graphics"), ("report", "Report"),
            ("settings", "Settings")]

    def build(self):
        self.icon = os.path.join(self.assets, "logo_256.png")
        authcore.EXTRA_MACHINE_ID = PA.device_id()
        self.core = Core(self.user_data_dir, post=lambda fn: Clock.schedule_once(lambda dt: fn(), 0))
        self.theme = self.core.settings.get("theme", "light") if self.core.settings.get("theme") in THEMES else "light"
        T.update(THEMES[self.theme])
        Window.clearcolor = T["bg"]
        Window.bind(on_keyboard=self.on_key)
        self.status_label: Optional[Label] = None
        self.graphics = GraphicsModel(self.core)
        self.back_stack: List[str] = []
        self.holder = BoxLayout()
        if self.core.auth.autologin_ok():
            Clock.schedule_once(lambda dt: self.show_main(), 0)
        else:
            self.holder.add_widget(LoginView(self))
        return self.holder

    @property
    def assets(self) -> str:
        for d in (os.path.join(HERE, "assets"), os.path.join(os.path.dirname(HERE), "assets")):
            if os.path.isdir(d):
                return d
        return HERE

    # ---- main UI
    def show_main(self):
        self.holder.clear_widgets()
        root = BoxLayout(orientation="vertical")
        top = Card(bg=T["bar"], size_hint_y=None, height=dp(56), padding=(dp(10), dp(6)), spacing=dp(8))
        logo = os.path.join(self.assets, "logo_64.png")
        if os.path.exists(logo):
            top.add_widget(Image(source=logo, size_hint_x=None, width=dp(40)))
        top.add_widget(lbl(f"[b]{APP_NAME}[/b]", 18))
        self.status_label = lbl("", 12, color=T["muted"], halign="right")
        top.add_widget(self.status_label)
        root.add_widget(top)
        self.sm = ScreenManager(transition=NoTransition())
        self.screens = {
            "devices": DevicesScreen(self), "device": DeviceScreen(self), "point": PointScreen(self),
            "watch": WatchScreen(self), "graphics": GraphicsScreen(self), "report": ReportScreen(self),
            "settings": SettingsScreen(self)}
        for s in self.screens.values():
            self.sm.add_widget(s)
        root.add_widget(self.sm)
        nav = Card(bg=T["bar"], size_hint_y=None, height=dp(58), spacing=dp(2), padding=dp(2))
        self.nav_btns: Dict[str, ToggleButton] = {}
        for key, text in self.TABS:
            b = ToggleButton(text=text, group="nav", font_size=sp(13), background_normal="", background_down="",
                             background_color=T["bar"], color=T["muted"], allow_no_selection=False)
            b.bind(on_release=lambda w, k=key: self.tab(k))
            nav.add_widget(b)
            self.nav_btns[key] = b
        root.add_widget(nav)
        self.holder.add_widget(root)
        self.core.on_devices = self.devices_changed
        self.core.on_watch = lambda: self.screens["watch"].refresh() if self.sm.current == "watch" else None
        self.core.on_status = lambda t: toast(t)
        self.tab(self.core.settings.get("last_tab", "devices") if self.core.settings.get("last_tab") in dict(self.TABS) else "devices")
        if not self.core.online:
            self.connect()
        if not getattr(self, "_status_ev", None):
            self._status_ev = Clock.schedule_interval(lambda dt: self.update_status(), 3)

    def tab(self, key: str):
        self.back_stack.clear()
        for k, b in self.nav_btns.items():
            b.state = "down" if k == key else "normal"
            b.color = T["accent"] if k == key else T["muted"]
            b.bold = k == key
        self.sm.current = key
        self.screens[key].refresh()
        self.core.settings["last_tab"] = key

    def push(self, name: str):
        self.back_stack.append(self.sm.current)
        self.sm.current = name

    def go_back(self):
        if self.back_stack:
            self.sm.current = self.back_stack.pop()
            self.screens[self.sm.current].refresh()
            return True
        if self.sm.current != "devices":
            self.tab("devices")
            return True
        return False

    def on_key(self, window, key, *args):
        if key == 27:                     # Android back button
            return self.go_back()
        return False

    def open_device(self, dev):
        self.screens["device"].open(dev)
        self.push("device")

    def open_point(self, dev, oid, name):
        self.screens["point"].open(dev, oid, name)
        self.push("point")

    # ---- network
    def connect(self):
        PA.acquire_multicast_lock()
        net = self.core.settings.get("net", {})
        adapter = net.get("adapter", "")
        if not PA.bind_to_adapter(adapter):
            message("Network", f"The adapter '{adapter}' is not connected.\n\nPlug in the USB-C adapter and "
                               "check its cable / IP address, or choose another adapter in Settings > Network.")
        ip, _p, bc = PA.network_info(adapter)
        if adapter:                        # the chosen adapter's own address, not an old saved one
            a = PA.find_adapter(adapter)
            if a:
                net = dict(net, ip=a["ip"], broadcast=a["broadcast"])
        err = self.core.connect(net.get("ip") or ip, net.get("broadcast") or bc, int(net.get("port", 47808)),
                                int(net.get("remote_port", 47808)), net.get("bbmd", ""))
        if err:
            message("Network", f"Could not start BACnet/IP:\n{err}")
        else:
            self.discover()
        self.update_status()

    def discover(self):
        if not self.core.online:
            self.connect()
            return
        self.core.discover()
        toast("Who-Is sent - devices appear as they answer")

    def devices_changed(self):
        cur = self.sm.current if hasattr(self, "sm") else ""
        if cur == "devices":
            self.screens["devices"].refresh()
        self.graphics.sync()
        self.update_status()

    def update_status(self):
        if self.status_label is None:
            return
        cl = self.core.client
        if cl and cl.running:
            ad = PA.find_adapter(self.core.settings.get("net", {}).get("adapter", ""))
            via = f"{ad['kind']}  " if ad else ""
            self.status_label.text = (f"[color={hexc(T['good'])}]Online[/color]  {via}{cl.local_ip}  ·  "
                                      f"{len(cl.devices)} devices")
        else:
            self.status_label.text = f"[color={hexc(T['danger'])}]Offline[/color]"

    # ---- theme / account
    def set_theme(self, mode: str):
        if mode == self.theme or mode not in THEMES:
            return
        self.theme = mode
        self.core.settings["theme"] = mode
        self.core.save()
        T.update(THEMES[mode])
        Window.clearcolor = T["bg"]
        tab = self.sm.current if hasattr(self, "sm") else "settings"
        self.show_main()                  # rebuild every screen with the new colours
        self.tab("settings" if tab not in dict(self.TABS) else tab)

    def logout(self):
        self.core.auth.disable_autologin()
        self.core.save()
        self.holder.clear_widgets()
        self.holder.add_widget(LoginView(self))

    # ---- lifecycle
    def on_pause(self):
        self.core.save()
        return True

    def on_resume(self):
        PA.acquire_multicast_lock()

    def on_stop(self):
        self.core.close()
        PA.release_multicast_lock()


if __name__ == "__main__":
    BasilApp().run()
