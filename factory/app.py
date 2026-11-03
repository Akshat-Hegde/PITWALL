"""The factory window (spec 2.8, F8): a plain tkinter/ttk form. All the logic is in factory/controller.py (tested
without tkinter); this file only draws widgets, passes edits to the controller and shows what it returns.

Layout: a red key banner on top (until the signing key is made, known to the program and backed up); the cafe list
with a search box and New cafe on the left; the tabs Cafe, Rigs & games, Features, Branding & price on the right,
with each field's problems in red next to it; the buttons Preview, Build package, Issue upgrade, Rebuild all, Open
shipments folder and Settings; a progress bar with Cancel; the status bar.

Long jobs run in the controller's worker thread. This window never waits for them: `after()` polls the controller
every 100 ms, and only this (the Tk) thread touches widgets.

Started by "<product> Factory.cmd" in the repo root (`.venv\\Scripts\\pythonw -m factory`). Seller only: never
packaged for cafes. No network.
"""

from __future__ import annotations

import logging
import logging.handlers
import math
import os
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Callable

from simtelemetry import brand
from simtelemetry.provision import MAX_RIGS

from . import build
from .controller import NEW_KEY, POLL_MS, TABS, Controller, ControllerError, Notice

log = logging.getLogger(__name__)

TITLE = f"{brand.PRODUCT_NAME} Factory"
RED = "#B00020"
BANNER_BG = "#C62828"
PAD = 6
LOGO_BOX = 96                    # the logo preview fits in this many pixels
HOURS = [f"{h:02d}:00" for h in range(25)]


class FactoryApp:
    def __init__(self, root: tk.Tk, controller: Controller) -> None:
        self.root = root
        self.c = controller
        self._filling = False                      # True while the form is filled from the profile (no edits)
        self._logo_image: tk.PhotoImage | None = None
        self._last_sig: Any = None
        self._list_keys: list[str] = []
        self.vars: dict[str, tk.Variable] = {}
        self.problem_labels: dict[str, ttk.Label] = {}
        self.form_widgets: list[tk.Widget] = []

        root.title(TITLE)
        root.geometry("1180x780")
        root.minsize(960, 640)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.report_callback_exception = self._callback_error
        style = ttk.Style(root)
        style.configure("Problem.TLabel", foreground=RED)
        style.configure("Muted.TLabel", foreground="#555555")
        style.configure("Head.TLabel", font=("Segoe UI", 13, "bold"))

        self._build_banner()
        body = self.body = ttk.Panedwindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))
        body.add(self._build_list(body), weight=1)
        body.add(self._build_form(body), weight=4)
        self._build_bottom()

        self.refresh_all()
        root.after(POLL_MS, self._tick)

    # --- building the window ----------------------------------------------------------------------------------

    def _build_banner(self) -> None:
        self.banner = tk.Frame(self.root, bg=BANNER_BG)
        self.banner_text = tk.Label(self.banner, bg=BANNER_BG, fg="white", justify="left", anchor="w",
                                    font=("Segoe UI", 10, "bold"), wraplength=820)
        self.banner_text.pack(side="left", fill="x", expand=True, padx=PAD, pady=PAD)
        self.banner_buttons = tk.Frame(self.banner, bg=BANNER_BG)
        self.banner_buttons.pack(side="right", padx=PAD, pady=PAD)

    def _build_list(self, parent: tk.Widget) -> ttk.Frame:
        f = ttk.Frame(parent, padding=PAD)
        ttk.Label(f, text="Cafes", style="Head.TLabel").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(PAD, 0))
        ttk.Label(row, text="Search").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._on_search())
        ttk.Entry(row, textvariable=self.search_var).pack(side="left", fill="x", expand=True, padx=(PAD, 0))
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True, pady=PAD)
        self.listbox = tk.Listbox(box, activestyle="none", exportselection=False, height=20)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_list_select())
        self.new_btn = ttk.Button(f, text="New cafe", command=self.on_new)
        self.new_btn.pack(fill="x")
        return f

    def _build_form(self, parent: tk.Widget) -> ttk.Frame:
        f = ttk.Frame(parent, padding=PAD)
        head = ttk.Frame(f)
        head.pack(fill="x")
        self.cafe_title = ttk.Label(head, text="", style="Head.TLabel")
        self.cafe_title.pack(side="left")
        self.revert_btn = ttk.Button(head, text="Undo changes", command=self.on_revert)
        self.revert_btn.pack(side="right")
        self.save_btn = ttk.Button(head, text="Save", command=self.on_save)
        self.save_btn.pack(side="right", padx=PAD)

        self.nb = ttk.Notebook(f)
        self.nb.pack(fill="both", expand=True, pady=(PAD, 0))
        self.tabs: dict[str, ttk.Frame] = {}
        for name in TABS:
            tab = ttk.Frame(self.nb, padding=PAD * 2)
            self.nb.add(tab, text=name)
            self.tabs[name] = tab
        self._tab_cafe(self.tabs["Cafe"])
        self._tab_rigs(self.tabs["Rigs & games"])
        self._tab_features(self.tabs["Features"])
        self._tab_price(self.tabs["Branding & price"])
        self.empty = ttk.Label(f, text="Choose a cafe on the left, or press New cafe.", style="Muted.TLabel")
        return f

    # helpers for fields
    def _var(self, name: str, kind: type = tk.StringVar, on_change: Callable[[], None] | None = None,
             refill: bool = False) -> tk.Variable:
        v = kind()
        self.vars[name] = v
        if on_change is not None:
            v.trace_add("write", lambda *_: self._edit(on_change, refill=refill))
        return v

    @staticmethod
    def _set(var: tk.Variable, value: Any) -> None:
        """Set a field only when it differs, so refilling the form never moves the cursor of the field typed in."""
        try:
            same = var.get() == value
        except tk.TclError:
            same = False
        if not same:
            var.set(value)

    def _problem(self, parent: tk.Widget, fieldname: str, row: int, column: int = 1, columnspan: int = 3) -> None:
        lab = ttk.Label(parent, text="", style="Problem.TLabel", wraplength=560, justify="left")
        lab.grid(row=row, column=column, columnspan=columnspan, sticky="w")
        self.problem_labels[fieldname] = lab

    def _entry(self, parent: tk.Widget, row: int, label: str, var: tk.Variable, width: int = 40,
               show: str = "") -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        e = ttk.Entry(parent, textvariable=var, width=width, show=show)
        e.grid(row=row, column=1, columnspan=3, sticky="w", pady=2)
        self.form_widgets.append(e)
        return e

    def _tab_cafe(self, t: ttk.Frame) -> None:
        c = self.c
        self._entry(t, 0, "Cafe name", self._var("name", on_change=lambda: c.set_name(self.vars["name"].get())))
        self._problem(t, "name", 1)
        self._entry(t, 2, "Tagline (optional)",
                    self._var("tagline", on_change=lambda: c.set_tagline(self.vars["tagline"].get())), width=60)
        self._problem(t, "tagline", 3)

        ttk.Label(t, text="Logo (optional)").grid(row=4, column=0, sticky="nw", pady=2)
        logo = ttk.Frame(t)
        logo.grid(row=4, column=1, columnspan=3, sticky="w", pady=2)
        self.logo_image_label = ttk.Label(logo)
        self.logo_image_label.pack(side="left")
        self.logo_name = ttk.Label(logo, text="", style="Muted.TLabel")
        self.logo_name.pack(side="left", padx=PAD)
        b1 = ttk.Button(logo, text="Choose logo…", command=self.on_choose_logo)
        b1.pack(side="left", padx=PAD)
        b2 = ttk.Button(logo, text="Remove logo", command=lambda: self._edit(c.clear_logo, refill=True))
        b2.pack(side="left")
        self.form_widgets += [b1, b2]
        self._problem(t, "logo", 5)

        ttk.Label(t, text="Accent colour").grid(row=6, column=0, sticky="w", pady=2)
        acc = ttk.Frame(t)
        acc.grid(row=6, column=1, columnspan=3, sticky="w", pady=2)
        for colour in c.accent_swatches():
            b = tk.Button(acc, bg=colour, activebackground=colour, width=3, relief="raised",
                          command=lambda col=colour: self._edit(lambda: c.set_accent(col)))
            b.pack(side="left", padx=2)
            self.form_widgets.append(b)
        b = ttk.Button(acc, text="Other colour…", command=self.on_other_colour)
        b.pack(side="left", padx=PAD)
        self.form_widgets.append(b)
        self.accent_sample = tk.Label(acc, text="  current  ", relief="sunken")
        self.accent_sample.pack(side="left", padx=PAD)
        self._problem(t, "accent", 7)

        wifi = self._var("wifi_on", tk.BooleanVar, on_change=self._set_wifi)
        cb = ttk.Checkbutton(t, text="Guest Wi-Fi (shown to guests on their phones)", variable=wifi)
        cb.grid(row=8, column=0, columnspan=4, sticky="w", pady=(PAD, 2))
        self.form_widgets.append(cb)
        self.wifi_widgets = [
            self._entry(t, 9, "Wi-Fi name", self._var("ssid", on_change=self._set_wifi), width=32),
            self._entry(t, 10, "Wi-Fi password", self._var("wifi_pw", on_change=self._set_wifi), width=32),
        ]
        ttk.Label(t, text="Security").grid(row=11, column=0, sticky="w", pady=2)
        sec = ttk.Combobox(t, state="readonly", width=30, values=["WPA (with a password)", "Open (no password)"],
                           textvariable=self._var("wifi_sec", on_change=self._set_wifi))
        sec.grid(row=11, column=1, sticky="w", pady=2)
        self.wifi_widgets.append(sec)
        self.form_widgets.append(sec)
        self._problem(t, "wifi", 12)

        hours = self._var("hours_on", tk.BooleanVar, on_change=self._set_hours)
        cb = ttk.Checkbutton(t, text="Opening hours", variable=hours)
        cb.grid(row=13, column=0, columnspan=4, sticky="w", pady=(PAD, 2))
        self.form_widgets.append(cb)
        hrow = ttk.Frame(t)
        hrow.grid(row=14, column=1, columnspan=3, sticky="w")
        ttk.Label(t, text="Opens / closes").grid(row=14, column=0, sticky="w")
        o = ttk.Combobox(hrow, state="readonly", width=7, values=HOURS[:24],
                         textvariable=self._var("open", on_change=self._set_hours))
        o.pack(side="left")
        ttk.Label(hrow, text=" to ").pack(side="left")
        cl = ttk.Combobox(hrow, state="readonly", width=7, values=HOURS,
                          textvariable=self._var("close", on_change=self._set_hours))
        cl.pack(side="left")
        ttk.Label(hrow, text="  A cafe open past midnight can close at 01:00 to 06:00.",
                  style="Muted.TLabel").pack(side="left")
        self.hours_widgets = [o, cl]
        self.form_widgets += [o, cl]
        self._problem(t, "hours", 15)

        ttk.Label(t, text="Your contact at the cafe (your records only: never in the installer or the licence)",
                  style="Muted.TLabel").grid(row=16, column=0, columnspan=4, sticky="w", pady=(PAD * 2, 2))
        self._entry(t, 17, "Name", self._var("contact_name", on_change=lambda: c.set_contact(
            name=self.vars["contact_name"].get())), width=32)
        self._entry(t, 18, "Phone", self._var("contact_phone", on_change=lambda: c.set_contact(
            phone=self.vars["contact_phone"].get())), width=32)
        self._entry(t, 19, "City", self._var("contact_city", on_change=lambda: c.set_contact(
            city=self.vars["contact_city"].get())), width=32)
        self._problem(t, "contact", 20)
        self._problem(t, "cafe_id", 21, column=0, columnspan=4)

    def _tab_rigs(self, t: ttk.Frame) -> None:
        c = self.c
        ttk.Label(t, text="Rigs").grid(row=0, column=0, sticky="w")
        sp = ttk.Spinbox(t, from_=1, to=MAX_RIGS, width=6,
                         textvariable=self._var("rigs", on_change=lambda: c.set_rigs_text(self.vars["rigs"].get()),
                                                refill=True))
        sp.grid(row=0, column=1, sticky="w")
        self.form_widgets.append(sp)
        self._problem(t, "rigs", 1)
        ttk.Label(t, text="Rig names (optional; blank = Rig 1, Rig 2…; at most 16 characters)",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=4, sticky="w", pady=(PAD, 2))
        grid = ttk.Frame(t)
        grid.grid(row=3, column=0, columnspan=4, sticky="w")
        self.rig_entries: list[tuple[ttk.Label, ttk.Entry, tk.StringVar]] = []
        for i in range(MAX_RIGS):
            var = tk.StringVar()
            var.trace_add("write", lambda *_a, i=i, v=var: self._edit(lambda: c.set_rig_name(i, v.get())))
            lab = ttk.Label(grid, text=f"Rig {i + 1}")
            ent = ttk.Entry(grid, textvariable=var, width=20)
            self.rig_entries.append((lab, ent, var))
            self.form_widgets.append(ent)
        self._problem(t, "rig_names", 4, column=0, columnspan=4)
        ttk.Label(t, text="Games", style="Head.TLabel").grid(row=5, column=0, sticky="w", pady=(PAD * 2, 2))
        self.games_frame = ttk.Frame(t)
        self.games_frame.grid(row=6, column=0, columnspan=4, sticky="w")
        self.game_vars: dict[str, tk.BooleanVar] = {}
        self._problem(t, "games", 7, column=0, columnspan=4)

    def _tab_features(self, t: ttk.Frame) -> None:
        c = self.c
        top = ttk.Frame(t)
        top.pack(fill="x")
        ttk.Label(top, text="Preset:").pack(side="left")
        for key, label in (("full", "Full"), ("basic", "Basic")):
            b = ttk.Button(top, text=label, command=lambda k=key: self._edit(lambda: c.apply_preset(k), refill=True))
            b.pack(side="left", padx=PAD)
            self.form_widgets.append(b)
        self.preset_label = ttk.Label(top, text="", style="Muted.TLabel")
        self.preset_label.pack(side="left", padx=PAD)
        ttk.Label(t, text="Features the cafe gets. Ones left off can be sold later as an add-on (Issue upgrade).",
                  style="Muted.TLabel").pack(anchor="w", pady=(PAD, 2))
        box = ttk.Frame(t)
        box.pack(fill="x")
        self.feature_vars: dict[str, tk.BooleanVar] = {}
        self.feature_checks: dict[str, ttk.Checkbutton] = {}
        from .profile import FEATURES, SAFETY_FLAGS, feature_label
        for i, name in enumerate(FEATURES):
            var = tk.BooleanVar()
            var.trace_add("write", lambda *_a, n=name, v=var: self._edit(lambda: c.set_feature(n, v.get())))
            text = feature_label(name) + ("  (always on)" if name in SAFETY_FLAGS else "")
            cb = ttk.Checkbutton(box, text=text, variable=var)
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 24), pady=1)
            self.feature_vars[name] = var
            self.feature_checks[name] = cb
            if name not in SAFETY_FLAGS:
                self.form_widgets.append(cb)
            else:
                cb.state(["disabled"])
        self.features_problem = ttk.Label(t, text="", style="Problem.TLabel")
        self.features_problem.pack(anchor="w")
        self.problem_labels["features"] = self.features_problem

    def _tab_price(self, t: ttk.Frame) -> None:
        c = self.c
        ttk.Label(t, text="Branding", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        variant = self._var("variant", on_change=lambda: c.set_variant(self.vars["variant"].get()), refill=True)
        r = 1
        for key, label, note in c.variant_choices():
            rb = ttk.Radiobutton(t, text=label, value=key, variable=variant)
            rb.grid(row=r, column=0, sticky="w")
            ttk.Label(t, text=note, style="Muted.TLabel", wraplength=560).grid(row=r, column=1, columnspan=3,
                                                                              sticky="w")
            self.form_widgets.append(rb)
            r += 1
        self._problem(t, "variant", r)
        ttk.Label(t, text="Price", style="Head.TLabel").grid(row=r + 1, column=0, sticky="w", pady=(PAD * 2, 2))
        ttk.Label(t, text="Agreed price (₹)").grid(row=r + 2, column=0, sticky="w")
        pe = ttk.Entry(t, width=14, textvariable=self._var(
            "price", on_change=lambda: c.set_price_text(self.vars["price"].get())))
        pe.grid(row=r + 2, column=1, sticky="w")
        self.list_btn = ttk.Button(t, text="Use list price", command=lambda: self._edit(c.use_list_price,
                                                                                         refill=True))
        self.list_btn.grid(row=r + 2, column=2, sticky="w", padx=PAD)
        self.form_widgets += [pe]
        self.price_note = ttk.Label(t, text="", style="Muted.TLabel")
        self.price_note.grid(row=r + 3, column=1, columnspan=3, sticky="w")
        self._problem(t, "price_inr", r + 4)
        self._entry(t, r + 5, "Discount note (optional)",
                    self._var("discount_note", on_change=lambda: c.set_discount_note(self.vars["discount_note"].get())),
                    width=60)
        self._problem(t, "discount_note", r + 6)
        ttk.Label(t, text="On the certificate", style="Head.TLabel").grid(row=r + 7, column=0, sticky="w",
                                                                          pady=(PAD * 2, 2))
        self.breakdown = ttk.Frame(t)
        self.breakdown.grid(row=r + 8, column=0, columnspan=4, sticky="w")
        ttk.Label(t, text="History", style="Head.TLabel").grid(row=r + 9, column=0, sticky="w", pady=(PAD * 2, 2))
        self.history = ttk.Label(t, text="", style="Muted.TLabel", justify="left")
        self.history.grid(row=r + 10, column=0, columnspan=4, sticky="w")

    def _build_bottom(self) -> None:
        bottom = ttk.Frame(self.root, padding=(PAD, 0, PAD, PAD))
        bottom.pack(fill="x")
        self.hint = ttk.Label(bottom, text="", style="Muted.TLabel")
        self.hint.pack(anchor="w", pady=(PAD, 2))
        row = ttk.Frame(bottom)
        row.pack(fill="x")
        self.buttons = {
            "preview": ttk.Button(row, text="Preview", command=self.on_preview),
            "build": ttk.Button(row, text="Build package", command=self.on_build),
            "upgrade": ttk.Button(row, text="Issue upgrade", command=self.on_upgrade),
            "rebuild": ttk.Button(row, text="Rebuild all", command=self.on_rebuild),
            "shipments": ttk.Button(row, text="Open shipments folder", command=lambda: self._do(self.c.open_shipments)),
        }
        for b in self.buttons.values():
            b.pack(side="left", padx=(0, PAD))
        self.settings_btn = ttk.Button(row, text="Settings…", command=self.on_settings)
        self.settings_btn.pack(side="right")
        self.job_row = ttk.Frame(bottom)
        self.progress = ttk.Progressbar(self.job_row, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        self.cancel_btn = ttk.Button(self.job_row, text="Cancel", command=self.on_cancel)
        self.cancel_btn.pack(side="left", padx=(PAD, 0))
        self.statusbar = ttk.Label(self.root, text="", relief="sunken", anchor="w", padding=(PAD, 2))
        self.statusbar.pack(fill="x", side="bottom")

    # --- filling the window from the controller -----------------------------------------------------------------

    def refresh_all(self) -> None:
        self.refresh_list()
        self.fill_form()
        self.refresh_state()

    def refresh_list(self) -> None:
        rows = self.c.rows()
        self._list_keys = [k for k, _, _ in rows]
        self.listbox.delete(0, "end")
        for _key, title, note in rows:
            self.listbox.insert("end", f"{title}   ({note})" if note else title)
        sel = self.c.selected_key()
        if sel in self._list_keys:
            i = self._list_keys.index(sel)
            self.listbox.selection_set(i)
            self.listbox.see(i)

    def fill_form(self) -> None:
        """Put the controller's cafe into the widgets (without these writes counting as edits)."""
        c, p = self.c, self.c.profile
        self._filling = True
        try:
            if p is None:
                self.nb.pack_forget()
                self.empty.pack(fill="both", expand=True)
                self.cafe_title.configure(text="")
                return
            self.empty.pack_forget()
            if not self.nb.winfo_ismapped():
                self.nb.pack(fill="both", expand=True, pady=(PAD, 0))
            v = self.vars
            self._set(v["name"], p.name)
            self._set(v["tagline"], p.tagline)
            self._set(v["wifi_on"], p.wifi is not None)
            self._set(v["ssid"], p.wifi.ssid if p.wifi else "")
            self._set(v["wifi_pw"], p.wifi.password if p.wifi else "")
            self._set(v["wifi_sec"], "Open (no password)" if p.wifi and p.wifi.security == "nopass"
                              else "WPA (with a password)")
            self._set(v["hours_on"], p.hours is not None)
            self._set(v["open"], HOURS[p.hours.open_hour] if p.hours and 0 <= p.hours.open_hour <= 24 else "10:00")
            self._set(v["close"], HOURS[p.hours.close_hour] if p.hours and 0 <= p.hours.close_hour <= 24 else "22:00")
            self._set(v["contact_name"], p.contact.name)
            self._set(v["contact_phone"], p.contact.phone)
            self._set(v["contact_city"], p.contact.city)
            self._set(v["rigs"], c.rigs_text)
            self._fill_rig_names()
            self._fill_games()
            for name, _label, on, _locked in c.feature_rows():
                self._set(self.feature_vars[name], on)
            self._set(v["variant"], p.variant)
            self._set(v["price"], c.price_text)
            self._set(v["discount_note"], p.discount_note)
            self._fill_logo()
        finally:
            self._filling = False

    def _fill_rig_names(self) -> None:
        slots = self.c.rig_name_slots()
        for i, (lab, ent, var) in enumerate(self.rig_entries):
            if i < len(slots):
                self._set(var, slots[i])
                lab.grid(row=i // 3, column=(i % 3) * 2, sticky="w", padx=(0, 4), pady=1)
                ent.grid(row=i // 3, column=(i % 3) * 2 + 1, sticky="w", padx=(0, 16), pady=1)
            else:
                lab.grid_remove()
                ent.grid_remove()

    def _fill_games(self) -> None:
        for w in self.games_frame.winfo_children():
            w.destroy()
        self.game_vars = {}
        for gid, name, on in self.c.game_rows():
            var = tk.BooleanVar(value=on)
            var.trace_add("write", lambda *_a, g=gid, v=var: self._edit(lambda: self.c.set_game(g, v.get())))
            cb = ttk.Checkbutton(self.games_frame, text=name, variable=var)
            cb.pack(anchor="w")
            if self.c.job is not None:
                cb.state(["disabled"])
            self.game_vars[gid] = var

    def _fill_logo(self) -> None:
        path = self.c.logo_path()
        self._logo_image = None
        self.logo_image_label.configure(image="")
        if path is None:
            self.logo_name.configure(text="No logo")
            return
        self.logo_name.configure(text=path.name)
        png = self.c.logo_preview_path()
        if png is not None:
            try:
                img = tk.PhotoImage(file=str(png))
                factor = max(1, math.ceil(max(img.width(), img.height()) / LOGO_BOX))
                self._logo_image = img.subsample(factor) if factor > 1 else img
                self.logo_image_label.configure(image=self._logo_image)
            except tk.TclError:
                self._logo_image = None

    def refresh_state(self) -> None:
        """Everything that follows from the cafe and the job: problems, tab titles, buttons, banner, status."""
        c, p = self.c, self.c.profile
        busy = c.job is not None
        if p is not None:
            title = p.name.strip() or "New cafe"
            self.cafe_title.configure(text=title + ("  (not saved)" if c.dirty else ""))
            problems = c.problems()
            for fieldname, lab in self.problem_labels.items():
                lab.configure(text="\n".join(problems.get(fieldname, [])))
            for i, name in enumerate(TABS):
                self.nb.tab(i, text=c.tab_title(name))
            self.preset_label.configure(text=f"Now: {c.preset_name()}")
            self.price_note.configure(text=c.price_note())
            self.accent_sample.configure(bg=p.accent if len(p.accent) == 7 else "white")
            self._fill_breakdown()
            self.history.configure(text="\n".join(c.history_lines()) or "Not built yet.")
            wifi_on = bool(self.vars["wifi_on"].get())
            hours_on = bool(self.vars["hours_on"].get())
            for w in self.form_widgets:
                self._enable(w, not busy)
            for w in self.wifi_widgets:
                self._enable(w, not busy and wifi_on, readonly=isinstance(w, ttk.Combobox))
            for w in self.hours_widgets:
                self._enable(w, not busy and hours_on, readonly=True)
            self._enable(self.list_btn, not busy and p.variant == "9t7" and not p.price_auto)
        acts = c.actions()
        self._enable(self.save_btn, acts["save"].enabled)
        self._enable(self.revert_btn, not busy and c.dirty)
        self._enable(self.new_btn, acts["new"].enabled)
        self._enable(self.listbox, not busy)
        self._enable(self.settings_btn, acts["settings"].enabled)
        for name, b in self.buttons.items():
            a = acts[name]
            self._enable(b, a.enabled)
            if a.label:
                b.configure(text=a.label)
        self._refresh_banner()
        self._refresh_job()
        self.hint.configure(text=c.hint())
        self.statusbar.configure(text=c.status)

    def _fill_breakdown(self) -> None:
        for w in self.breakdown.winfo_children():
            w.destroy()
        lines = self.c.price_lines()
        for i, (label, amount) in enumerate(lines):
            bold = label == "Total" or label == "Agreed price"
            font = ("Segoe UI", 10, "bold") if bold else None
            ttk.Label(self.breakdown, text=label, font=font).grid(row=i, column=0, sticky="w", padx=(0, 24))
            ttk.Label(self.breakdown, text=amount, font=font).grid(row=i, column=1, sticky="e")
        if not lines:
            ttk.Label(self.breakdown, text="Enter the price to see it here.", style="Muted.TLabel").grid(row=0,
                                                                                                     column=0)

    def _refresh_banner(self) -> None:
        info = self.c.banner()
        for w in self.banner_buttons.winfo_children():
            w.destroy()
        if info is None:
            self.banner.pack_forget()
            return
        text, buttons = info
        self.banner_text.configure(text=text)
        actions = {"Set up keys": self.on_setup_keys, "Copy key to…": self.on_copy_key, "Settings": self.on_settings}
        for label in buttons:
            tk.Button(self.banner_buttons, text=label, command=actions[label]).pack(side="left", padx=2)
        if not self.banner.winfo_ismapped():
            self.banner.pack(fill="x", side="top", before=self.body)

    def _refresh_job(self) -> None:
        job = self.c.job
        if job is None:
            self.progress.stop()
            self.job_row.pack_forget()
            return
        if not self.job_row.winfo_ismapped():
            self.job_row.pack(fill="x", pady=(PAD, 0))
        if job.total:
            if str(self.progress["mode"]) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
            self.progress["value"] = 100.0 * min(job.done, job.total) / job.total
        elif str(self.progress["mode"]) != "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start(15)
        self._enable(self.cancel_btn, self.c.actions()["cancel"].enabled)

    @staticmethod
    def _enable(widget: tk.Widget, on: bool, readonly: bool = False) -> None:
        try:
            if isinstance(widget, (ttk.Widget,)) and not isinstance(widget, tk.Listbox):
                if readonly and on:
                    widget.state(["!disabled", "readonly"])
                else:
                    widget.state(["!disabled"] if on else ["disabled"])
            else:
                widget.configure(state="normal" if on else "disabled")
        except tk.TclError:
            pass

    # --- the worker loop ------------------------------------------------------------------------------------

    def _tick(self) -> None:
        try:
            notices = self.c.poll()
            job = self.c.job
            sig = (job.kind, job.done, job.total, job.text, job.cancelling) if job else None
            sig = (sig, self.c.preview is None)
            if notices or sig != self._last_sig:
                if self._last_sig is not None and self._last_sig[0] is not None and job is None:
                    self.refresh_list()        # a job ended: the history (and the form) may have changed
                    self.fill_form()
                self._last_sig = sig
                self.refresh_state()
            for n in notices:
                self.show_notice(n)
        finally:
            try:
                self.root.after(POLL_MS, self._tick)
            except tk.TclError:
                pass                           # the window is gone

    # --- actions ------------------------------------------------------------------------------------------------

    def _do(self, fn: Callable[[], Any], *, refill: bool = False) -> Any:
        """Run a controller call from a button; a ControllerError becomes a plain message box."""
        try:
            result = fn()
        except ControllerError as exc:
            messagebox.showerror(TITLE, str(exc), parent=self.root)
            result = None
        if refill:
            self.fill_form()
        self.refresh_list()
        self.refresh_state()
        return result

    def _edit(self, fn: Callable[[], Any], *, refill: bool = False) -> None:
        """A form edit. Ignored while the form is being filled."""
        if self._filling or self.c.profile is None:
            return
        try:
            fn()
        except ControllerError as exc:
            self.c.status = str(exc)
        if refill:
            self.fill_form()
        if self.c.profile is not None and self.c.path is None:
            self.refresh_list()                # a new cafe's name shows in the list as it is typed
        self.refresh_state()

    def _set_wifi(self) -> None:
        v = self.vars
        self.c.set_wifi(bool(v["wifi_on"].get()), v["ssid"].get(), v["wifi_pw"].get(),
                        "nopass" if v["wifi_sec"].get().startswith("Open") else "WPA")

    def _set_hours(self) -> None:
        v = self.vars
        try:
            o, cl = HOURS.index(v["open"].get()), HOURS.index(v["close"].get())
        except ValueError:
            o, cl = 10, 22
        self.c.set_hours(bool(v["hours_on"].get()), o, cl)

    def _ask_leave(self) -> bool:
        """Before leaving the open cafe: save, drop or stay. True = go on."""
        q = self.c.leave_prompt()
        if q is None:
            return True
        answer = messagebox.askyesnocancel(TITLE, q + "\n\nYes saves them, No drops them.", parent=self.root)
        if answer is None:
            return False
        try:
            if answer:
                self.c.save()
            else:
                self.c.revert()
        except ControllerError as exc:
            messagebox.showerror(TITLE, str(exc), parent=self.root)
            return False
        return True

    def _on_search(self) -> None:
        self.c.set_search(self.search_var.get())
        self.refresh_list()

    def _on_list_select(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        key = self._list_keys[sel[0]]
        if key == self.c.selected_key():
            return
        if self.c.job is not None or not self._ask_leave():
            self.refresh_list()                # put the selection back
            return
        if key != NEW_KEY:
            self._do(lambda: self.c.select(key), refill=True)
        else:
            self.refresh_all()

    def on_new(self) -> None:
        if not self._ask_leave():
            return
        self._do(self.c.new_cafe, refill=True)
        self.nb.select(0)

    def on_save(self) -> None:
        self._do(self.c.save, refill=True)

    def on_revert(self) -> None:
        self._do(self.c.revert, refill=True)

    def on_choose_logo(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Choose the cafe's logo",
                                          filetypes=[("Pictures", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")])
        if path:
            self._do(lambda: self.c.choose_logo(Path(path)), refill=True)

    def on_other_colour(self) -> None:
        p = self.c.profile
        if p is None:
            return
        _rgb, hexcol = colorchooser.askcolor(color=p.accent, parent=self.root, title="Accent colour")
        if hexcol:
            self._edit(lambda: self.c.set_accent(hexcol))

    def on_preview(self) -> None:
        self._do(self.c.toggle_preview)

    def on_build(self) -> None:
        self._do(self.c.start_build)

    def on_upgrade(self) -> None:
        default, question = self.c.upgrade_default_price()
        text = simpledialog.askstring("Issue upgrade", question, parent=self.root,
                                      initialvalue="" if default is None else str(default))
        if text is None:
            return
        self._do(lambda: self.c.start_upgrade(text))

    def on_rebuild(self) -> None:
        if not messagebox.askyesno(
                "Rebuild all",
                f"Rebuild every cafe's package with this version of {brand.PRODUCT_NAME}? Each cafe gets a new "
                "package and licence code with the same rigs, games and features. This can take a while.",
                parent=self.root):
            return
        self._do(self.c.start_rebuild_all)

    def on_cancel(self) -> None:
        self.c.cancel_job()
        self.refresh_state()

    def on_setup_keys(self) -> None:
        k = self.c.keys
        if not k.has_keys and not messagebox.askokcancel(
                "Set up keys",
                "This makes your signing key: it signs every cafe's licence, and only this PC has it. Its public "
                f"half is added to {brand.PRODUCT_NAME}'s source so cafes' hubs accept your licences.",
                parent=self.root):
            return
        text = self._do(self.c.setup_keys)
        if text:
            messagebox.showinfo("Set up keys", text, parent=self.root)
            if not self.c.keys.backed_up and messagebox.askyesno(
                    "Back up your signing key", "Copy the key to a USB drive now?", parent=self.root):
                self.on_copy_key()

    def on_copy_key(self) -> None:
        folder = filedialog.askdirectory(parent=self.root, mustexist=True,
                                         title="Choose a USB drive or folder for the copy of your key")
        if not folder:
            return
        text = self._do(lambda: self.c.copy_key_to(Path(folder)))
        if text:
            messagebox.showinfo("Copy key to…", text, parent=self.root)

    def on_settings(self) -> None:
        SettingsDialog(self)

    def on_close(self) -> None:
        why = self.c.close_prompt()
        if why:
            messagebox.showinfo(TITLE, why, parent=self.root)
            return
        if not self._ask_leave():
            return
        self.c.shutdown()
        self.root.destroy()

    def _callback_error(self, exc: type, value: BaseException, tb: Any) -> None:
        details = "".join(traceback.format_exception(exc, value, tb))
        log.error("window error:\n%s", details)
        if isinstance(value, ControllerError):
            messagebox.showerror(TITLE, str(value), parent=self.root)
            return
        MessageDialog(self.root, TITLE, "Something went wrong in the window. Try again; Show details has what "
                                        "happened.", details, error=True)

    # --- notices --------------------------------------------------------------------------------------------

    def show_notice(self, n: Notice) -> tk.Toplevel:
        if n.kind == "upgrade":
            return UpgradeDialog(self, n)
        if n.kind == "rebuild":
            return RebuildDialog(self, n)
        return MessageDialog(self.root, n.title, n.message, n.details, error=n.kind == "error")


# --- dialogs -----------------------------------------------------------------------------------------------------

class _Dialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.body = ttk.Frame(self, padding=PAD * 2)
        self.body.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda _e: self.destroy())

    def details_box(self, details: str) -> Callable[[], None]:
        """A hidden scrollable text with `details`; returns the Show/Hide details toggle."""
        box = ScrolledText(self.body, height=14, width=90, wrap="word")
        box.insert("1.0", details)
        box.configure(state="disabled")
        shown = [False]

        def toggle() -> None:
            if shown[0]:
                box.pack_forget()
            else:
                box.pack(fill="both", expand=True, pady=(PAD, 0))
            shown[0] = not shown[0]
        return toggle


class MessageDialog(_Dialog):
    """A plain message, with "Show details" (a scrollable log) when there are details."""

    def __init__(self, parent: tk.Misc, title: str, message: str, details: str = "", error: bool = False) -> None:
        super().__init__(parent, title)
        ttk.Label(self.body, text=message, wraplength=560, justify="left",
                  foreground=RED if error else "").pack(anchor="w")
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(PAD * 2, 0))
        ok = ttk.Button(row, text="OK", command=self.destroy)
        ok.pack(side="right")
        if details.strip():
            ttk.Button(row, text="Show details", command=self.details_box(details)).pack(side="right", padx=PAD)
        ok.focus_set()


class UpgradeDialog(_Dialog):
    """Issue upgrade's result: the code with a Copy button, and the folder (opened already)."""

    def __init__(self, app: FactoryApp, n: Notice) -> None:
        super().__init__(app.root, n.title)
        self.app = app
        ttk.Label(self.body, text=n.message, wraplength=620, justify="left").pack(anchor="w")
        code = tk.Text(self.body, height=6, width=80, wrap="char")
        code.insert("1.0", n.code)
        code.configure(state="disabled")
        code.pack(fill="x", pady=PAD)
        row = ttk.Frame(self.body)
        row.pack(fill="x")
        self.copied = ttk.Label(row, text="", style="Muted.TLabel")
        ttk.Button(row, text="Copy code", command=lambda: self.copy(n.code)).pack(side="left")
        self.copied.pack(side="left", padx=PAD)
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        if n.folder is not None:
            ttk.Button(row, text="Open folder", command=lambda: app.c.opener(n.folder)).pack(side="right", padx=PAD)
        if n.details.strip():
            ttk.Button(row, text="Show details", command=self.details_box(n.details)).pack(side="right")

    def copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.copied.configure(text="Copied.")


class RebuildDialog(_Dialog):
    """Rebuild all's summary table."""

    def __init__(self, app: FactoryApp, n: Notice) -> None:
        super().__init__(app.root, n.title)
        ttk.Label(self.body, text=n.message).pack(anchor="w")
        cols = ("cafe", "result", "message", "package")
        tree = ttk.Treeview(self.body, columns=cols, show="headings", height=min(14, max(3, len(n.rows))))
        for col, head, width in zip(cols, ("Cafe", "Result", "What happened", "Package"), (180, 70, 420, 220)):
            tree.heading(col, text=head)
            tree.column(col, width=width, anchor="w")
        for row in n.rows:
            tree.insert("", "end", values=row)
        tree.pack(fill="both", expand=True, pady=PAD)
        row = ttk.Frame(self.body)
        row.pack(fill="x")
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        if n.folder is not None:
            ttk.Button(row, text="Open shipments folder", command=lambda: app.c.opener(n.folder)).pack(
                side="right", padx=PAD)
        if n.details.strip():
            ttk.Button(row, text="Show details", command=self.details_box(n.details)).pack(side="right")


class SettingsDialog(_Dialog):
    """The Shipments folder, the Edge program and the signing key's backup."""

    def __init__(self, app: FactoryApp) -> None:
        super().__init__(app.root, "Settings")
        self.app = app
        c = app.c
        b = self.body
        self.ship = tk.StringVar(value=str(c.settings.shipments))
        self.edge = tk.StringVar(value=str(c.settings.edge) if c.settings.edge else "")
        ttk.Label(b, text="Shipments folder (packages and cafe files; keep it outside the program's folder)").grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Entry(b, textvariable=self.ship, width=70).grid(row=1, column=0, columnspan=2, sticky="we")
        ttk.Button(b, text="Choose…", command=self.choose_ship).grid(row=1, column=2, padx=PAD)
        ttk.Label(b, text="Microsoft Edge (makes the PDFs; leave blank to find it by itself)").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(PAD * 2, 0))
        ttk.Entry(b, textvariable=self.edge, width=70).grid(row=3, column=0, columnspan=2, sticky="we")
        ttk.Button(b, text="Choose…", command=self.choose_edge).grid(row=3, column=2, padx=PAD)
        ttk.Label(b, text=c.edge_text(), style="Muted.TLabel").grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Label(b, text="Signing key", style="Head.TLabel").grid(row=5, column=0, sticky="w", pady=(PAD * 2, 0))
        self.key_text = ttk.Label(b, text=c.key_summary(), wraplength=620, justify="left")
        self.key_text.grid(row=6, column=0, columnspan=3, sticky="w")
        keys = ttk.Frame(b)
        keys.grid(row=7, column=0, columnspan=3, sticky="w", pady=PAD)
        ttk.Button(keys, text="Set up keys", command=self.setup_keys).pack(side="left")
        ttk.Button(keys, text="Copy key to…", command=self.copy_key).pack(side="left", padx=PAD)
        row = ttk.Frame(b)
        row.grid(row=8, column=0, columnspan=3, sticky="e", pady=(PAD * 2, 0))
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(row, text="Save", command=self.save).pack(side="right", padx=PAD)
        self.grab_set()

    def choose_ship(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="Choose the Shipments folder")
        if folder:
            self.ship.set(folder)

    def choose_edge(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Choose msedge.exe",
                                          filetypes=[("Programs", "*.exe"), ("All files", "*.*")])
        if path:
            self.edge.set(path)

    def setup_keys(self) -> None:
        self.app.on_setup_keys()
        self.key_text.configure(text=self.app.c.key_summary())

    def copy_key(self) -> None:
        self.app.on_copy_key()
        self.key_text.configure(text=self.app.c.key_summary())

    def save(self) -> None:
        c = self.app.c
        moving = self.ship.get().strip() != str(c.settings.shipments)
        if moving and not self.app._ask_leave():
            return
        try:
            c.update_settings(self.ship.get(), self.edge.get())
        except ControllerError as exc:
            messagebox.showerror("Settings", str(exc), parent=self)
            return
        self.destroy()
        self.app.refresh_all()


# --- starting --------------------------------------------------------------------------------------------------

def _setup_logging() -> None:
    """factory.log in the factory's settings folder (never the repo or Shipments; no key material is logged)."""
    try:
        folder = build.config_dir()
        folder.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            folder / "factory.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _dpi_aware() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)      # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    _dpi_aware()
    try:
        root = tk.Tk()
    except tk.TclError:
        print("The factory window can't open here (no screen).", file=sys.stderr if sys.stderr else sys.stdout)
        return 1
    FactoryApp(root, Controller())
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
