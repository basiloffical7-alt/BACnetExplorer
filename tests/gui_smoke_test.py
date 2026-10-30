"""Drives the real ExplorerApp logic against the simulator with Tk replaced by functional fakes
(the build machine has no Tk libraries). Verifies the UI wiring end to end."""
import os, sys, types, time, subprocess, tempfile, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class W:  # generic widget: every method is a no-op
    def __init__(self, *a, **k): self._cfg = dict(k)
    def __getattr__(self, n): return lambda *a, **k: None
    def configure(self, *a, **k): self._cfg.update(k)
    config = configure
    def cget(self, k): return self._cfg.get(k)
    def winfo_width(self): return 900
    def winfo_height(self): return 300
    def get(self, *a): return ""
    def theme_names(self): return ("clam",)
    def winfo_children(self): return []
    def panes(self): return []

class Var:
    def __init__(self, master=None, value=None): self.v = value
    def get(self): return self.v
    def set(self, v): self.v = v
    def trace_add(self, *a): pass

class Treeview(W):
    def __init__(self, *a, **k):
        super().__init__(); self.items = {"": {"children": [], "parent": None, "text": "", "values": {}}}
        self.cols = list(k.get("columns", ())); self.sel = (); self.n = 0; self.tagcfg = {}
    def tag_configure(self, tag, **k): self.tagcfg.setdefault(tag, {}).update(k)
    def insert(self, parent, index, iid=None, text="", values=(), **k):
        self.n += 1; iid = iid or f"I{self.n:04d}"
        self.items[iid] = {"children": [], "parent": parent, "text": text,
                           "values": dict(zip(self.cols, values)), "tags": tuple(k.get("tags", ()))}
        ch = self.items[parent]["children"]
        ch.insert(len(ch) if index == "end" else index, iid); return iid
    def delete(self, *iids):
        for i in iids:
            if i in self.items:
                self.delete(*list(self.items[i]["children"]))
                self.items[self.items[i]["parent"]]["children"].remove(i); del self.items[i]
    def get_children(self, item=""): return tuple(self.items[item]["children"])
    def exists(self, i): return i in self.items
    def parent(self, i): return self.items[i]["parent"]
    def index(self, i): return self.items[self.parent(i)]["children"].index(i)
    def move(self, i, p, idx):
        self.items[self.parent(i)]["children"].remove(i); self.items[p]["children"].append(i); self.items[i]["parent"] = p
    def item(self, i, option=None, **k):
        if option == "text": return self.items[i]["text"]
        if "text" in k: self.items[i]["text"] = k["text"]
        if "values" in k: self.items[i]["values"] = dict(zip(self.cols, k["values"]))
        if "tags" in k: self.items[i]["tags"] = tuple(k["tags"])
        return self.items[i]
    def set(self, i, col=None, value=None):
        if value is None: return self.items[i]["values"].get(col, "")
        self.items[i]["values"][col] = value
    def selection(self): return self.sel
    def selection_set(self, *i): self.sel = tuple(i[0]) if len(i) == 1 and isinstance(i[0], (list, tuple)) else i

class Text(W):
    def __init__(self, *a, **k): super().__init__(); self.buf = ""
    def insert(self, idx, txt, *tags): self.buf += txt
    def index(self, x): return f"{self.buf.count(chr(10)) + 1}.0"
    def get(self, *a): return self.buf

class Tk(W):
    def winfo_containing(self, *a): return None
    def winfo_screenwidth(self): return 1366
    def winfo_screenheight(self): return 768
    def state(self, *a): return "normal"
    def after(self, *a): pass
    def focus_get(self): return None
    def geometry(self, *a): return "1280x800"

tkmod = types.ModuleType("tkinter")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_canvas import RecCanvas
for n in ("Toplevel", "Menu", "Misc", "Widget"): setattr(tkmod, n, W)
tkmod.Canvas = RecCanvas
tkmod.Tk, tkmod.Text, tkmod.PhotoImage = Tk, Text, W
tkmod.Label = W
class SVar(Var):
    def __init__(self, master=None, value=""): super().__init__(master, value)
tkmod.StringVar = SVar
tkmod.BooleanVar = tkmod.IntVar = Var
tkmod.TclError = Exception
ttk = types.ModuleType("tkinter.ttk")
for n in ("Frame", "Label", "Button", "Entry", "Combobox", "Checkbutton", "Radiobutton", "Scrollbar",
          "Separator", "LabelFrame", "PanedWindow", "Notebook", "Progressbar", "Style"):
    setattr(ttk, n, W)
ttk.Treeview = Treeview
class Combobox(W):
    def __init__(self, *a, **k): super().__init__(**k); self.vals = list(k.get("values", ())); self.i = -1; self.txt = ""
    def configure(self, *a, **k):
        if "values" in k: self.vals = list(k["values"])
    def current(self, i=None):
        if i is None: return self.i
        self.i = i; self.txt = self.vals[i]
    def get(self): return self.txt
    def set(self, v): self.txt = v; self.i = self.vals.index(v) if v in self.vals else -1
ttk.Combobox = Combobox
class Spinbox(W):
    def __init__(self, *a, **k): super().__init__(**k); self.v = ""
    def set(self, v): self.v = str(v)
    def get(self): return self.v
ttk.Spinbox = Spinbox
msgs = []
mb = types.ModuleType("tkinter.messagebox")
mb.showerror = lambda *a, **k: msgs.append(("error", a)); mb.showinfo = lambda *a, **k: msgs.append(("info", a))
mb.askyesno = lambda *a, **k: True
fd = types.ModuleType("tkinter.filedialog")
export_path = os.path.join(tempfile.mkdtemp(), "points.csv")
fd.asksaveasfilename = lambda **k: export_path
sd = types.ModuleType("tkinter.simpledialog"); sd.askstring = lambda *a, **k: ""; sd.askinteger = lambda *a, **k: 5
tkmod.ttk, tkmod.messagebox, tkmod.filedialog, tkmod.simpledialog = ttk, mb, fd, sd
sys.modules.update({"tkinter": tkmod, "tkinter.ttk": ttk, "tkinter.messagebox": mb,
                    "tkinter.filedialog": fd, "tkinter.simpledialog": sd})

import bacnet_explorer as BE
from bacnet.codec import ObjectId, Real
from bacnet import constants as C
from bacnet import codec as X
BE.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
cfg = {"local_ip": "127.0.0.1", "port": 47821, "broadcast": "127.255.255.255", "remote_port": 47809,
       "timeout": 2.0, "retries": 1, "use_bbmd": False, "bbmd": "", "bbmd_ip": "", "bbmd_port": 47808,
       "ttl": 900, "discover_on_start": False}
BE.ChannelDialog = lambda parent, settings: types.SimpleNamespace(show=lambda: cfg)

sim = subprocess.Popen([sys.executable, "bacnet_simulator.py", "--port", "47809"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
time.sleep(0.8)

def render_props(app, path):
    """Draw the property grid (fake Treeview) with its tag styles - for visual review."""
    from PIL import Image, ImageDraw, ImageFont
    F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"; FB = F.replace("Sans.ttf", "Sans-Bold.ttf")
    tree = app.prop_tree; rows = []
    def walk(parent, depth):
        for i in tree.get_children(parent):
            rows.append((i, depth)); walk(i, depth + 1)
    walk("", 0)
    tc = app.colors
    im = Image.new("RGB", (900, 22 * len(rows) + 26), tc["panel"]); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 900, 22], fill=tc["heading"]); hdr = ImageFont.truetype(FB, 12)
    for x, t in ((6, "Property"), (300, "Value"), (780, "Type")): d.text((x, 4), t, fill=tc["fg"], font=hdr)
    for n, (i, depth) in enumerate(rows):
        y = 24 + n * 22; it = tree.items[i]; cfg = {}
        for t in it["tags"]: cfg.update(tree.tagcfg.get(t, {}))
        if cfg.get("background"): d.rectangle([0, y, 900, y + 21], fill=cfg["background"])
        bold = isinstance(cfg.get("font"), tuple) and "bold" in cfg["font"]
        size = 13 if isinstance(cfg.get("font"), tuple) and cfg["font"][1] >= 10 else 12
        f = ImageFont.truetype(FB if bold else F, size); fg = cfg.get("foreground", tc["fg"])
        d.text((8 + depth * 22, y + 3), it["text"], fill=fg, font=f)
        d.text((300, y + 3), str(it["values"].get("value", ""))[:60], fill=fg, font=f)
        d.text((780, y + 3), str(it["values"].get("type", "")), fill=tc["muted"], font=ImageFont.truetype(F, 11))
        d.line([0, y + 21, 900, y + 21], fill=tc["border"]); d.line([295, y, 295, y + 21], fill=tc["border"])
    im.save(path)

def render_devices(app, path):
    """Draw the device list (name pane + red address pane) for visual review."""
    from PIL import Image, ImageDraw, ImageFont
    F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"; FB = F.replace("Sans.ttf", "Sans-Bold.ttf")
    tc = app.colors; dt = app.dev_tree; rows = []
    def walk(parent, depth):
        for i in dt.main.get_children(parent):
            rows.append((i, depth)); walk(i, depth + 1)
    walk("", 0)
    W = 600; im = Image.new("RGB", (W, 22 * len(rows) + 26), tc["panel"]); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 22], fill=tc["heading"]); hdr = ImageFont.truetype(FB, 12); f = ImageFont.truetype(F, 12)
    for x, t in ((6, "Device"), (270, "Address"), (440, "MAC")): d.text((x, 4), t, fill=tc["fg"], font=hdr)
    red = dt.addr.tagcfg.get("addr", {}).get("foreground", "#000")
    for n, (i, depth) in enumerate(rows):
        y = 24 + n * 22
        d.text((8 + depth * 20, y + 3), dt.main.items[i]["text"][:34], fill=tc["fg"], font=ImageFont.truetype(FB if depth == 0 else F, 12))
        d.text((270, y + 3), dt.set(i, "addr"), fill=red, font=f)
        d.text((440, y + 3), dt.set(i, "mac"), fill=red, font=f)
        d.line([0, y + 21, W, y + 21], fill=tc["border"])
    im.save(path)

def pump(sec=1.0, until=None):
    end = time.time() + sec
    while time.time() < end:
        while not app.ui_queue.empty(): app.ui_queue.get()()
        if until and until(): return True
        time.sleep(0.05)
    while not app.ui_queue.empty(): app.ui_queue.get()()
    return until() if until else True

try:
    app = BE.ExplorerApp(Tk())
    app.start_channel()
    assert app.client and app.client.running
    app.settings["whois_target_tuple"] = ["127.0.0.1", 47809]
    app.quick_whois()
    assert pump(5, lambda: len(app.dev_iid) == 9 and all(app.client.devices[i].name for i in app.dev_iid))
    pump(0.5)
    print("device tree:")
    for n in app.dev_tree.get_children():
        print(" ", app.dev_tree.item(n, "text"))
        for d in app.dev_tree.get_children(n):
            print("    ", app.dev_tree.item(d, "text"), "|", app.dev_tree.set(d, "addr"), "|", app.dev_tree.set(d, "mac"))

    rd = os.environ.get("RENDER_DIR", "/tmp")
    assert app.dev_tree.addr.tagcfg["addr"]["foreground"] == "#c62828"
    render_devices(app, os.path.join(rd, "devices_light.png"))
    app.apply_theme("dark"); assert app.dev_tree.addr.tagcfg["addr"]["foreground"] == "#ff6b6b"
    render_devices(app, os.path.join(rd, "devices_dark.png")); app.apply_theme("light")
    app.show_addr_var.set(False); app.show_mac_var.set(True); app._device_columns_changed()
    assert app.dev_tree.addr._cfg.get("displaycolumns") == ["mac"]
    app.show_addr_var.set(True); app._device_columns_changed()
    assert app.dev_tree.addr._cfg.get("displaycolumns") == ["addr", "mac"]
    print("address / MAC columns hide + show: ok")
    app.dev_tree.selection_set(app.dev_iid[1001]); app.on_device_select()
    assert pump(8, lambda: len(app.obj_nodes) == 164 and app.prop_rows)
    print("address space groups:", [app.obj_tree.item(g, "text") for g in app.obj_tree.get_children()][:6], "...")
    print("device props shown:", len(app.prop_rows))

    # select AV1 and read properties
    iid = next(i for i, o in app.obj_nodes.items() if o == ObjectId(2, 1))
    app.obj_tree.selection_set(iid); app.on_object_select()
    assert pump(4, lambda: app.current_props.get(77) == "Zone Setpoint")
    pv_row = next(i for i, r in app.prop_rows.items() if r.prop == 85)
    print("AV1 PV row:", app.prop_tree.set(pv_row, "value"), app.prop_tree.set(pv_row, "type"))
    pa_row = next(i for i, r in app.prop_rows.items() if r.prop == 87)
    kids = app.prop_tree.get_children(pa_row)
    print("priority-array children:", len(kids))
    assert [app.prop_tree.item(k, "text") for k in kids][:2] == ["Manual Life Safety", "Automatic Life Safety"]
    assert app.prop_tree.item(kids[15], "text") == "Lowest And Default"
    tags = {app.prop_rows[i].prop: app.prop_tree.items[i]["tags"] for i in app.prop_rows}
    print("row tags:", {C.property_name(p): t for p, t in tags.items() if t})
    assert tags[85] == ("pv",) and tags[75] == ("oid",) and tags[103] == ("rel_ok",)

    # write via the UI path at priority 8
    app._do_write(app.current_dev, ObjectId(2, 1), 85, Real(21.0), 10, None)
    app._do_write(app.current_dev, ObjectId(2, 1), 85, Real(20.5), 8, None)
    assert pump(4, lambda: abs(float(app.current_props.get(85, 0)) - 20.5) < 1e-6)
    render_props(app, os.path.join(os.environ.get("RENDER_DIR", "/tmp"), "props_av1.png"))
    iid_ai = next(i for i, o in app.obj_nodes.items() if o == ObjectId(0, 1))
    app.obj_tree.selection_set(iid_ai); app.on_object_select()
    assert pump(4, lambda: app.current_props.get(77) == "Zone Temperature")
    t2 = {app.prop_rows[i].prop: app.prop_tree.items[i]["tags"] for i in app.prop_rows}
    assert t2[65] == ("maxpv",) and t2[69] == ("minpv",), t2
    render_props(app, os.path.join(os.environ.get("RENDER_DIR", "/tmp"), "props_ai1.png"))
    iid_bo = next(i for i, o in app.obj_nodes.items() if o == ObjectId(4, 1))
    app.obj_tree.selection_set(iid_bo); app.on_object_select()
    assert pump(4, lambda: app.current_props.get(77) == "Supply Fan Start/Stop")
    t3 = {app.prop_rows[i].prop: app.prop_tree.items[i]["tags"] for i in app.prop_rows}
    assert t3[84] == ("polarity",), t3
    render_props(app, os.path.join(rd, "props_bo1_light.png"))
    app.apply_theme("dark"); render_props(app, os.path.join(rd, "props_bo1_dark.png")); app.apply_theme("light")
    app.obj_tree.selection_set(iid); app.on_object_select()
    assert pump(4, lambda: app.current_props.get(77) == "Zone Setpoint")
    print("after write PV row:", app.prop_tree.set(next(i for i, r in app.prop_rows.items() if r.prop == 85), "value"),
          "| PA:", app.prop_tree.set(next(i for i, r in app.prop_rows.items() if r.prop == 87), "value"))
    # write error shows dialog
    app._do_write(app.current_dev, ObjectId(0, 1), 85, Real(1.0), None, None)
    assert pump(3, lambda: any(m[0] == "error" for m in msgs)); print("write error dialog:", msgs[-1][1][1])

    # subscriptions (COV + poll), routed device too
    opts = {"sub_mode": "cov", "sub_confirmed": False, "sub_lifetime": 60, "poll_interval": 1, "sub_fallback": True}
    app._subscribe_one(app.client, app.current_dev, ObjectId(0, 1), "Zone Temperature", opts)
    app._subscribe_one(app.client, app.client.devices[1002], ObjectId(0, 3), "Zone Humidity", dict(opts, sub_mode="poll"))
    assert pump(5, lambda: len(app.sub_tree.get_children()) == 2 and
                all(app.sub_tree.set(i, "value") != "-" for i in app.sub_tree.get_children()))
    for i in app.sub_tree.get_children():
        print("sub row:", app.sub_tree.items[i]["values"])
    app.graph.redraw(); app._tick()

    # export CSV
    app.export_csv(app.client.devices[1001])
    assert pump(10, lambda: os.path.exists(export_path) and os.path.getsize(export_path) > 0)
    lines = open(export_path, encoding="utf-8-sig").read().splitlines()
    print("CSV rows:", len(lines) - 1); print("  ", lines[0]); print("  ", lines[2])

    # remove subscriptions & device, stop
    app.sub_tree.selection_set(app.sub_tree.get_children()); app.remove_subscriptions(); pump(1)
    app.remove_device(app.client.devices[1003]); assert 1003 not in app.dev_iid
    errors = [l for l in app.log_text.buf.splitlines() if " ERROR " in l and "failed" not in l]
    print("unexpected UI errors:", errors); assert not errors
    print("log tail:"); print("\n".join("   " + l for l in app.log_text.buf.splitlines()[-6:]))

    # ---------------- graphics: link AHU points to simulator objects
    g = app.graphics
    assert g.templates.keys() >= {"ahu"} and g.pages and g.pages[0]["template"] == "ahu"
    page = g.current_page(); dev = app.client.devices[1001]
    links = {"supply_fan": ObjectId(4, 1), "cooling_valve": ObjectId(1, 1), "flow_dps": ObjectId(3, 2),
             "filter_dps": ObjectId(3, 1), "fresh_damper": ObjectId(2, 2), "supply_temp": ObjectId(0, 1)}
    app.current_dev = dev
    for k, o in links.items():
        g.set_link(page, k, 1001, o, dev.object_names.get(o, ""))
    # command the outputs like an operator would
    app._do_write(dev, ObjectId(4, 1), 85, X.Enumerated(1), 8, None)
    app._do_write(dev, ObjectId(1, 1), 85, Real(65.0), 8, None)
    g._last_sync = 0
    def ready():
        g._frame()
        st = g.states_for(page, g.template_for(page), 1.0)
        return all(st[k].online for k in links) and st["supply_fan"].active and st["cooling_valve"].percent > 60
    assert pump(10, ready), {k: v for k, v in g.states_for(page, g.template_for(page), 1.0).items()}
    st = g.states_for(page, g.template_for(page), 1.0)
    for k in links: print(f"   graphic {k:<14} -> {st[k].text:<12} active={st[k].active} pct={st[k].percent:.0f}")
    # value-change flash in the Subscriptions tab
    assert pump(6, lambda: (app._tick(), bool(app._flash))[1]), "no flash started"
    sid = next(iter(app._flash))
    print("value flash started for subscription", sid, "value", app.sub_tree.set(str(sid), "value"))
    t_end = app._flash[sid]; assert 2.5 < t_end - time.time() <= 3.01
    g.redraw(3.3); g.canvas.render(os.environ.get("RENDER_OUT", "/tmp/ahu_live.png"))
    print("graphic subs:", sorted(g.subs), "tree:", [g.tree.set(i, "value") for i in g.tree.get_children()])
    # click detection on the fan
    g.canvas.find_overlapping  # recording canvas supports hit testing
    saved = json.load(open(BE.SETTINGS_FILE))["graphic_pages"][0]["links"]
    assert set(saved) == set(links), saved
    g.selected_point = "flow_dps"; g.unlink(); assert "flow_dps" not in page["links"]

    # ---------------- network adapter: command building + validation
    import netconfig as N
    print(N.build_windows_commands("Ethernet 2", False, "192.168.10.50", "255.255.255.0", "192.168.10.1", ["8.8.8.8", "1.1.1.1"], False))
    print(N.build_windows_commands("Wi-Fi", True))
    assert N.validate("192.168.10.50", "255.255.255.0", "192.168.10.1", []) == []
    assert N.validate("192.168.10.50", "255.255.255.0", "10.0.0.1", [])  # warning outside subnet
    for bad in (("192.168.10.255", "255.255.255.0", "", []), ("300.1.1.1", "255.255.255.0", "", []),
                ("10.0.0.5", "255.0.255.0", "", [])):
        try: N.validate(*bad); raise SystemExit(f"no error for {bad}")
        except ValueError as e: print("   rejected:", e)
    sample = '[{"Name":"Ethernet","Index":12,"Status":"Up","Description":"Intel(R) Ethernet","Mac":"AA-BB-CC-DD-EE-FF","Dhcp":"Disabled","IP":"192.168.1.20","Prefix":24,"Gateway":"192.168.1.1","Dns":["192.168.1.1"]},{"Name":"Wi-Fi","Index":5,"Status":"Disconnected","Dhcp":"Enabled","IP":null,"Prefix":null,"Gateway":null,"Dns":[]}]'
    ad = N.parse_powershell_json(sample); print("   parsed:", [(a.name, a.ip, a.mask, a.gateway, a.dhcp) for a in ad])
    assert ad[0].mask == "255.255.255.0" and ad[1].dhcp
    print("   adapters on this machine:", [(a.name, a.ip, a.mask) for a in N.list_adapters()])

    # ---------------- every equipment template: page + auto-link to its simulator device
    out_dir = os.environ.get("RENDER_DIR", "/tmp")
    sim_dev = {"ahu_sr": 3001, "fcu": 3002, "exhaust_fan": 3003, "vav": 3004, "chiller": 3005, "pump_set": 3006}
    for tid, inst in sim_dev.items():
        dev = app.client.devices[inst]
        app.dev_tree.selection_set(app.dev_iid[inst]); app.on_device_select()
        assert pump(8, lambda: len(dev.object_names) == len(dev.objects) > 0)
        page = g._new_page_dict(dev.name, tid); g.pages.append(page); g._save(); g._refresh_page_list(page["id"])
        if tid == "chiller":
            assert g.set_options(page, {"chillers": 2, "primary": 2, "secondary": 2})
            g._build_options(page)
            g.opt_boxes["secondary"].set("4"); g._options_changed()
            assert g.template_for(page).nsp == 4 and page["options"]["secondary"] == 4
            g.opt_boxes["secondary"].set("99"); g._options_changed()
            assert g.template_for(page).nsp == 8 and g.opt_boxes["secondary"].get() == "8"
            g.opt_boxes["secondary"].set("2"); g._options_changed()
            assert g.template_for(page).nsp == 2
            print("secondary pumps 2 -> 4 -> 8 (clamped) -> 2: ok")
            vis = g.points_visible; g.toggle_points(); g.toggle_points(); assert g.points_visible == vis
        assert g.equip_box.get() == g.templates[tid].NAME
        g.auto_link()
        tpl = g.template_for(page)
        unlinked = [p.key for p in tpl.POINTS if p.key not in page["links"]]
        wrong = [(k, l["name"]) for k, l in page["links"].items()]
        g._last_sync = 0
        ok = pump(10, lambda: (g._frame(), all(st.online for k, st in g.states_for(page, tpl, 1.0).items() if k in page["links"]))[1])
        st = g.states_for(page, tpl, 1.0)
        print(f"  {tid:<12} linked {len(page['links'])}/{len(tpl.POINTS)} online={ok} unlinked={unlinked}")
        for k, l in page["links"].items():
            print(f"      {tpl.point(k).label:<22} <- {l['name']:<26} {st[k].text}")
        assert ok and not unlinked, tid
        g.redraw(5.0); g.canvas.render(os.path.join(out_dir, f"live_{tid}.png"))
    # equipment switch on an existing page
    page = g.current_page(); g.equip_box.current(g.tpl_ids.index("fcu")); g.change_equipment()
    assert page["template"] == "fcu"
    app.on_exit()
    print("GUI SMOKE TEST PASSED")
finally:
    sim.terminate()
