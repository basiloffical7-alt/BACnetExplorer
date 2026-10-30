"""
Login screen for the desktop application (logic lives in authcore.py, shared with Android).
"""
from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import ttk
from typing import Dict

from authcore import (DEFAULT_PASSWORD, DEFAULT_USER, ITERATIONS, LOCK_SECONDS, MAX_TRIES,  # noqa: F401
                      Auth, hash_password, machine_key)


class LoginScreen(ttk.Frame):
    """Login form shown inside the main window before the application is built."""

    def __init__(self, root: tk.Tk, auth: Auth, app_name: str, version: str, logo_path: str,
                 colors: Dict[str, str]):
        super().__init__(root, padding=28, style="Login.TFrame")
        self.root, self.auth = root, auth
        self.result = tk.BooleanVar(master=root, value=False)
        self.tries = 0
        self.locked_until = 0.0
        c = colors
        st = ttk.Style(root)
        if c.get("dark") == "1":
            st.theme_use("clam")
        for name, opts in (("Login.TFrame", {"background": c["bg"]}),
                           ("Login.TLabel", {"background": c["bg"], "foreground": c["fg"]}),
                           ("LoginTitle.TLabel", {"background": c["bg"], "foreground": c["fg"],
                                                  "font": ("Segoe UI", 16, "bold")}),
                           ("LoginHint.TLabel", {"background": c["bg"], "foreground": c["muted"]}),
                           ("LoginErr.TLabel", {"background": c["bg"], "foreground": "#e53935"}),
                           ("Login.TCheckbutton", {"background": c["bg"], "foreground": c["fg"]})):
            st.configure(name, **opts)
        root.configure(background=c["bg"])
        root.title(f"{app_name} - Login")
        self.logo = None
        try:
            if os.path.exists(logo_path):
                self.logo = tk.PhotoImage(master=root, file=logo_path)
        except tk.TclError:
            self.logo = None
        if self.logo is not None:
            ttk.Label(self, image=self.logo, style="Login.TLabel").grid(row=0, column=0, columnspan=2,
                                                                        pady=(0, 8))
        ttk.Label(self, text=app_name, style="LoginTitle.TLabel").grid(row=1, column=0, columnspan=2)
        ttk.Label(self, text=f"version {version}  ·  please sign in", style="LoginHint.TLabel").grid(
            row=2, column=0, columnspan=2, pady=(0, 16))
        ttk.Label(self, text="Username", style="Login.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        self.user = ttk.Entry(self, width=28)
        self.user.grid(row=3, column=1, pady=4)
        ttk.Label(self, text="Password", style="Login.TLabel").grid(row=4, column=0, sticky="w", pady=4)
        self.pw = ttk.Entry(self, width=28, show="•")
        self.pw.grid(row=4, column=1, pady=4)
        self.show = tk.BooleanVar(master=root, value=False)
        ttk.Checkbutton(self, text="Show password", variable=self.show, style="Login.TCheckbutton",
                        command=lambda: self.pw.configure(show="" if self.show.get() else "•")
                        ).grid(row=5, column=1, sticky="w")
        self.remember = tk.BooleanVar(master=root, value=False)
        ttk.Checkbutton(self, text="Remember me on this computer (auto login)",
                        variable=self.remember, style="Login.TCheckbutton").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.msg = ttk.Label(self, text="", style="LoginErr.TLabel")
        self.msg.grid(row=7, column=0, columnspan=2, pady=(8, 0))
        bar = ttk.Frame(self, style="Login.TFrame")
        bar.grid(row=8, column=0, columnspan=2, pady=(12, 0), sticky="ew")
        self.btn = ttk.Button(bar, text="Login", command=self.submit)
        self.btn.pack(side="right")
        ttk.Button(bar, text="Exit", command=root.destroy).pack(side="right", padx=6)
        self.pack(expand=True)
        root.bind("<Return>", lambda e: self.submit())
        root.update_idletasks()
        w, h = max(self.winfo_reqwidth() + 60, 420), self.winfo_reqheight() + 60
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
        root.resizable(False, False)
        self.user.insert(0, auth.record()["user"])
        self.pw.focus_set()

    def submit(self):
        now = time.time()
        if now < self.locked_until:
            self.msg.configure(text=f"Too many attempts - wait {int(self.locked_until - now) + 1} s")
            return
        if self.auth.check(self.user.get(), self.pw.get()):
            if self.remember.get():
                self.auth.enable_autologin()
            self.root.unbind("<Return>")
            self.root.resizable(True, True)
            self.result.set(True)
            return
        self.tries += 1
        self.pw.delete(0, "end")
        if self.tries >= MAX_TRIES:
            self.tries = 0
            self.locked_until = now + LOCK_SECONDS
            self.msg.configure(text=f"Too many attempts - locked for {LOCK_SECONDS} s")
            self.btn.configure(state="disabled")
            self.after(LOCK_SECONDS * 1000, lambda: (self.btn.configure(state="normal"),
                                                     self.msg.configure(text="")))
        else:
            self.msg.configure(text=f"Wrong username or password ({MAX_TRIES - self.tries} tries left)")
