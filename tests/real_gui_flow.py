import os, sys, subprocess, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); OUT = os.environ.get("OUT", "/tmp")
sys.path.insert(0, ROOT)
import tkinter as tk
from tkinter import messagebox, filedialog
import bacnet_explorer as BE
import auth as AU
def shot(root, name):
    root.update(); time.sleep(0.4); root.update()
    subprocess.run(["import", "-window", "root", os.path.join(OUT, name)]); print("shot", name, flush=True)

if os.environ.get("BASIL_RESTART_TOKEN"):          # ---- second process, started by Restart
    root = tk.Tk()
    ok = BE.login(root)
    print("RESTARTED, login skipped:", ok, flush=True)
    if ok:
        app = BE.ExplorerApp(root)
        root.after(2500, lambda: (shot(root, "after_restart.png"), app.on_exit()))
        root.mainloop()
    sys.exit(0)

messagebox.askyesno = lambda *a, **k: True
messagebox.showinfo = lambda *a, **k: None
cfg = {"local_ip": "127.0.0.1", "port": 47851, "broadcast": "127.255.255.255", "remote_port": 47809,
       "timeout": 2.0, "retries": 1, "use_bbmd": False, "bbmd": "", "bbmd_ip": "", "bbmd_port": 47808,
       "ttl": 900, "discover_on_start": False}
BE.ChannelDialog = lambda parent, settings: type("D", (), {"show": lambda self: cfg})()
xlsx = os.path.join(OUT, "online_report.xlsx")
filedialog.asksaveasfilename = lambda **k: xlsx
written = []
class FakeWrite:                                   # stand-in for the write dialog: capture + answer
    def __init__(self, root, oid, prop, current, st, commandable, *a, **k):
        written.append((str(oid), current, commandable))
    def show(self): return (BE.X.Real(42.0), 8, None)
sim = subprocess.Popen([sys.executable, "bacnet_simulator.py", "--port", "47809"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
root = tk.Tk()
def do_login():
    scr = next(w for w in root.winfo_children() if isinstance(w, AU.LoginScreen))
    shot(root, "login_screen.png")
    scr.pw.insert(0, "wrong"); scr.submit(); print("wrong password msg:", scr.msg.cget("text"), flush=True)
    scr.pw.insert(0, "Basil@12345"); scr.remember.set(False); scr.submit()
root.after(800, do_login)
ok = BE.login(root); print("login ok:", ok, flush=True)
root.geometry("2400x1300+-8+-8")                   # simulate a too-big saved size ...
app = BE.ExplorerApp(root)                          # ... ExplorerApp must clamp it to the screen
steps = []
def step(d, fn): steps.append((d, fn))
step(300, lambda: print("window geometry:", root.geometry(), "screen", root.winfo_screenwidth(), flush=True))
step(100, app.start_channel)
step(500, lambda: (app.settings.__setitem__("whois_target_tuple", ["127.0.0.1", 47809]), app.quick_whois()))
def sub():
    app.dev_tree.selection_set(app.dev_iid[3001]); app.on_device_select()
step(2500, sub)
def subscribe():
    dev = app.client.devices[3001]
    app._subscribe_one(app.client, dev, BE.ObjectId(1, 1), "Cooling Valve",
                       {"sub_mode": "cov", "sub_confirmed": False, "sub_lifetime": 60, "poll_interval": 1,
                        "sub_fallback": True})
step(2500, subscribe)
def write_from_sub():
    BE.WriteDialog = FakeWrite
    iid = next(iter(app.sub_tree.get_children())); app.sub_tree.selection_set(iid)
    app.write_subscription()
step(2000, write_from_sub)
step(2500, lambda: print("written:", written, "sub value now:",
                         [app.sub_tree.set(i, "value") for i in app.sub_tree.get_children()], flush=True))
def hide(): app.toggle_devices(False)
step(200, hide); step(800, lambda: shot(root, "devices_hidden.png"))
step(200, lambda: app.toggle_devices(True))
step(200, app.online_report)
def scan():
    app._report.whois.set(False); app._report.start(True)
step(800, scan)
def wait_scan():
    if app._report.running: root.after(300, wait_scan); return
    shot(app._report, "report.png")
    print("summary:", app._report._summary_text(), flush=True)
    app._report.export(); print("xlsx exists:", os.path.exists(xlsx), flush=True)
    root.after(500, lambda: (app._report.close(), app._restart(keep_login=True), sim.terminate()))
step(500, wait_scan)
def run(i=0):
    if i >= len(steps): return
    d, fn = steps[i]
    def go():
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
        run(i + 1)
    root.after(d, go)
run(); root.mainloop()
print("first process ended", flush=True)
