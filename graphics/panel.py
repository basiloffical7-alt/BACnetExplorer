"""
Graphics tab: animated equipment pages whose elements are linked to BACnet points.

Links are stored in the settings file as (device instance, object type, instance) so they
survive restarts and reconnect automatically when the device is discovered again.
"""
from __future__ import annotations

import re
import time
import tkinter as tk
import uuid
from tkinter import messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Type

from bacnet import codec as X
from bacnet import constants as C
from bacnet.codec import ObjectId
from graphics import load_templates
from graphics.base import Drawer, GraphicTemplate, PointState

if TYPE_CHECKING:  # pragma: no cover
    from bacnet.client import BACnetClient, Subscription

LinkKey = Tuple[int, int, int]   # device instance, object type, object instance

UNIT_SHORT = {62: "°C", 64: "°F", 98: "%", 29: "%RH", 53: "Pa", 54: "kPa", 55: "bar", 58: "inH2O",
              56: "psi", 84: "cfm", 85: "m³/s", 87: "l/s", 88: "l/min", 89: "gpm", 96: "ppm",
              104: "rpm", 27: "Hz", 47: "W", 48: "kW", 19: "kWh"}


def interpret(value: Any, oid: ObjectId, link: Dict[str, Any], units: Any,
              state_text: Optional[List[str]] = None) -> PointState:
    """Turn a raw BACnet value into a PointState for drawing."""
    st = PointState(linked=True, value=value, online=value is not None)
    if value is None:
        st.text = "waiting…"
        return st
    invert = bool(link.get("invert", False))
    threshold = float(link.get("threshold", 1.0))
    binary_like = oid.type in C.BINARY_TYPES or isinstance(value, (bool, X.Enumerated))
    if binary_like:
        st.active = int(value) == 1
        st.text = X.format_value(value, oid.type, C.PROP_PRESENT_VALUE)
        if oid.type in C.BINARY_TYPES or isinstance(value, bool):
            st.text = "ACTIVE" if int(value) == 1 else "INACTIVE"
    elif oid.type in C.MULTISTATE_TYPES:
        st.active = int(value) > 1
        n = int(value)
        st.text = state_text[n - 1] if state_text and 0 < n <= len(state_text) else f"state {n}"
    elif isinstance(value, (int, float)):
        v = float(value)
        st.is_analog = True
        st.percent = max(0.0, min(100.0, v))
        st.active = v > threshold
        u = UNIT_SHORT.get(int(units)) if units is not None else None
        fmt = f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}"
        st.text = f"{fmt} {u}" if u else (fmt if abs(v) >= 100 else f"{v:.2f}")
    else:
        st.text = X.format_plain(value)[:20]
    if invert:
        st.active = not st.active
        if st.is_analog:
            st.percent = 100.0 - st.percent
    if not st.is_analog:
        st.percent = 100.0 if st.active else 0.0
    return st


class OptionsDialog(tk.Toplevel):
    def __init__(self, parent, title: str, link: Dict[str, Any]):
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result: Optional[Dict[str, Any]] = None
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        self.invert = tk.BooleanVar(value=bool(link.get("invert", False)))
        ttk.Checkbutton(f, text="Invert (active when the point is inactive / reverse %)",
                        variable=self.invert).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Analog 'active' above:").grid(row=1, column=0, sticky="w", pady=6)
        self.thr = ttk.Entry(f, width=10)
        self.thr.insert(0, str(link.get("threshold", 1.0)))
        self.thr.grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="Analog values are treated as 0-100 % for valves, dampers and fan speed.",
                  foreground="#777777").grid(row=2, column=0, columnspan=2, sticky="w")
        b = ttk.Frame(self, padding=(12, 0, 12, 12))
        b.pack(fill="x")
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="OK", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window()

    def _ok(self):
        try:
            thr = float(self.thr.get())
        except ValueError:
            messagebox.showerror("Invalid", "Threshold must be a number", parent=self)
            return
        self.result = {"invert": self.invert.get(), "threshold": thr}
        self.destroy()


class GraphicsPanel(ttk.Frame):
    FRAME_MS = 50

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.templates, errors = load_templates()
        for e in errors:
            app.log("error", e)
        self.t0 = time.time()
        self.selected_point: Optional[str] = None
        self.subs: Dict[LinkKey, int] = {}
        self.pending: Set[LinkKey] = set()
        self._last_sync = 0.0
        self._last_list = 0.0

        pages = app.settings.get("graphic_pages")
        if not isinstance(pages, list) or not pages:
            pages = [self._new_page_dict("AHU-01", "ahu")] if "ahu" in self.templates else []
            app.settings["graphic_pages"] = pages
        self.pages: List[Dict[str, Any]] = pages
        self.instances: Dict[str, GraphicTemplate] = {}
        self._migrate_links()

        self._build()
        self._refresh_page_list(select=app.settings.get("graphic_page_current"))
        self.after(self.FRAME_MS, self._frame)

    # ------------------------------------------------------------------ UI
    def _build(self):
        # ---- row 1: page and equipment
        bar = ttk.Frame(self, padding=(2, 3, 2, 0))
        bar.pack(fill="x")
        ttk.Label(bar, text="Page:").pack(side="left", padx=(2, 4))
        self.page_box = ttk.Combobox(bar, state="readonly", width=24)
        self.page_box.pack(side="left")
        self.page_box.bind("<<ComboboxSelected>>", lambda e: self._page_changed())
        ttk.Button(bar, text="New…", command=self.new_page, width=6).pack(side="left", padx=(4, 1))
        ttk.Button(bar, text="Rename…", command=self.rename_page, width=8).pack(side="left", padx=1)
        ttk.Button(bar, text="Delete", command=self.delete_page, width=7).pack(side="left", padx=1)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(bar, text="Equipment:").pack(side="left", padx=(0, 4))
        self.tpl_ids = sorted(self.templates, key=lambda i: self.templates[i].NAME)
        self.equip_box = ttk.Combobox(bar, state="readonly", width=22,
                                      values=[self.templates[i].NAME for i in self.tpl_ids])
        self.equip_box.pack(side="left")
        self.equip_box.bind("<<ComboboxSelected>>", lambda e: self.change_equipment())
        ttk.Button(bar, text="Auto-link…", command=self.auto_link).pack(side="left", padx=(4, 1))

        # ---- row 2: equipment options (number of chillers / pumps), zoom, demo, points list
        bar2 = ttk.Frame(self, padding=(2, 2, 2, 3))
        bar2.pack(fill="x")
        self.opt_frame = ttk.Frame(bar2)            # per-equipment options (e.g. number of chillers)
        self.opt_frame.pack(side="left")
        self.opt_boxes: Dict[str, Any] = {}
        self.points_btn = ttk.Button(bar2, text="Points list ▸", width=13,
                                     command=self.toggle_points)
        self.points_btn.pack(side="right", padx=(4, 2))
        self.full_btn = ttk.Button(bar2, text="Full view", width=12,
                                   command=lambda: self.app.toggle_full_view())
        self.full_btn.pack(side="right", padx=(4, 0))
        self.demo = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar2, text="Demo", variable=self.demo).pack(side="right", padx=4)
        zooms = ["Zoom Fit", "Zoom 50%", "Zoom 75%", "Zoom 100%", "Zoom 125%", "Zoom 150%"]
        self.zoom_box = ttk.Combobox(bar2, state="readonly", width=10, values=zooms)
        z = str(self.app.settings.get("graphic_zoom", "Zoom Fit"))
        self.zoom_box.set(z if z in zooms else "Zoom Fit")
        self.zoom_box.bind("<<ComboboxSelected>>", lambda e: self._zoom_changed())
        self.zoom_box.pack(side="right", padx=(6, 0))

        # ---- body: drawing | points list
        self.pw = pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True)
        cframe = ttk.Frame(pw)
        pw.add(cframe, weight=4)
        self.canvas = tk.Canvas(cframe, background=self._bg(), highlightthickness=0, cursor="hand2")
        self.hbar = ttk.Scrollbar(cframe, orient="horizontal", command=self.canvas.xview)
        self.vbar = ttk.Scrollbar(cframe, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        cframe.rowconfigure(0, weight=1)
        cframe.columnconfigure(0, weight=1)
        self._bars_shown = (False, False)
        self.canvas.bind("<Shift-MouseWheel>",
                         lambda e: self.canvas.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))   # Linux
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        self.side = side = ttk.Frame(pw, width=360)
        self.points_visible = bool(self.app.settings.get("graphic_points_list", True))
        if self.points_visible:
            pw.add(side, weight=1)
        self._sash_done = False
        pw.bind("<Configure>", self._place_sash, add="+")
        # the frame must exist BEFORE the tree: a widget packed into a frame created after it
        # is hidden behind that frame (Tk stacking order) - the cause of the empty points list
        tframe = ttk.Frame(side)
        tframe.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tframe, columns=("link", "value"), show="tree headings",
                                 selectmode="browse", height=8)
        self.tree.heading("#0", text="Graphic point")
        self.tree.heading("link", text="Linked BACnet object")
        self.tree.heading("value", text="Value")
        self.tree.column("#0", width=130, minwidth=90)
        self.tree.column("link", width=140, minwidth=80)
        self.tree.column("value", width=80, minwidth=60)
        self.tree.tag_configure("unlinked", foreground="#9e9e9e")
        tbar = ttk.Scrollbar(tframe, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tbar.pack(side="right", fill="y")
        btns = ttk.Frame(side, padding=(0, 4))
        btns.pack(fill="x")
        ttk.Button(btns, text="⇐ Link selected object", command=self.link_selected).grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=1)
        ttk.Button(btns, text="Unlink", command=self.unlink).grid(row=1, column=0, sticky="ew",
                                                                  padx=(0, 1))
        ttk.Button(btns, text="Options…", command=self.options).grid(row=1, column=1, sticky="ew",
                                                                     padx=(1, 0))
        ttk.Button(btns, text="Write value…", command=self.command).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=1)
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        self.help = ttk.Label(side, text="Tip: drag an object from the address space onto an "
                              "element of the drawing to link it.", wraplength=340,
                              foreground="#777777", justify="left")
        self.help.pack(fill="x", pady=(4, 0))
        self._update_points_btn()

        self.tree.bind("<<TreeviewSelect>>", self._tree_select)
        self.tree.bind("<Double-1>", self._tree_double)
        self.tree.bind("<Button-3>", self._tree_menu)
        self.canvas.bind("<Button-1>", self._canvas_click)
        self.canvas.bind("<Button-3>", self._canvas_menu)
        self.canvas.bind("<Double-1>", lambda e: self.command())

    # ------------------------------------------------------------------ pages
    def _migrate_links(self):
        """Templates may rename points (LEGACY_KEYS); keep old pages' links working."""
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
                new = legacy.get(old)
                link = links.pop(old)
                if new and new in valid and new not in links:
                    links[new] = link

    def _new_page_dict(self, name: str, template: str) -> Dict[str, Any]:
        return {"id": uuid.uuid4().hex[:8], "name": name, "template": template, "links": {}}

    def current_page(self) -> Optional[Dict[str, Any]]:
        i = self.page_box.current()
        return self.pages[i] if 0 <= i < len(self.pages) else None

    def template_for(self, page: Dict[str, Any]) -> Optional[GraphicTemplate]:
        if page["id"] not in self.instances:
            cls = self.templates.get(page["template"])
            if cls is None:
                return None
            self.instances[page["id"]] = cls(page.get("options"))
        return self.instances[page["id"]]

    # ------------------------------------------------------------------ equipment options
    def _build_options(self, page: Optional[Dict[str, Any]]):
        for w in self.opt_frame.winfo_children():
            w.destroy()
        self.opt_boxes = {}
        tpl = self.template_for(page) if page else None
        if not tpl or not tpl.OPTIONS:
            return
        for name, (label, lo, hi, _default) in tpl.OPTIONS.items():
            ttk.Label(self.opt_frame, text=label).pack(side="left", padx=(8, 3))
            box = ttk.Spinbox(self.opt_frame, from_=lo, to=hi, width=3, wrap=False,
                              command=self._options_changed)
            box.set(str(tpl.options[name]))
            box.bind("<Return>", lambda e: self._options_changed())
            box.bind("<FocusOut>", lambda e: self._options_changed())
            box.pack(side="left")
            self.opt_boxes[name] = box

    def _options_changed(self):
        page = self.current_page()
        if not page:
            return
        new: Dict[str, int] = {}
        for name, box in self.opt_boxes.items():
            try:
                new[name] = int(str(box.get()).strip())
            except (TypeError, ValueError):
                pass
        tpl = self.template_for(page)
        if tpl is not None and all(tpl.options.get(k) == v for k, v in new.items()):
            return
        self.set_options(page, new)
        tpl = self.template_for(page)
        if tpl is not None:          # show the value actually used (clamped to min / max)
            for name, box in self.opt_boxes.items():
                if str(box.get()) != str(tpl.options.get(name)):
                    box.set(str(tpl.options.get(name)))

    def set_options(self, page: Dict[str, Any], new_opts: Dict[str, int]) -> bool:
        """Change e.g. the number of chillers / pumps of a page. Asks before dropping links."""
        cls = self.templates.get(page["template"])
        if cls is None:
            return False
        inst = cls({**(page.get("options") or {}), **new_opts})
        valid = {p.key for p in inst.POINTS}
        lost = [k for k in page["links"] if k not in valid]
        if lost:
            old = self.template_for(page)
            labels = {p.key: p.label for p in old.POINTS} if old else {}
            names = ", ".join(str(labels.get(k) or k) for k in lost[:8]) + (" …" if len(lost) > 8 else "")
            if not messagebox.askyesno("Remove equipment",
                                       f"{len(lost)} linked point(s) will be unlinked:\n\n{names}"
                                       "\n\nContinue?", parent=self):
                self._build_options(page)      # put the spin boxes back
                return False
            for k in lost:
                del page["links"][k]
        page["options"] = dict(inst.options)
        self.instances[page["id"]] = inst
        self._save()
        self._cleanup_subscriptions()
        self._fill_tree()
        return True

    def _refresh_page_list(self, select: Optional[str] = None):
        names = []
        for p in self.pages:
            tpl = self.templates.get(p["template"])
            names.append(f"{p['name']}   ({tpl.NAME if tpl else 'missing: ' + p['template']})")
        self.page_box.configure(values=names)
        idx = 0
        for k, p in enumerate(self.pages):
            if p["id"] == select:
                idx = k
        if self.pages:
            self.page_box.current(idx)
        else:
            self.page_box.set("")
        self._page_changed()

    def _page_changed(self):
        page = self.current_page()
        self.app.settings["graphic_page_current"] = page["id"] if page else None
        if page and page["template"] in self.tpl_ids:
            self.equip_box.current(self.tpl_ids.index(page["template"]))
        else:
            self.equip_box.set("")
        self._build_options(page)
        self.selected_point = None
        self._fill_tree()

    def _save(self):
        self.app.settings["graphic_pages"] = self.pages
        self.app.save()

    def new_page(self):
        if not self.templates:
            messagebox.showwarning("Graphics", "No graphic templates found in the graphics folder.",
                                   parent=self)
            return
        win = tk.Toplevel(self)
        win.title("New graphic page")
        win.transient(self.winfo_toplevel())
        f = ttk.Frame(win, padding=12)
        f.pack(fill="both", expand=True)
        ids = list(self.templates)
        ttk.Label(f, text="Equipment template").grid(row=0, column=0, sticky="w", pady=3)
        box = ttk.Combobox(f, state="readonly", width=34,
                           values=[self.templates[i].NAME for i in ids])
        box.current(0)
        box.grid(row=0, column=1, sticky="ew")
        ttk.Label(f, text="Page name").grid(row=1, column=0, sticky="w", pady=3)
        name = ttk.Entry(f, width=36)
        name.insert(0, f"{self.templates[ids[0]].TEMPLATE_ID.upper()}-{len(self.pages) + 1:02d}")
        name.grid(row=1, column=1, sticky="ew")
        desc = ttk.Label(f, text=self.templates[ids[0]].DESCRIPTION, foreground="#777777",
                         wraplength=320)
        desc.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        box.bind("<<ComboboxSelected>>",
                 lambda e: desc.configure(text=self.templates[ids[box.current()]].DESCRIPTION))

        def ok():
            nm = name.get().strip() or "Page"
            page = self._new_page_dict(nm, ids[box.current()])
            self.pages.append(page)
            self._save()
            self._refresh_page_list(page["id"])
            win.destroy()
        b = ttk.Frame(win, padding=(12, 0, 12, 12))
        b.pack(fill="x")
        ttk.Button(b, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(b, text="Create", command=ok).pack(side="right", padx=6)
        win.bind("<Return>", lambda e: ok())
        win.bind("<Escape>", lambda e: win.destroy())
        try:
            win.wait_visibility()
            win.grab_set()
        except tk.TclError:
            pass

    def rename_page(self):
        page = self.current_page()
        if not page:
            return
        nm = simpledialog.askstring("Rename page", "New name:", initialvalue=page["name"],
                                    parent=self)
        if nm and nm.strip():
            page["name"] = nm.strip()
            self._save()
            self._refresh_page_list(page["id"])

    def delete_page(self):
        page = self.current_page()
        if not page:
            return
        if not messagebox.askyesno("Delete page", f"Delete graphic page '{page['name']}' and its "
                                   f"{len(page['links'])} link(s)?", parent=self):
            return
        self.pages.remove(page)
        self.instances.pop(page["id"], None)
        self._cleanup_subscriptions()
        self._save()
        self._refresh_page_list()

    def change_equipment(self):
        """Switch the current page to another equipment type."""
        page = self.current_page()
        i = self.equip_box.current()
        if i < 0:
            return
        new_id = self.tpl_ids[i]
        if page is None:
            page = self._new_page_dict(f"{new_id.upper()}-{len(self.pages) + 1:02d}", new_id)
            self.pages.append(page)
            self._save()
            self._refresh_page_list(page["id"])
            return
        if page["template"] == new_id:
            return
        new_keys = {p.key for p in self.templates[new_id]().POINTS}
        lost = [k for k in page["links"] if k not in new_keys]
        if lost and not messagebox.askyesno(
                "Change equipment", f"Change '{page['name']}' to {self.templates[new_id].NAME}?\n\n"
                f"{len(lost)} linked point(s) do not exist on the new equipment and will be "
                "unlinked.\n\nTip: use 'New page…' to keep this page and add another.", parent=self):
            self._page_changed()
            return
        for k in lost:
            del page["links"][k]
        page["template"] = new_id
        page["options"] = {}
        self.instances.pop(page["id"], None)
        self._save()
        self._cleanup_subscriptions()
        self._refresh_page_list(page["id"])

    # ------------------------------------------------------------------ auto-link
    @staticmethod
    def _tokens(name: str) -> List[str]:
        name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)      # SupplyFan -> Supply Fan
        return [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w]

    def suggest_links(self, page: Dict[str, Any], names: Dict[ObjectId, str]
                      ) -> List[Tuple[str, ObjectId, str]]:
        tpl = self.template_for(page)
        if not tpl:
            return []
        objs = [(o, n, self._tokens(n)) for o, n in names.items() if n and o.type != C.OBJ_DEVICE]
        used = {(int(l["device"]), int(l["object"][0]), int(l["object"][1]))
                for l in page["links"].values()}
        cands = []
        for gp in tpl.POINTS:
            if gp.key in page["links"]:
                continue
            patterns = gp.match or [gp.label]
            for pi, pat in enumerate(patterns):
                words = self._tokens(pat)
                for o, n, toks in objs:
                    if all(w in toks for w in words):
                        score = pi * 10 + len(toks) - len(words)
                        binary_obj = o.type in C.BINARY_TYPES or o.type in C.MULTISTATE_TYPES
                        if (gp.kind == "binary") != binary_obj and gp.kind != "any":
                            score += 25
                        cands.append((score, gp.key, o, n))
        cands.sort(key=lambda c: c[0])
        taken_pts: Set[str] = set()
        taken_objs: Set[ObjectId] = set()
        out = []
        for score, key, o, n in cands:
            if key in taken_pts or o in taken_objs:
                continue
            taken_pts.add(key)
            taken_objs.add(o)
            out.append((key, o, n))
        return out

    def auto_link(self):
        page = self.current_page()
        dev = self.app.current_dev
        if not page:
            return
        if dev is None or not dev.object_names:
            messagebox.showinfo("Auto-link", "Select the equipment's device in the Devices tree first "
                                "(its object names must be loaded).", parent=self)
            return
        tpl = self.template_for(page)
        sugg = self.suggest_links(page, dev.object_names)
        if not sugg:
            messagebox.showinfo("Auto-link", f"No matching object names found in device "
                                f"{dev.instance} for the unlinked points.", parent=self)
            return
        labels = {p.key: p.label for p in tpl.POINTS} if tpl else {}
        lines = "\n".join(f"  {labels.get(k, k):<22} ←  {o.short}  {n}" for k, o, n in sugg)
        missing = [labels[p.key] for p in (tpl.POINTS if tpl else [])
                   if p.key not in page["links"] and p.key not in {k for k, _, _ in sugg}]
        msg = (f"Link these points to device {dev.instance} '{dev.name}'?\n\n{lines}" +
               (f"\n\nNo match for: {', '.join(missing)}" if missing else ""))
        if not messagebox.askyesno("Auto-link", msg, parent=self):
            return
        for k, o, n in sugg:
            old = page["links"].get(k, {})
            page["links"][k] = {"device": dev.instance, "object": [o.type, o.instance], "name": n,
                                "invert": old.get("invert", False), "threshold": old.get("threshold", 1.0)}
        self.app.log("info", f"Graphic '{page['name']}': auto-linked {len(sugg)} point(s) to device "
                             f"{dev.instance}")
        self._save()
        self._cleanup_subscriptions()
        self._fill_tree()
        self._last_sync = 0

    # ------------------------------------------------------------------ linking
    @staticmethod
    def link_key(link: Dict[str, Any]) -> LinkKey:
        return int(link["device"]), int(link["object"][0]), int(link["object"][1])

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        page = self.current_page()
        tpl = self.template_for(page) if page else None
        if not page or not tpl:
            self.help.configure(text="This page's template file is missing from the graphics folder."
                                if page else "Create a page with 'New page…'.")
            return
        for gp in tpl.POINTS:
            link = page["links"].get(gp.key)
            txt = self._link_text(link) if link else "— not linked —"
            self.tree.insert("", "end", iid=gp.key, text=gp.label, values=(txt, ""),
                             tags=() if link else ("unlinked",))
        if self.selected_point and self.tree.exists(self.selected_point):
            self.tree.selection_set(self.selected_point)

    @staticmethod
    def _link_text(link: Dict[str, Any]) -> str:
        oid = ObjectId(int(link["object"][0]), int(link["object"][1]))
        nm = link.get("name") or ""
        flags = " (inv)" if link.get("invert") else ""
        return f"{link['device']} {oid.short} {nm}{flags}"

    def _select_point(self, key: Optional[str]):
        self.selected_point = key
        if key and self.tree.exists(key):
            if self.tree.selection() != (key,):
                self.tree.selection_set(key)
            self.tree.see(key)
            page = self.current_page()
            tpl = self.template_for(page) if page else None
            if tpl:
                gp = tpl.point(key)
                self.help.configure(text=f"{gp.label}: {gp.help}")

    def _tree_select(self, event=None):
        sel = self.tree.selection()
        if sel:
            self._select_point(sel[0])

    def link_selected(self, key: Optional[str] = None, oid: Optional[ObjectId] = None):
        key = key or self.selected_point
        page = self.current_page()
        if not page or not key:
            messagebox.showinfo("Graphics", "Select a graphic point (in the list or by clicking "
                                "the drawing) first.", parent=self)
            return
        dev = self.app.current_dev
        if oid is None:
            objs = [o for o in self.app.selected_objects() if o.type != C.OBJ_DEVICE]
            if not objs and self.app.current_obj is not None and self.app.current_obj.type != C.OBJ_DEVICE:
                objs = [self.app.current_obj]
            oid = objs[0] if objs else None
        if dev is None or oid is None:
            messagebox.showinfo("Graphics", "Select a device and then a BACnet object in the "
                                "Address space, then press 'Link selected object' "
                                "(or drag the object onto the drawing).", parent=self)
            return
        self.set_link(page, key, dev.instance, oid, dev.object_names.get(oid, ""))

    def set_link(self, page: Dict[str, Any], key: str, device: int, oid: ObjectId, name: str):
        old = page["links"].get(key, {})
        page["links"][key] = {"device": device, "object": [oid.type, oid.instance], "name": name,
                              "invert": old.get("invert", False),
                              "threshold": old.get("threshold", 1.0)}
        tpl = self.template_for(page)
        label = tpl.point(key).label if tpl else key
        self.app.log("info", f"Graphic '{page['name']}': {label} linked to device {device} "
                             f"{oid} {name}")
        self._save()
        self._cleanup_subscriptions()
        self._fill_tree()
        self._select_point(key)
        self._last_sync = 0  # subscribe right away

    def drop_object(self, x_root: int, y_root: int, oid: ObjectId) -> bool:
        """Called by the main window when an object is dragged from the address space."""
        page = self.current_page()
        if not page or self.app.current_dev is None:
            return False
        key = None
        w = self.winfo_toplevel().winfo_containing(x_root, y_root)
        if w is self.canvas:
            key = self._point_at(self.canvas.canvasx(x_root - self.canvas.winfo_rootx()),
                                 self.canvas.canvasy(y_root - self.canvas.winfo_rooty()))
        elif w is self.tree:
            row = self.tree.identify_row(y_root - self.tree.winfo_rooty())
            key = row or None
        if not key:
            return False
        self.set_link(page, key, self.app.current_dev.instance, oid,
                      self.app.current_dev.object_names.get(oid, ""))
        return True

    def unlink(self):
        page, key = self.current_page(), self.selected_point
        if page and key and key in page["links"]:
            del page["links"][key]
            self._save()
            self._cleanup_subscriptions()
            self._fill_tree()
            self._select_point(key)

    def options(self):
        page, key = self.current_page(), self.selected_point
        if not page or not key or key not in page["links"]:
            messagebox.showinfo("Graphics", "Select a linked point first.", parent=self)
            return
        res = OptionsDialog(self, "Point options", page["links"][key]).result
        if res:
            page["links"][key].update(res)
            self._save()
            self._fill_tree()

    def command(self):
        page, key = self.current_page(), self.selected_point
        cl = self.app.client
        if not page or not key or key not in page["links"]:
            messagebox.showinfo("Graphics", "Select a linked point first.", parent=self)
            return
        if cl is None:
            messagebox.showinfo("Graphics", "Open a BACnet/IP channel first.", parent=self)
            return
        k = self.link_key(page["links"][key])
        dev = cl.devices.get(k[0])
        if dev is None:
            messagebox.showinfo("Graphics", f"Device {k[0]} has not been discovered yet.",
                                parent=self)
            return
        sub = cl.subscriptions.get(self.subs.get(k, -1))
        self.app.open_write_dialog(dev, ObjectId(k[1], k[2]), sub.value if sub else None)

    # ------------------------------------------------------------------ canvas events
    def _point_at(self, x: float, y: float) -> Optional[str]:
        items = self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)
        for it in reversed(items):
            for tag in self.canvas.gettags(it):
                if tag.startswith("pt:") and len(tag) > 3:
                    return tag[3:]
        return None

    def _canvas_click(self, event):
        key = self._point_at(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if key:
            self._select_point(key)

    def _canvas_menu(self, event):
        key = self._point_at(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if key:
            self._select_point(key)
            self._popup(event)

    def _goto_selected(self):
        page, key = self.current_page(), self.selected_point
        link = page["links"].get(key) if page and key else None
        if link:
            k = self.link_key(link)
            self.app.goto_object(k[0], ObjectId(k[1], k[2]))

    def _tree_double(self, event):
        """Double-click: Value -> write in place; point / object name -> go to the point in the
        address space (highlighted 3 s); not linked -> link the selected object."""
        key = self.tree.identify_row(event.y)
        if not key:
            return
        self._select_point(key)
        col = self.tree.identify_column(event.x)
        page = self.current_page()
        link = page["links"].get(key) if page else None
        if not link:
            self.link_selected(key)
            return "break"
        k = self.link_key(link)
        oid = ObjectId(k[1], k[2])
        if col == "#2":                                   # value column
            cl = self.app.client
            dev = cl.devices.get(k[0]) if cl else None
            if dev is None:
                messagebox.showinfo("Graphics", f"Device {k[0]} has not been discovered yet.",
                                    parent=self)
                return "break"
            sub = cl.subscriptions.get(self.subs.get(k, -1)) if cl else None
            self.app.inline_write(self.tree, key, "value", dev, oid, sub.value if sub else None)
        else:
            self.app.goto_object(k[0], oid)
        return "break"

    def _tree_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self._select_point(row)
            self._popup(event)

    def _popup(self, event):
        m = tk.Menu(self, tearoff=False)
        m.add_command(label="Write value…", command=self.command)
        m.add_command(label="Go to point in address space", command=self._goto_selected)
        m.add_separator()
        m.add_command(label="Link selected address-space object", command=self.link_selected)
        m.add_command(label="Unlink", command=self.unlink)
        m.add_command(label="Options (invert / threshold)…", command=self.options)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    # ------------------------------------------------------------------ subscriptions
    def all_links(self):
        for page in self.pages:
            for key, link in page["links"].items():
                yield page, key, link

    def _sync_subscriptions(self):
        cl: Optional["BACnetClient"] = self.app.client
        if cl is None or not cl.running:
            self.subs.clear()
            self.pending.clear()
            return
        for page, key, link in self.all_links():
            k = self.link_key(link)
            sid = self.subs.get(k)
            if k in self.pending or (sid is not None and sid in cl.subscriptions):
                continue
            dev = cl.devices.get(k[0])
            if dev is None:
                continue
            self.pending.add(k)
            oid = ObjectId(k[1], k[2])
            label = f"[Graphic] {link.get('name') or oid.short}"
            self.app.pool.submit(self._subscribe_worker, cl, dev, oid, k, label)

    def _subscribe_worker(self, cl, dev, oid: ObjectId, k: LinkKey, label: str):
        try:
            if (dev.instance, oid) not in self.app.units_cache and oid.type in C.ANALOG_TYPES:
                try:
                    self.app.units_cache[(dev.instance, oid)] = cl.read_property(
                        dev.address, oid, C.PROP_UNITS)
                except Exception:
                    self.app.units_cache[(dev.instance, oid)] = None
            if oid.type in C.MULTISTATE_TYPES and (dev.instance, oid, "st") not in self.app.units_cache:
                try:
                    txt = cl.read_property(dev.address, oid, C.PROP_STATE_TEXT)
                    self.app.units_cache[(dev.instance, oid, "st")] = [str(x) for x in txt] \
                        if isinstance(txt, list) else None
                except Exception:
                    self.app.units_cache[(dev.instance, oid, "st")] = None
            sub = cl.add_subscription(dev, oid, False, 300, True, cl.refresh_interval, name=label)
            sub.graph = False

            def done():
                self.subs[k] = sub.sub_id
                self.pending.discard(k)
                self.app._update_sub_row(sub)
            self.app.ui(done)
        except Exception as e:
            self.app.log("warning", f"Graphic link {k[0]} {oid}: {e}")

            def failed():
                self.pending.discard(k)
            self.app.ui(failed)

    def _cleanup_subscriptions(self):
        """Remove graphic subscriptions that no page uses any more."""
        used = {self.link_key(l) for _, _, l in self.all_links()}
        cl = self.app.client
        for k in list(self.subs):
            if k not in used:
                sid = self.subs.pop(k)
                if cl and sid in cl.subscriptions:
                    if self.app.sub_tree.exists(str(sid)):
                        self.app.sub_tree.delete(str(sid))
                    self.app.pool.submit(cl.remove_subscription, sid)

    # ------------------------------------------------------------------ animation
    def states_for(self, page: Dict[str, Any], tpl: GraphicTemplate, t: float) -> Dict[str, PointState]:
        cl = self.app.client
        states: Dict[str, PointState] = {}
        for gp in tpl.POINTS:
            if self.demo.get():
                val, analog = tpl.demo_value(gp.key, t)
                if analog:
                    st = PointState(value=val, is_analog=True, percent=max(0.0, min(100.0, val)),
                                    active=val > 1.0, text=f"{val:.1f}")
                else:
                    st = PointState(value=val, active=bool(val), percent=100.0 if val else 0.0,
                                    text="ACTIVE" if val else "INACTIVE")
                st.override = True
                st.online = True
                link = page["links"].get(gp.key)
                st.linked = link is not None
                states[gp.key] = st
                continue
            link = page["links"].get(gp.key)
            if not link:
                states[gp.key] = PointState()
                continue
            k = self.link_key(link)
            oid = ObjectId(k[1], k[2])
            sub: Optional["Subscription"] = None
            if cl is not None:
                sub = cl.subscriptions.get(self.subs.get(k, -1))
            value = sub.value if sub is not None and sub.last_update else None
            states[gp.key] = interpret(value, oid, link, self.app.units_cache.get((k[0], oid)),
                                       self.app.units_cache.get((k[0], oid, "st")))
        return states

    def _frame(self):
        try:
            now = time.time()
            if now - self._last_sync > 2.0:
                self._last_sync = now
                self._sync_subscriptions()
            if self.winfo_ismapped():
                self.redraw(now - self.t0)
        except Exception as e:  # never stop the animation loop
            self.app.log("error", f"Graphics: {e!r}")
        finally:
            self.after(self.FRAME_MS, self._frame)

    # ------------------------------------------------------------------ zoom / points list
    def _zoom(self) -> Optional[float]:
        z = self.zoom_box.get().replace("Zoom", "").strip()
        try:
            return float(z.rstrip("%")) / 100 if z and z != "Fit" else None
        except ValueError:
            return None

    def _zoom_changed(self):
        self.app.settings["graphic_zoom"] = self.zoom_box.get() or "Zoom Fit"
        self.app.save()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _update_points_btn(self):
        self.points_btn.configure(text="Points list ▸" if self.points_visible else "◂ Points list")

    def toggle_points(self):
        """Show / hide the list of graphic points on the right."""
        self.points_visible = not self.points_visible
        if self.points_visible:
            self.pw.add(self.side, weight=1)
            self._sash_done = False
            self.after(50, self._place_sash)
        else:
            self.pw.forget(self.side)
        self.app.settings["graphic_points_list"] = self.points_visible
        self.app.save()
        self._update_points_btn()

    def _place_sash(self, event=None):
        """Give the points list a usable width (~360 px) the first time the tab is laid out."""
        if self._sash_done or not self.points_visible:
            return
        w = self.pw.winfo_width()
        if w < 200:
            return
        try:
            self.pw.sashpos(0, max(int(w * 0.45), w - 380))
            self._sash_done = True
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ theme / scrolling
    def _dark(self) -> bool:
        return bool(getattr(self.app, "dark", False))

    def _bg(self) -> str:
        return "#1e2227" if self._dark() else "#ffffff"

    def apply_theme(self):
        self.canvas.configure(background=self._bg())

    def _update_scroll(self, d: Drawer):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        need_h, need_v = d.width_px > cw + 2, d.height_px > ch + 2
        self.canvas.configure(scrollregion=(0, 0, max(d.width_px, cw), max(d.height_px, ch)))
        if (need_h, need_v) != self._bars_shown:
            self._bars_shown = (need_h, need_v)
            if need_h:
                self.hbar.grid(row=1, column=0, sticky="ew")
            else:
                self.hbar.grid_remove()
                self.canvas.xview_moveto(0)
            if need_v:
                self.vbar.grid(row=0, column=1, sticky="ns")
            else:
                self.vbar.grid_remove()
                self.canvas.yview_moveto(0)

    def redraw(self, t: float):
        cv = self.canvas
        cv.delete("all")
        page = self.current_page()
        if not page:
            cv.create_text(cv.winfo_width() / 2, cv.winfo_height() / 2,
                           text="No graphic pages - click 'New page…'", fill="#888888")
            return
        tpl = self.template_for(page)
        if not tpl:
            cv.create_text(cv.winfo_width() / 2, cv.winfo_height() / 2, fill="#c62828",
                           text=f"Template '{page['template']}' not found in the graphics folder")
            return
        states = self.states_for(page, tpl, t)
        d = Drawer(cv, tpl.WIDTH, tpl.HEIGHT, highlight=self.selected_point, dark=self._dark(),
                   scale=self._zoom())
        d.text(10, 18, page["name"], 14, True, anchor="w")
        if self.demo.get():
            d.text(10, 40, "DEMO MODE", 9, True, "#ffa000", anchor="w")
        tpl.draw(d, states, t)
        self._update_scroll(d)
        if time.time() - self._last_list > 0.5:
            self._last_list = time.time()
            for gp in tpl.POINTS:
                if self.tree.exists(gp.key):
                    st = states[gp.key]
                    self.tree.set(gp.key, "value", st.text if (st.linked or st.override) else "")
