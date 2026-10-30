"""Drive the REAL Tk application (e.g. under xvfb-run) against the simulator and take screenshots.
   Env: TPL, DEV, OPTS, ZOOM, THEME=dark, FULL=1, SHOT, OUT."""
import os, sys, subprocess, time, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("OUT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp()           # fresh settings file
import tkinter as tk
from tkinter import messagebox
import bacnet_explorer as BE

messagebox.askyesno = lambda *a, **k: True
cfg = {"local_ip": "127.0.0.1", "port": 47841, "broadcast": "127.255.255.255", "remote_port": 47809,
       "timeout": 2.0, "retries": 1, "use_bbmd": False, "bbmd": "", "bbmd_ip": "", "bbmd_port": 47808,
       "ttl": 900, "discover_on_start": False}
BE.ChannelDialog = lambda parent, settings: type("D", (), {"show": lambda self: cfg})()

sim = subprocess.Popen([sys.executable, "bacnet_simulator.py", "--port", "47809"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.0)
root = tk.Tk()
root.geometry(os.environ.get("GEOM", "1440x900+0+0"))
app = BE.ExplorerApp(root)
if os.environ.get("THEME") == "dark":
    app.apply_theme("dark")
steps = []
def step(delay, fn): steps.append((delay, fn))
def shot(name):
    root.update(); time.sleep(0.3); root.update()
    subprocess.run(["import", "-window", "root", os.path.join(OUT, name)], check=False)
    print("screenshot", name, flush=True)

step(300, lambda: app.start_channel())
step(500, lambda: (app.settings.__setitem__("whois_target_tuple", ["127.0.0.1", 47809]), app.quick_whois()))
def pick(inst):
    iid = app.dev_iid.get(inst)
    if iid: app.dev_tree.selection_set(iid); app.on_device_select()
step(2500, lambda: pick(int(os.environ.get("DEV", "3001"))))
step(3000, lambda: app._show_graphics())
def make_page():
    g = app.graphics
    tid = os.environ.get("TPL", "ahu_sr")
    page = g._new_page_dict(app.current_dev.name, tid); g.pages.append(page); g._save(); g._refresh_page_list(page["id"])
    opts = os.environ.get("OPTS")
    if opts:
        import json; g.set_options(page, json.loads(opts)); g._build_options(page)
    g.auto_link()
step(800, make_page)
def zoom():
    z = os.environ.get("ZOOM")
    if z: app.graphics.zoom_box.set(z); app.graphics._zoom_changed()
step(4000, zoom)
step(800, lambda: shot(os.environ.get("SHOT", "real_graphics.png")))
if os.environ.get("FLASH"):
    def flash_shots():
        # wait until a value cell is blinking, then take two frames (both blink phases)
        if not app._flash_labels or not any(l.winfo_ismapped() for l in app._flash_labels.values()):
            root.after(100, flash_shots); return
        shot("flash1.png"); root.after(260, lambda: shot("flash2.png"))
    step(100, flash_shots)
    step(1500, lambda: None)
if os.environ.get("FULL"):
    step(200, lambda: app.toggle_full_view())
    step(1200, lambda: shot("full_" + os.environ.get("SHOT", "real_graphics.png")))
    step(200, lambda: app.toggle_full_view())
    step(800, lambda: shot("restored_" + os.environ.get("SHOT", "real_graphics.png")))
step(300, lambda: (sim.terminate(), root.destroy()))

def run(i=0):
    if i >= len(steps): return
    d, fn = steps[i]
    def go():
        try: fn()
        except Exception as e: print("STEP ERROR", i, repr(e), flush=True)
        run(i + 1)
    root.after(d, go)
run()
root.mainloop()
