"""
Runs the REAL Kivy app against the simulator (used by the GitHub build) and saves phone-sized
screenshots of every tab into ./screenshots - a visual check before installing the APK.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("KIVY_NO_ARGS", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]
from kivy.config import Config  # noqa: E402
Config.set("graphics", "width", "412")
Config.set("graphics", "height", "860")
from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402

DATA = tempfile.mkdtemp()
OUT = os.path.join(ROOT, "screenshots")
os.makedirs(OUT, exist_ok=True)
json.dump({"net": {"ip": "127.0.0.1", "broadcast": "127.255.255.255", "port": 47895,
                   "remote_port": 47809, "bbmd": ""}}, open(os.path.join(DATA, "settings.json"), "w"))
sim = subprocess.Popen([sys.executable, "bacnet_simulator.py", "--port", "47809"], cwd=ROOT)
time.sleep(1.5)
import main as M  # noqa: E402
import platform_android as PA  # noqa: E402
PA.network_info = lambda: ("127.0.0.1", 8, "127.255.255.255")


class CIApp(M.BasilApp):
    @property
    def user_data_dir(self):
        return DATA

    def on_start(self):
        steps = []
        n = [0]

        def shot(name):
            n[0] += 1
            path = os.path.join(OUT, f"{n[0]:02d}_{name}.png")
            try:
                Window.screenshot(name=path)           # whole window, popups included
            except Exception:
                self.root.export_to_png(path)
            print("screenshot", name, flush=True)

        def step(delay, fn):
            steps.append((delay, fn))

        def login():
            v = self.holder.children[0]
            shot("login")
            v.pw.text = "Basil@12345"
            v.login()
        step(1.5, login)
        step(1.0, lambda: self.core.discover(("127.0.0.1", 47809)))
        step(4.0, lambda: (self.screens["devices"].refresh(), shot("devices")))
        step(0.5, lambda: self.open_device(self.core.device(3001)))
        step(5.0, lambda: shot("device_points"))
        step(0.5, lambda: self.open_point(self.core.device(3001), M.ObjectId(1, 1), "Cooling Valve"))
        step(4.0, lambda: shot("point"))

        def write_box():
            M.write_popup(self, self.core.device(3001), M.ObjectId(1, 1), "Cooling Valve", 55.0, 98)
        step(0.5, write_box)
        step(1.0, lambda: shot("write"))

        def close_popups():
            from kivy.uix.popup import Popup
            for w in list(Window.children):
                if isinstance(w, Popup):
                    w.dismiss()
        step(0.5, close_popups)

        def watch():
            d = self.core.device(3001)
            for oid, nm in ((M.ObjectId(4, 1), "Supply Fan Command"), (M.ObjectId(0, 3), "Supply Air Temp"),
                            (M.ObjectId(0, 2), "CO2 Sensor"), (M.ObjectId(1, 2), "Fresh Air Damper")):
                self.core.add_watch(d, oid, nm)
            self.tab("watch")
        step(0.5, watch)
        step(4.0, lambda: shot("watch"))

        def graphics():
            g = self.graphics
            g.add_page("AHU-01", "ahu_sr")
            g.apply_links(3001, g.suggest_links(self.core.device(3001).object_names))
            self.tab("graphics")
            self.screens["graphics"].sync_controls()
        step(0.5, graphics)
        step(5.0, lambda: shot("graphics"))

        def report():
            self.tab("report")
            rs = self.screens["report"]
            rs.whois.active = False
            rs.start(True)
        step(0.5, report)
        step(12.0, lambda: shot("report"))
        step(0.5, lambda: self.tab("settings"))
        step(1.0, lambda: shot("settings"))
        step(0.5, lambda: self.set_theme("dark"))
        step(0.5, lambda: self.tab("devices"))
        step(1.5, lambda: shot("devices_dark"))
        step(0.5, lambda: (sim.terminate(), self.stop()))

        def run(i=0):
            if i < len(steps):
                d, fn = steps[i]

                def go(dt):
                    try:
                        fn()
                    except Exception:
                        import traceback
                        traceback.print_exc()
                    run(i + 1)
                Clock.schedule_once(go, d)
        run()


try:
    CIApp().run()
finally:
    sim.terminate()
