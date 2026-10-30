"""
A small stand-in for the Kivy package, so the Android app's screens (android/main.py) can be
driven in tests on a machine without Kivy. It is NOT Kivy: it only records widgets, properties,
callbacks and drawing instructions closely enough to exercise the app's own logic.
"""
import sys
import types

CALLS = {"popups": [], "clock": [], "instructions": 0}


class _Canvas:
    def __init__(self):
        self.before = self
        self.after = self
        self.items = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def clear(self):
        self.items = []

    def add(self, x):
        self.items.append(x)


class Instruction:
    def __init__(self, *a, **k):
        CALLS["instructions"] += 1
        self.args, self.kw = a, k
        for key, v in k.items():
            object.__setattr__(self, key, v)
        if a:
            self.rgba = a


class EventDispatcher:
    def __init__(self, **kw):
        object.__setattr__(self, "_binds", {})
        for k, v in kw.items():
            object.__setattr__(self, k, v)

    def bind(self, **kw):
        for k, f in kw.items():
            self._binds.setdefault(k, []).append(f)

    def unbind(self, **kw):
        pass

    def __setattr__(self, k, v):
        object.__setattr__(self, k, v)
        for f in getattr(self, "_binds", {}).get(k, []):
            f(self, v)

    def dispatch(self, ev, *a):
        res = None
        for f in self._binds.get(ev, []):
            r = f(self, *a)
            if r:
                return r
        meth = getattr(self, ev, None)
        if callable(meth):
            res = meth(*a)
        return res

    def setter(self, name):
        return lambda inst, v: setattr(self, name, v)


class Widget(EventDispatcher):
    def __init__(self, **kw):
        defaults = dict(x=0, y=0, width=360, height=640, pos=(0, 0), size=(360, 640), size_hint=(1, 1),
                        size_hint_x=1, size_hint_y=1, opacity=1, disabled=False, text="", color=(1, 1, 1, 1))
        defaults.update(kw)
        super().__init__(**defaults)
        object.__setattr__(self, "children", [])
        object.__setattr__(self, "parent", None)
        object.__setattr__(self, "canvas", _Canvas())

    def add_widget(self, w, *a, **k):
        self.children.insert(0, w)
        object.__setattr__(w, "parent", self)

    def remove_widget(self, w):
        if w in self.children:
            self.children.remove(w)

    def clear_widgets(self, *a):
        self.children[:] = []

    def collide_point(self, x, y):
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height

    @property
    def right(self):
        return self.x + self.width

    @property
    def center_x(self):
        return self.x + self.width / 2

    def walk(self):
        yield self
        for c in list(self.children):
            yield from c.walk()

    def on_touch_up(self, touch):
        return False


class Label(Widget):
    def __init__(self, **kw):
        kw.setdefault("text", "")
        super().__init__(**kw)


class ButtonBehavior:
    last_touch = None

    def __init__(self, **kw):
        super().__init__(**kw)

    def trigger(self):
        self.dispatch("on_press")
        self.dispatch("on_release")


class Button(ButtonBehavior, Label):
    pass


class ToggleButton(Button):
    def __init__(self, **kw):
        kw.setdefault("state", "normal")
        super().__init__(**kw)


class BoxLayout(Widget):
    pass


class GridLayout(Widget):
    pass


class FloatLayout(Widget):
    pass


class ScrollView(Widget):
    pass


class Image(Widget):
    pass


class CheckBox(Widget):
    def __init__(self, **kw):
        kw.setdefault("active", False)
        super().__init__(**kw)


class TextInput(Widget):
    def __init__(self, **kw):
        kw.setdefault("text", "")
        super().__init__(**kw)


class Spinner(Button):
    def __init__(self, **kw):
        kw.setdefault("values", [])
        super().__init__(**kw)


class Popup(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        if kw.get("content") is not None:
            self.add_widget(kw["content"])

    def open(self):
        CALLS["popups"].append(self)

    def dismiss(self, *a):
        if self in CALLS["popups"]:
            CALLS["popups"].remove(self)
        self.dispatch("on_dismiss")


class Screen(Widget):
    def on_enter(self, *a):
        pass

    def on_leave(self, *a):
        pass


class ScreenManager(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        object.__setattr__(self, "_screens", {})
        object.__setattr__(self, "_current", "")

    def add_widget(self, s, *a, **k):
        super().add_widget(s)
        self._screens[s.name] = s
        if not self._current:
            object.__setattr__(self, "_current", s.name)

    @property
    def current(self):
        return self._current

    @current.setter
    def current(self, name):
        old = self._screens.get(self._current)
        if old is not None and name != self._current:
            old.on_leave()
        object.__setattr__(self, "_current", name)
        self._screens[name].on_enter()

    def __setattr__(self, k, v):
        if k == "current":
            type(self).current.fset(self, v)
        else:
            super().__setattr__(k, v)


class NoTransition:
    pass


class RecycleView(Widget):
    def __init__(self, **kw):
        kw.setdefault("data", [])
        super().__init__(**kw)


class RecycleBoxLayout(Widget):
    pass


class RecycleDataViewBehavior:
    pass


class ListProperty:
    def __init__(self, default=None):
        self.default = default

    def __set_name__(self, owner, name):
        self.name = "_lp_" + name

    def __get__(self, obj, owner):
        if obj is None:
            return self
        return obj.__dict__.get(self.name, list(self.default or []))

    def __set__(self, obj, v):
        obj.__dict__[self.name] = list(v)
        for f in obj.__dict__.get("_binds", {}).get(self.name[4:], []):
            f(obj, v)


class _Event:
    def __init__(self, fn, interval):
        self.fn, self.interval, self.cancelled = fn, interval, False

    def cancel(self):
        self.cancelled = True


class Clock:
    @staticmethod
    def schedule_once(fn, timeout=0):
        ev = _Event(fn, None)
        CALLS["clock"].append(ev)
        return ev

    @staticmethod
    def schedule_interval(fn, interval):
        ev = _Event(fn, interval)
        CALLS["clock"].append(ev)
        return ev


def run_clock(rounds=3):
    """Run pending one-shot callbacks and one tick of every interval."""
    for _ in range(rounds):
        evs = list(CALLS["clock"])
        CALLS["clock"][:] = [e for e in evs if e.interval is not None and not e.cancelled]
        for e in evs:
            if not e.cancelled:
                e.fn(0)


class CoreLabel:
    def __init__(self, **kw):
        self.kw = kw
        self.texture = types.SimpleNamespace(size=(len(kw.get("text", "")) * kw.get("font_size", 10) * 0.6,
                                                   kw.get("font_size", 10) * 1.2))

    def refresh(self):
        pass


class Tesselator:
    def __init__(self):
        self.meshes = []

    def add_contour(self, pts):
        n = len(pts) // 2
        self.meshes = [(pts, list(range(n)))]

    def tesselate(self, *a):
        return True


class App(EventDispatcher):
    _running = None
    user_data_dir = "/tmp"

    @classmethod
    def get_running_app(cls):
        return cls._running

    def __init__(self, **kw):
        super().__init__(**kw)
        App._running = self


class _Window(EventDispatcher):
    clearcolor = (0, 0, 0, 1)


def install():
    mods = {}

    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        mods[name] = m
        return m
    mod("kivy", __version__="fake")
    mod("kivy.app", App=App)
    mod("kivy.clock", Clock=Clock)
    mod("kivy.core")
    mod("kivy.core.window", Window=_Window())
    mod("kivy.core.text", Label=CoreLabel)
    g = mod("kivy.graphics")
    for n in ("Color", "Rectangle", "Ellipse", "Line", "Mesh"):
        setattr(g, n, type(n, (Instruction,), {}))
    mod("kivy.graphics.tesselator", Tesselator=Tesselator, TYPE_POLYGONS=1, WINDING_ODD=0)
    mod("kivy.metrics", dp=lambda v: v, sp=lambda v: v)
    mod("kivy.properties", ListProperty=ListProperty)
    mod("kivy.utils", platform="linux")
    mod("kivy.uix")
    mod("kivy.uix.widget", Widget=Widget)
    mod("kivy.uix.behaviors", ButtonBehavior=ButtonBehavior)
    for name, cls in (("boxlayout", BoxLayout), ("button", Button), ("checkbox", CheckBox),
                      ("gridlayout", GridLayout), ("image", Image), ("label", Label), ("popup", Popup),
                      ("recycleboxlayout", RecycleBoxLayout), ("scrollview", ScrollView),
                      ("spinner", Spinner), ("textinput", TextInput), ("togglebutton", ToggleButton)):
        mod(f"kivy.uix.{name}", **{cls.__name__: cls})
    mod("kivy.uix.recycleview", RecycleView=RecycleView)
    mod("kivy.uix.recycleview.views", RecycleDataViewBehavior=RecycleDataViewBehavior)
    mod("kivy.uix.screenmanager", NoTransition=NoTransition, Screen=Screen, ScreenManager=ScreenManager)
    sys.modules.update(mods)
