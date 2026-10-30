import os, sys, subprocess, time, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); OUT = os.environ.get("OUT", "/tmp")
sys.path.insert(0, ROOT); os.environ["HOME"] = tempfile.mkdtemp()
import tkinter as tk
from tkinter import messagebox
import bacnet_explorer as BE
messagebox.askyesno = lambda *a, **k: True
cfg = {"local_ip": "127.0.0.1", "port": 47861, "broadcast": "127.255.255.255", "remote_port": 47809,
       "timeout": 2.0, "retries": 1, "use_bbmd": False, "bbmd": "", "bbmd_ip": "", "bbmd_port": 47808,
       "ttl": 900, "discover_on_start": False}
BE.ChannelDialog = lambda parent, settings: type("D", (), {"show": lambda self: cfg})()
sim = subprocess.Popen([sys.executable, "bacnet_simulator.py", "--port", "47809"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
root = tk.Tk(); root.geometry("1366x740+0+0")
app = BE.ExplorerApp(root)
def shot(name, w=None):
    root.update(); time.sleep(0.3); root.update()
    subprocess.run(["import", "-window", "root", os.path.join(OUT, name)]); print("shot", name, flush=True)
def dclick(w, x, y):
    for _ in range(2):
        w.event_generate("<ButtonPress-1>", x=x, y=y); w.event_generate("<ButtonRelease-1>", x=x, y=y)
    root.update()
def row(oid_short):
    return next(i for i in app.sub_tree.get_children() if app.sub_tree.set(i, "object") == oid_short)
def click(widget, x, y, double=False):
    widget.event_generate("<Motion>", x=x, y=y); widget.event_generate("<ButtonPress-1>", x=x, y=y)
    widget.event_generate("<ButtonRelease-1>", x=x, y=y)
    if double:
        widget.event_generate("<Double-1>", x=x, y=y)
steps = []
def step(d, fn): steps.append((d, fn))
step(300, app.start_channel)
step(400, lambda: (app.settings.__setitem__("whois_target_tuple", ["127.0.0.1", 47809]), app.quick_whois()))
def drag_divider():
    m = app.dev_tree.main; pw = app.dev_tree.pw
    print("divider before:", pw.sashpos(0), "device col width", m.column("#0", "width"), flush=True)
    x0 = m.winfo_width() - 3
    m.event_generate("<Motion>", x=x0, y=10); print("cursor at edge:", m.cget("cursor"), flush=True)
    m.event_generate("<ButtonPress-1>", x=x0, y=10)
    for x in range(x0, x0 + 120, 20):
        m.event_generate("<B1-Motion>", x=x, y=10, state=0x100)
    m.event_generate("<ButtonRelease-1>", x=x0 + 120, y=10); root.update()
    print("divider after drag right:", pw.sashpos(0), "device col width", m.column("#0", "width"), flush=True)
step(2500, drag_divider)
step(300, lambda: shot("divider_dragged.png"))
def subscribe():
    dev = app.client.devices[3001]
    app.dev_tree.selection_set(app.dev_iid[3001]); app.on_device_select()
    for oid, nm in ((BE.ObjectId(1, 2), "Fresh Air Damper"), (BE.ObjectId(4, 1), "Supply Fan Command")):
        app._subscribe_one(app.client, dev, oid, nm, {"sub_mode": "cov", "sub_confirmed": False,
                           "sub_lifetime": 60, "poll_interval": 1, "sub_fallback": True})
step(800, subscribe)
def edit_value():
    t = app.sub_tree; iid = row("AO2")
    x, y, w, h = t.bbox(iid, "value")
    dclick(t, x + 10, y + 5)
    ed = app._inline_editor; print("editor opened:", type(ed).__name__, "with", repr(ed.get()), flush=True)
    ed.delete(0, "end"); ed.insert(0, "72.5")
    shot("inline_editor.png")
    ed.event_generate("<Return>")
step(2500, edit_value)
step(2500, lambda: print("value after Enter:", [app.sub_tree.set(i, "value") for i in app.sub_tree.get_children()], flush=True))
def edit_binary():
    t = app.sub_tree; iid = row("BO1")
    x, y, w, h = t.bbox(iid, "value")
    dclick(t, x + 10, y + 5)
    ed = app._inline_editor; print("binary editor:", type(ed).__name__, list(ed.cget("values")), flush=True)
    ed.set("1 - active"); ed.event_generate("<<ComboboxSelected>>")
step(300, edit_binary)
step(2500, lambda: print("values now:", [app.sub_tree.set(i, "value") for i in app.sub_tree.get_children()], flush=True))
def goto():
    app.dev_tree.selection_set(app.dev_iid[1001]); app.on_device_select()      # select another device first
step(300, goto)
def dbl_name():
    t = app.sub_tree; iid = row("AO2")
    x, y, w, h = t.bbox(iid, "name")
    dclick(t, x + 10, y + 5)
step(3000, dbl_name)
def check_goto():
    sel = (app._highlight_iid,) if app._highlight_iid else app.obj_tree.selection()
    print("now selected device:", app.current_dev.instance, "object:", [app.obj_nodes.get(i) for i in sel],
          "highlight tags:", app.obj_tree.item(sel[0], "tags") if sel else None, flush=True)
    shot("goto_highlight.png")
step(1500, check_goto)
step(3200, lambda: print("after 3 s: selected", [app.obj_nodes.get(i) for i in app.obj_tree.selection()], "tags", app.obj_tree.item(app.obj_tree.selection()[0], "tags"), flush=True))
step(200, lambda: (sim.terminate(), root.destroy()))
def run(i=0):
    if i >= len(steps): return
    d, fn = steps[i]
    def go():
        try: fn()
        except Exception:
            import traceback; traceback.print_exc()
        run(i + 1)
    root.after(d, go)
run(); root.mainloop()
