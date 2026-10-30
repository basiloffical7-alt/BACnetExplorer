"""
Walks through the Android app's screens (android/main.py) with the fake Kivy stand-in,
against the simulator over real UDP: login -> devices -> device -> write -> watch ->
graphics (auto-link, tap, draw) -> report + Excel -> settings (theme) -> logout.
"""
import os, sys, subprocess, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tests"), os.path.join(ROOT, "android"), ROOT]
import fake_kivy
fake_kivy.install()
from fake_kivy import CALLS, run_clock
import json

data = tempfile.mkdtemp()
os.environ["HOME"] = data
json.dump({"net": {"ip": "127.0.0.1", "broadcast": "127.255.255.255", "port": 47891,
                   "remote_port": 47809, "bbmd": ""}}, open(os.path.join(data, "settings.json"), "w"))
sim = subprocess.Popen([sys.executable, "bacnet_simulator.py", "--port", "47809"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
import main as M
import platform_android as PA
PA.network_info = lambda: ("127.0.0.1", 8, "127.255.255.255")

def pump(sec=1.0, until=None):
    end = time.time() + sec
    while time.time() < end:
        run_clock(1)
        if until and until():
            return True
        time.sleep(0.05)
    run_clock(1)
    return until() if until else True

def find(root, cls=None, text=None):
    for w in root.walk():
        if (cls is None or isinstance(w, cls)) and (text is None or text in str(getattr(w, "text", ""))):
            return w
    raise LookupError(text)

def popup():
    return CALLS["popups"][-1] if CALLS["popups"] else None

try:
    app = M.BasilApp()
    app.user_data_dir = data
    holder = app.build()
    login = holder.children[0]
    assert isinstance(login, M.LoginView)
    login.pw.text = "nope"; login.login(); print("wrong password:", login.msg.text)
    login.pw.text = "Basil@12345"; login.remember.active = True; login.login()
    assert app.core.auth.autologin_ok() and app.core.online, "login / connect failed"
    print("logged in, online:", app.core.client.local_ip, app.core.client.port)
    app.core.discover(("127.0.0.1", 47809))
    assert pump(5, lambda: len(app.core.devices()) == 9 and all(d.name for d in app.core.devices()))
    ds = app.screens["devices"]; ds.refresh()
    print("devices list:", [r["title"] for r in ds.rv.data][:4], "...", ds.count.text)
    ds.search.text = "chiller"; print("search 'chiller':", [r["title"] for r in ds.rv.data]); ds.search.text = ""
    # open AHU-SR device
    row = next(r for r in ds.rv.data if "3001" in r["title"]); row["on_tap"]("title", row)
    dv = app.screens["device"]; assert app.sm.current == "device"
    assert pump(8, lambda: len(dv.rv.data) == 17)
    print("device points:", [(r["sub"], r["title"], r["value"]) for r in dv.rv.data[:5]])
    dv.type_sp.text = "Analog"; print("filter Analog ->", len(dv.rv.data), "rows"); dv.type_sp.text = "All"
    # tap value of Cooling Valve -> write popup -> type -> WRITE
    r = next(r for r in dv.rv.data if r["title"] == "Cooling Valve"); r["on_tap"]("value", r)
    pop = popup(); field = find(pop, M.TextInput); field.text = "47.5"
    find(pop, M.Button, "WRITE").trigger()
    assert pump(4, lambda: popup() is None)
    print("after write:", next(x["value"] for x in dv.rv.data if x["title"] == "Cooling Valve"))
    # binary write: Supply Fan Command OFF via buttons
    r = next(r for r in dv.rv.data if r["title"] == "Supply Fan Command"); r["on_tap"]("value", r)
    find(popup(), M.Button, "INACTIVE").trigger(); assert pump(4, lambda: popup() is None)
    print("fan after OFF:", next(x["value"] for x in dv.rv.data if x["title"] == "Supply Fan Command"))
    # add to watch with '+'
    for name in ("Supply Fan Command", "Supply Air Temp", "CO2 Sensor"):
        r = next(r for r in dv.rv.data if r["title"] == name); r["on_tap"]("action", r)
    print("watch:", [w.name for w in app.core.watch])
    # open point screen
    r = next(r for r in dv.rv.data if r["title"] == "Supply Air Damper"); r["on_tap"]("title", r)
    ps = app.screens["point"]; assert app.sm.current == "point"
    assert pump(4, lambda: ps.big.text not in ("…", ""))
    print("point screen:", ps.big.text, "|", ps.state_lbl.text, "| rows:", len(ps.grid.children))
    assert app.go_back() and app.sm.current == "device"
    # watch tab: live + flash
    app.tab("watch"); ws = app.screens["watch"]
    assert pump(4, lambda: all(r["value"] not in ("-", "") for r in ws.rv.data))
    print("watch rows:", [(r["title"], r["value"]) for r in ws.rv.data])
    r = next(r for r in ws.rv.data if r["title"] == "Supply Fan Command"); r["on_tap"]("value", r)
    find(popup(), M.Button, "ACTIVE / ON").trigger(); assert pump(4, lambda: popup() is None)
    ws.refresh(); r = next(r for r in ws.rv.data if r["title"] == "Supply Fan Command")
    print("fan after ON (watch):", r["value"], "flashing bg:", "bg" in r); assert "bg" in r
    # graphics: new chiller page, options, auto-link, tap, draw
    app.tab("graphics"); gs = app.screens["graphics"]
    gs.model.add_page("Plant", "chiller"); gs.sync_controls()
    spins = [w for w in gs.opts.walk() if isinstance(w, M.Spinner)]
    spins[0].text = "2"; spins[1].text = "2"; spins[2].text = "2"
    print("chiller options:", gs.model.template().options, "points:", len(gs.model.template().POINTS))
    gs.auto_link(); find(popup(), M.RecycleView).data  # device chooser
    ch = next(r for r in find(popup(), M.RecycleView).data if "3005" in r["title"]); ch["on_tap"]("title", ch)
    assert pump(8, lambda: popup() is not None and "Link" in str(popup().title))
    find(popup(), M.Button, "Link all").trigger()
    print("auto-linked:", len(gs.model.page()["links"]))
    gs.model.sync(); pump(4, lambda: all(r["value"] not in ("", "waiting…") for r in gs.model.point_rows()))
    gs.gw.width, gs.gw.height = 360, 300; n0 = CALLS["instructions"]; gs.gw.redraw()
    print("graphic drawn with", CALLS["instructions"] - n0, "Kivy instructions")
    gs.tap_point("ch1_run"); print("tap Chiller 1 popup:", popup().title); find(popup(), M.Button, "Close").trigger()
    gs.points_list(); print("points list rows:", len(find(popup(), M.RecycleView).data)); popup().dismiss()
    gs.zoom_sp.text = "150%"; print("zoom 150% widget size:", gs.gw.size); gs.zoom_sp.text = "Fit"
    # report + excel
    app.tab("report"); rs = app.screens["report"]; rs.whois.active = False; rs.start(True)
    assert pump(40, lambda: not rs.running)
    print("report cards:", {k: v.text for k, v in rs.card_lbls.items()})
    rs.export(); print("export popup:", find(popup(), M.Label, "Saved").text.replace("\n", " ")); popup().dismiss()
    # settings: theme switch + persistence
    app.tab("settings"); app.set_theme("dark")
    print("theme now:", app.theme, "screen:", app.sm.current, "bg:", M.T["bg"])
    app.set_theme("light")
    # logout -> login screen, auto login off
    app.logout(); assert isinstance(holder.children[0], M.LoginView) and not app.core.auth.autologin_ok()
    app.on_stop()
    print("ANDROID UI WALKTHROUGH PASSED")
finally:
    sim.terminate()
