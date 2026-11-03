"""The factory window's logic (spec 2.8, F8), with no tkinter: everything the form does, testable on Linux.

`factory/app.py` draws the widgets and calls this. The split:

- **Controller state** (read by the window after every change): the cafe list (`rows()`, with the search box),
  the cafe being edited (`profile`, `dirty`), its problems by field and by tab (`problems()`, `tab_problems()`),
  the price breakdown (`price_lines()`), the key banner (`banner()`), which buttons work (`actions()`), the status
  bar (`status`) and the running job (`job`).
- **Edits** (`set_name`, `set_rigs_text`, `set_feature`, `set_variant`, `set_price_text`, ...) change the working
  copy only. Saving is explicit (`save()`); switching cafe with unsaved changes asks first (`leave_prompt()`).
  A job (Build package, Issue upgrade, Rebuild all) saves the cafe first, because the build records its history in
  the cafe's file; afterwards the cafe is read back from its file.
- **Jobs** run the back end (factory.build / factory.preview) in a worker thread. The worker never touches the
  window: it only puts events on a queue, and the window calls `poll()` from tkinter's `after()` loop, which applies
  them here (on the window's thread) and returns `Notice`s for the window to show (a message with "Show details",
  the upgrade code, the Rebuild all table).

Nothing here goes on the network; "open folder" is `open_folder` (os.startfile on Windows, xdg-open elsewhere),
injectable for tests. The back-end functions are injectable too (`Backend`).
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Literal

from simtelemetry import brand, licence
from simtelemetry.core.settings import ACCENT_SWATCHES
from simtelemetry.provision import MAX_RIGS

from . import build, docs, pricing, preview
from . import keys as keys_mod
from .build import BUILD_STEPS, BuildCancelled, BuildError, FactorySettings
from .keys import Keys, KeysError
from .profile import (FEATURES, PRESET_NAMES, SAFETY_FLAGS, CafeProfile, ProfileEntry, ProfileError,
                      available_games, feature_label, load)
from .preview import PreviewError

log = logging.getLogger(__name__)

TABS = ("Cafe", "Rigs & games", "Features", "Branding & price")
# Which tab shows each profile field's problems (spec 2.8: problems next to the fields).
FIELD_TAB = {
    "cafe_id": "Cafe", "name": "Cafe", "tagline": "Cafe", "logo": "Cafe", "accent": "Cafe", "wifi": "Cafe",
    "hours": "Cafe", "contact": "Cafe",
    "rigs": "Rigs & games", "rig_names": "Rigs & games", "games": "Rigs & games",
    "features": "Features",
    "variant": "Branding & price", "price_inr": "Branding & price", "discount_note": "Branding & price",
}
VARIANT_LABELS = {"9t7": brand.COMPANY, "unbranded": "Unbranded"}
VARIANT_NOTES = {
    "9t7": f'Says "{brand.PRODUCT_NAME}, by {brand.COMPANY}": TV, installer, guide, certificate and video.',
    "unbranded": f"Still called {brand.PRODUCT_NAME}, with no {brand.COMPANY} marks anywhere. Type the agreed price.",
}
NEW_KEY = "new"                       # the list row of a new cafe that isn't saved yet
POLL_MS = 100

PRICE_BAD = "Type the price in whole rupees, for example 20000."
RIGS_BAD = "Type the number of rigs, for example 6."
BUSY = "Wait for the current job to finish, or press Cancel."
NO_CAFE = "Choose a cafe on the left, or press New cafe."
# A running preview may be using the program a build replaces (Windows can't replace a program that is running).
STOP_PREVIEW_FIRST = "Press Stop preview first."

BANNER_NO_KEYS = ("There's no signing key on this PC yet. Press Set up keys: it makes the key that signs every "
                  "cafe's licence.")
BANNER_NOT_TRUSTED = (f"Your signing key isn't in this copy of {brand.PRODUCT_NAME} yet, so cafes would refuse its "
                      "licences. Press Set up keys to add it.")
BANNER_BACKUP = ("Back up your signing key. If this PC is lost or breaks without a copy, every cafe needs a new "
                 "package before you can sell it an add-on. Press Copy key to… and choose a USB drive, then keep it "
                 "safe.")

SETUP_DONE = (
    "Your signing key is ready (key {fingerprint}).\n\n"
    f"It was added to {brand.PRODUCT_NAME}'s source, in {{module}}. Keep that changed file with the source (commit "
    "it), so every later copy knows your key.\n\n"
    f"Cafes' hubs only accept licences from a {brand.PRODUCT_NAME} program that knows this key, so the program "
    "must be built again. The next Build package does that by itself; it takes several minutes that one time.\n\n"
    "Now back up the key: press Copy key to… and choose a USB drive.")
SETUP_ALREADY = (
    "Your signing key (key {fingerprint}) was added to "
    f"{brand.PRODUCT_NAME}'s source, in {{module}}. Keep that changed file with the source (commit it).\n\n"
    "The program must be built again so cafes' hubs accept its licences. The next Build package does that by "
    "itself; it takes several minutes that one time.")
LOST_KEY = (
    "If the signing key is ever lost: make a new one with Set up keys. Cafes you already sold keep working, but "
    f"their add-on codes then need a {brand.PRODUCT_NAME} build that knows the new key (send them a new package "
    "first).")


class ControllerError(ValueError):
    """Something the seller has to know or fix; plain English for a message box."""


# --- notices for the window --------------------------------------------------------------------------------

@dataclass
class Notice:
    """Something the window shows once: a message box (with "Show details" when `details`), the upgrade code or
    the Rebuild all table."""
    kind: Literal["info", "error", "upgrade", "rebuild"]
    title: str
    message: str
    details: str = ""
    code: str = ""                                   # upgrade: the code the Copy button copies
    folder: Path | None = None                       # where the files were saved
    rows: list[tuple[str, str, str, str]] = field(default_factory=list)   # rebuild: cafe, result, message, folder


@dataclass
class JobState:
    kind: str                                        # "build", "upgrade", "rebuild", "preview", "stop_preview"
    title: str
    cancel: threading.Event
    thread: threading.Thread | None = None
    done: int = 0
    total: int = 0                                   # 0 = no known length (the window shows a moving bar)
    text: str = ""
    cancellable: bool = True
    cancelling: bool = False
    cafe_id: str | None = None


@dataclass
class KeyStatus:
    has_keys: bool = False
    fingerprint: str | None = None
    trusted: bool = False
    backed_up: bool = False
    backed_up_to: str | None = None
    backed_up_on: dt.date | None = None
    problem: str | None = None                       # a key that can't be opened (damaged, another account)


@dataclass
class Action:
    enabled: bool
    reason: str = ""                                 # why it is off, in plain English (shown on the status bar)
    label: str = ""                                  # the button's text when it changes (Preview / Stop preview)


# --- injectable outside world --------------------------------------------------------------------------------

def _desktop() -> str:
    """"windows", "mac" or "other". Tests replace this (patching os.name instead would break pathlib)."""
    if os.name == "nt":
        return "windows"
    return "mac" if sys.platform == "darwin" else "other"


def open_folder(path: Path) -> None:
    """Show a folder in Explorer (Windows) or the desktop's file manager. Never raises for a missing program."""
    path = Path(path)
    try:
        desktop = _desktop()
        if desktop == "windows":
            os.startfile(str(path))                  # type: ignore[attr-defined]
        elif desktop == "mac":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        log.warning("couldn't open %s", path, exc_info=True)


@dataclass
class Backend:
    """The factory's back-end functions; tests replace them with fakes."""
    build_package: Callable[..., Any] = build.build_package
    rebuild_all: Callable[..., Any] = build.rebuild_all
    issue_upgrade: Callable[..., Any] = build.issue_upgrade
    upgrade_plan: Callable[..., Any] = build.upgrade_plan
    start_preview: Callable[..., Any] = preview.start_preview
    create_keys: Callable[..., Any] = keys_mod.create_keys
    load_private: Callable[..., Any] = keys_mod.load_private
    has_keys: Callable[..., Any] = keys_mod.has_keys
    backup_state: Callable[..., Any] = keys_mod.backup_state
    copy_backup: Callable[..., Any] = keys_mod.copy_backup
    write_public_key_py: Callable[..., Any] = keys_mod.write_public_key_py
    trusted_keys: Callable[[FactorySettings], tuple[bytes, ...]] = build._trusted
    find_edge: Callable[..., Any] = docs.find_edge
    video_problem: Callable[..., Any] = build.video_problem


# --- helpers ---------------------------------------------------------------------------------------------------

_PRICE_RE = re.compile(r"^\d+$")


def parse_price(text: str) -> int | None:
    """"20,000", "₹ 20000", "Rs. 45,000" -> the rupees; "" -> None; anything else -> ControllerError(PRICE_BAD)."""
    s = (text or "").strip()
    s = re.sub(r"^(₹|rs\.?|inr)\s*", "", s, flags=re.IGNORECASE)
    s = s.replace(",", "").replace(" ", "").replace("_", "")
    if s.endswith(("/-", ".00")):
        s = s[:-3] if s.endswith(".00") else s[:-2]
    if not s:
        return None
    if not _PRICE_RE.match(s) or len(s) > 9:
        raise ControllerError(PRICE_BAD)
    return int(s)


def format_price(value: int | None) -> str:
    return "" if value is None else str(value)


def _snapshot(profile: CafeProfile | None) -> str | None:
    return None if profile is None else profile.model_dump_json()


# --- the controller -------------------------------------------------------------------------------------------

class Controller:
    def __init__(self, settings: FactorySettings | None = None, *, settings_file: Path | None = None,
                 backend: Backend | None = None, opener: Callable[[Path], Any] = open_folder,
                 today: Callable[[], dt.date] = dt.date.today) -> None:
        self.settings_file = settings_file
        self.settings = settings if settings is not None else FactorySettings.load(settings_file)
        self.backend = backend or Backend()
        self.opener = opener
        self.today = today
        self.search = ""
        self.entries: list[ProfileEntry] = []
        self.profile: CafeProfile | None = None
        self.path: Path | None = None                  # the cafe's file (None: a new cafe, not saved yet)
        self._saved: str | None = None                 # the profile as last loaded/saved, to tell unsaved changes
        self.field_errors: dict[str, str] = {}         # typed text the form couldn't use (price, rigs)
        self.price_text = ""
        self.rigs_text = ""
        self.status = ""
        self.keys = KeyStatus()
        self.job: JobState | None = None
        self.preview: Any = None                       # a running factory.preview.Preview
        self.preview_cafe: str | None = None
        self._queue: queue.Queue = queue.Queue()
        self.refresh_keys()
        self.refresh_list()
        if self.settings.load_problem:
            self.status = self.settings.load_problem

    # --- the cafe list ---------------------------------------------------------------------------------------

    @property
    def store(self):
        return self.settings.store

    def refresh_list(self) -> None:
        self.entries = self.store.list()

    def rows(self) -> list[tuple[str, str, str]]:
        """(key, title, note) for the list, filtered by the search box. key is the file path, or NEW_KEY for a new
        cafe that isn't saved yet (listed first)."""
        out: list[tuple[str, str, str]] = []
        needle = self.search.strip().casefold()
        if self.profile is not None and self.path is None:
            title = self.profile.name.strip() or "New cafe"
            out.append((NEW_KEY, title, "not saved yet"))
        for e in self.entries:
            if needle:
                hay = e.title
                if e.profile is not None:
                    hay += " " + e.profile.contact.city + " " + e.profile.contact.name
                if needle not in hay.casefold():
                    continue
            note = e.error or ""
            if e.profile is not None and not note:
                last = build.latest_entry(e.profile)
                note = f"built {last.date.isoformat()}" if last else "not built yet"
            out.append((str(e.path), e.title, note))
        return out

    def set_search(self, text: str) -> None:
        self.search = text or ""

    def selected_key(self) -> str | None:
        if self.profile is None:
            return None
        return NEW_KEY if self.path is None else str(self.path)

    @property
    def dirty(self) -> bool:
        return self.profile is not None and (_snapshot(self.profile) != self._saved or bool(self.field_errors))

    def leave_prompt(self) -> str | None:
        """The question to ask before leaving the cafe (another cafe, New cafe, closing), or None when it's saved."""
        if not self.dirty:
            return None
        name = self.profile.name.strip() or "this new cafe"
        return f"Save the changes to {name}?"

    def select(self, key: str) -> None:
        """Open a cafe from the list (unsaved changes are dropped: ask with leave_prompt() first)."""
        self._idle()
        if key == NEW_KEY:
            return
        entry = next((e for e in self.entries if str(e.path) == key), None)
        if entry is None:
            raise ControllerError("That cafe isn't in the list any more.")
        if entry.profile is None:
            raise ControllerError(entry.error or "This cafe's file can't be opened.")
        try:
            profile = load(entry.path)            # read it fresh: a build may have added history since the list
        except ProfileError as exc:
            raise ControllerError(str(exc)) from None
        self._open(profile, entry.path)
        self.status = f"Opened {self.profile.name.strip() or 'the cafe'}."

    def new_cafe(self) -> None:
        self._idle()
        self._open(CafeProfile.new(""), None)
        self._saved = None
        self.status = "New cafe: fill in each tab, then press Save."

    def _open(self, profile: CafeProfile, path: Path | None) -> None:
        for flag in SAFETY_FLAGS:                       # the safety switches are always on (shown so in the form)
            if flag in profile.features and not profile.features[flag]:
                profile.features = {**profile.features, flag: True}
        self.profile, self.path = profile, path
        self._saved = _snapshot(profile)
        self.field_errors = {}
        self.price_text = format_price(profile.price_inr)
        self.rigs_text = str(profile.rigs)

    def revert(self) -> None:
        """Drop unsaved changes."""
        self._idle()
        if self.profile is None:
            return
        if self.path is None:
            self.profile = self.path = None
            self._saved = None
            self.field_errors = {}
            return
        try:
            self._open(load(self.path), self.path)
        except ProfileError as exc:
            raise ControllerError(str(exc)) from None

    def save(self) -> Path:
        """Save the cafe (a half-filled cafe is fine: problems only stop a build)."""
        self._idle()
        p = self._need_profile()
        if self.field_errors:
            raise ControllerError("Fix this first: " + next(iter(self.field_errors.values())))
        try:
            self.path = self.store.save(p)
        except ProfileError as exc:
            raise ControllerError(str(exc)) from None
        self._saved = _snapshot(p)
        self.refresh_list()
        left = len(self.problems_flat())
        self.status = "Saved." + (f" {left} thing{'s' if left != 1 else ''} to fix before building." if left else "")
        return self.path

    def _need_profile(self) -> CafeProfile:
        if self.profile is None:
            raise ControllerError(NO_CAFE)
        return self.profile

    def _idle(self) -> None:
        if self.job is not None:
            raise ControllerError(BUSY)

    def _edit(self) -> CafeProfile:
        self._idle()
        return self._need_profile()

    # --- edits: Cafe tab -------------------------------------------------------------------------------------

    def set_name(self, text: str) -> None:
        self._edit().name = text

    def set_tagline(self, text: str) -> None:
        self._edit().tagline = text

    def set_accent(self, colour: str) -> None:
        p = self._edit()
        c = (colour or "").strip()
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", c):
            p.accent = c.upper()

    def choose_logo(self, source: Path) -> None:
        """Copy the chosen picture in (checked like /setup: PNG, JPEG or WebP under 1 MB)."""
        p = self._edit()
        try:
            self.store.import_logo(p, Path(source))
        except ProfileError as exc:
            raise ControllerError(str(exc)) from None

    def clear_logo(self) -> None:
        self._edit().logo = None

    def logo_path(self) -> Path | None:
        return None if self.profile is None else self.store.logo_path(self.profile)

    def logo_preview_path(self) -> Path | None:
        """The logo file when tkinter can show it cheaply (PNG); None otherwise (the window shows its name)."""
        path = self.logo_path()
        if path is None or path.suffix.lower() != ".png":
            return None
        try:
            return path if path.is_file() else None
        except OSError:
            return None

    def set_wifi(self, enabled: bool, ssid: str = "", password: str = "", security: str = "WPA") -> None:
        p = self._edit()
        if not enabled:
            p.wifi = None
            return
        p.wifi = {"ssid": ssid, "password": password, "security": security if security in ("WPA", "nopass")
                  else "WPA"}

    def set_hours(self, enabled: bool, open_hour: int = 10, close_hour: int = 22) -> None:
        p = self._edit()
        p.hours = {"open_hour": int(open_hour), "close_hour": int(close_hour)} if enabled else None

    def set_contact(self, name: str | None = None, phone: str | None = None, city: str | None = None) -> None:
        p = self._edit()
        c = p.contact.model_copy()
        if name is not None:
            c.name = name
        if phone is not None:
            c.phone = phone
        if city is not None:
            c.city = city
        p.contact = c

    # --- edits: Rigs & games ----------------------------------------------------------------------------------

    def set_rigs_text(self, text: str) -> None:
        """The rig count as typed in the spin box. A 9T7 list price follows it until a price is typed."""
        p = self._edit()
        self.rigs_text = text
        s = (text or "").strip()
        if not s.isdigit() or len(s) > 3:
            self.field_errors["rigs"] = RIGS_BAD
            return
        self.field_errors.pop("rigs", None)
        p.rigs = int(s)
        if p.price_auto:
            self.price_text = format_price(p.price_inr)

    def rig_name_slots(self) -> list[str]:
        """One name per rig (blank = "Rig N"), plus any names beyond the rig count, so they can be cleared."""
        p = self._need_profile()
        names = list(p.rig_names)
        n = max(min(max(p.rigs, 0), MAX_RIGS), len(names))
        return (names + [""] * n)[:n]

    def set_rig_name(self, index: int, text: str) -> None:
        """index 0 = Rig 1."""
        p = self._edit()
        names = list(p.rig_names)
        while len(names) <= index:
            names.append("")
        names[index] = text
        while names and not names[-1].strip():
            names.pop()
        p.rig_names = names

    def game_rows(self) -> list[tuple[str, str, bool]]:
        """(game id, name, ticked) for every game this version can read, then any unknown one in the profile."""
        p = self._need_profile()
        games = available_games()
        rows = [(gid, name, gid in p.games) for gid, name in games.items()]
        rows += [(gid, licence.game_name(gid), True) for gid in p.games if gid not in games]
        return rows

    def set_game(self, game_id: str, on: bool) -> None:
        p = self._edit()
        games = [g for g in p.games if g != game_id]
        if on:
            games.append(game_id)
        p.games = games

    # --- edits: Features ------------------------------------------------------------------------------------

    def feature_rows(self) -> list[tuple[str, str, bool, bool]]:
        """(flag, plain label, on, locked). Locked = a safety switch: always on, not a product."""
        p = self._need_profile()
        return [(name, feature_label(name), bool(p.features.get(name)) or name in SAFETY_FLAGS,
                 name in SAFETY_FLAGS) for name in FEATURES]

    def set_feature(self, name: str, on: bool) -> None:
        p = self._edit()
        if name in SAFETY_FLAGS or name not in FEATURES:
            return
        p.features = {**p.features, name: bool(on)}

    def apply_preset(self, preset: str) -> None:
        p = self._edit()
        try:
            p.apply_preset(preset)
        except ProfileError as exc:
            raise ControllerError(str(exc)) from None

    def preset_name(self) -> str:
        p = self._need_profile()
        return PRESET_NAMES.get(p.preset() or "", "Custom")

    # --- edits: Branding & price ----------------------------------------------------------------------------

    def set_variant(self, variant: str) -> None:
        """9T7 Racing fills the list price when no price was typed; unbranded drops an automatic price."""
        p = self._edit()
        if variant not in VARIANT_LABELS or variant == p.variant:
            return
        p.variant = variant
        if "price_inr" in self.field_errors:
            return                                     # the typed text stays until it is fixed
        if variant == "9t7" and p.price_inr is None:
            p.use_list_price()
        self.price_text = format_price(p.price_inr)

    def set_price_text(self, text: str) -> None:
        """The price as typed. Typing makes it the agreed price (a discount stays when the rigs change)."""
        p = self._edit()
        self.price_text = text
        try:
            value = parse_price(text)
        except ControllerError as exc:
            self.field_errors["price_inr"] = str(exc)
            return
        self.field_errors.pop("price_inr", None)
        if p.price_auto and value == p.price_inr:
            return                                     # the window re-sent the list price it shows
        p.set_price(value)

    def use_list_price(self) -> None:
        p = self._edit()
        p.use_list_price()
        self.field_errors.pop("price_inr", None)
        self.price_text = format_price(p.price_inr)

    def set_discount_note(self, text: str) -> None:
        self._edit().discount_note = text

    def price_lines(self) -> list[tuple[str, str]]:
        """The live price breakdown, as the certificate will show it: (label, amount) lines."""
        p = self._need_profile()
        inr = pricing.format_inr
        if "price_inr" in self.field_errors:
            return []
        if p.price_inr is None or p.price_inr < 0 or not 1 <= p.rigs <= MAX_RIGS:
            lp = p.list_price()
            return [("List price", inr(lp))] if lp is not None else []
        b = pricing.breakdown(p.rigs, p.price_inr, p.variant)
        if b.base is None:
            return [("Agreed price", inr(b.total))]
        up_to = "up to " if p.rigs < (b.base_rigs or 0) else ""
        rigs = f"{b.base_rigs} rig{'s' if b.base_rigs != 1 else ''}"
        lines = [(f"Licence, including {up_to}{rigs}", inr(b.base))]
        if b.extra_rigs:
            lines.append((f"{b.extra_rigs} extra rig{'s' if b.extra_rigs != 1 else ''} at "
                          f"{inr(b.extra_rig_price)} each", inr(b.extra_total)))
        if b.other:
            lines.append(("Other add-ons", inr(b.other)))
        if b.discount:
            lines.append(("Discount", "−" + inr(b.discount)))
        lines.append(("Total", inr(b.total)))
        return lines

    def price_note(self) -> str:
        p = self._need_profile()
        if p.variant == "unbranded":
            return "Unbranded: type the agreed price (there is no list price)."
        if p.price_auto:
            return "List price for this number of rigs. Type another price for a discount."
        lp = p.list_price()
        return f"Typed price. The list price is {pricing.format_inr(lp)}." if lp is not None else "Typed price."

    def history_lines(self, limit: int = 5) -> list[str]:
        p = self._need_profile()
        kinds = {"build": "Package", "rebuild": "Rebuilt package", "upgrade": "Upgrade code"}
        out = []
        for h in sorted(p.history, key=lambda h: h.seq, reverse=True)[:limit]:
            price = f", {pricing.format_inr(h.price_inr)}" if h.price_inr is not None else ""
            out.append(f"{h.date.isoformat()}: {kinds.get(h.kind, h.kind)}, licence number {h.seq}, "
                       f"version {h.pitwall_version}{price}")
        return out

    # --- problems --------------------------------------------------------------------------------------------

    def problems(self) -> dict[str, list[str]]:
        """Plain-English problems by profile field (for the labels next to the fields)."""
        if self.profile is None:
            return {}
        out: dict[str, list[str]] = {}
        for f, msg in self.field_errors.items():
            out.setdefault(f, []).append(msg)
        for f, msg in self.store.problems(self.profile):
            if f in self.field_errors:
                continue                           # the typed text is the problem; the old value isn't shown
            out.setdefault(f, [])
            if msg not in out[f]:
                out[f].append(msg)
        return out

    def problems_flat(self) -> list[str]:
        return [m for msgs in self.problems().values() for m in msgs]

    def tab_problems(self) -> dict[str, int]:
        """How many problems each tab has (the window marks the tab's title)."""
        counts = {t: 0 for t in TABS}
        for f, msgs in self.problems().items():
            counts[FIELD_TAB.get(f, "Cafe")] += len(msgs)
        return counts

    def tab_title(self, tab: str) -> str:
        n = self.tab_problems().get(tab, 0)
        return f"{tab} ({n} to fix)" if n else tab

    # --- keys -------------------------------------------------------------------------------------------------

    def refresh_keys(self) -> KeyStatus:
        st = KeyStatus()
        b = self.backend
        folder = self.settings.keys_dir
        try:
            st.has_keys = bool(b.has_keys(folder))
        except OSError:
            st.has_keys = False
        if st.has_keys:
            try:
                k = b.load_private(folder)
                st.fingerprint = k.fingerprint
                try:
                    st.trusted = k.public in tuple(b.trusted_keys(self.settings))
                except (KeysError, OSError):
                    st.trusted = False
                state = b.backup_state(folder)
                if state is not None:
                    st.backed_up, st.backed_up_to, st.backed_up_on = True, state.backed_up_to, state.date
            except KeysError as exc:
                st.problem = str(exc)
        self.keys = st
        return st

    def banner(self) -> tuple[str, list[str]] | None:
        """(the red banner's text, its buttons) or None. Shown until the key is made, known and backed up."""
        k = self.keys
        if k.problem:
            return k.problem, ["Settings"]
        if not k.has_keys:
            return BANNER_NO_KEYS, ["Set up keys"]
        if not k.trusted:
            buttons = ["Set up keys"] + ([] if k.backed_up else ["Copy key to…"])
            return BANNER_NOT_TRUSTED, buttons
        if not k.backed_up:
            return BANNER_BACKUP, ["Copy key to…"]
        return None

    def key_summary(self) -> str:
        """For the Settings window's key backup section."""
        k = self.keys
        if k.problem:
            return k.problem
        if not k.has_keys:
            return "No signing key yet. Press Set up keys."
        lines = [f"Signing key {k.fingerprint}, kept in {self.settings.key_folder}."]
        lines.append("It is in this copy of the program." if k.trusted
                     else "It isn't in this copy of the program yet: press Set up keys.")
        if k.backed_up:
            lines.append(f"Last copied to {k.backed_up_to} on {k.backed_up_on.isoformat()}.")
        else:
            lines.append("Not backed up yet: press Copy key to… and choose a USB drive.")
        lines.append(LOST_KEY)
        return "\n".join(lines)

    def setup_keys(self) -> str:
        """First-run "Set up keys": make the key pair (if there is none) and add its public half to the hub's
        source (hub/simtelemetry/licence_pubkey.py). Returns the plain explanation for a message box."""
        self._idle()
        b = self.backend
        folder = self.settings.keys_dir
        made = False
        try:
            if b.has_keys(folder):
                keys = b.load_private(folder)
            else:
                keys = b.create_keys(folder, forbidden=[self.settings.shipments, self.settings.repo_root])
                made = True
            module = b.write_public_key_py(self.settings.repo_root, keys)
        except KeysError as exc:
            self.refresh_keys()
            raise ControllerError(str(exc)) from None
        self.refresh_keys()
        self.status = "Signing key ready. Back it up next." if not self.keys.backed_up else "Signing key ready."
        try:
            shown = Path(module).relative_to(self.settings.repo_root)
        except ValueError:
            shown = Path(module)
        return (SETUP_DONE if made else SETUP_ALREADY).format(fingerprint=keys.fingerprint, module=shown)

    def copy_key_to(self, folder: Path) -> str:
        """"Copy key to…": copy the key pair into the chosen folder (a USB drive), never the repo or Shipments."""
        self._idle()
        try:
            state = self.backend.copy_backup(Path(folder), folder=self.settings.keys_dir,
                                             forbidden=[self.settings.repo_root, self.settings.shipments])
        except KeysError as exc:
            raise ControllerError(str(exc)) from None
        self.refresh_keys()
        self.status = "Signing key backed up."
        return (f"Your signing key was copied to {state.backed_up_to}. Keep that drive somewhere safe, away from "
                "this PC. Anyone with the key can make licences.")

    # --- settings ----------------------------------------------------------------------------------------------

    def edge_text(self) -> str:
        try:
            found = self.backend.find_edge(self.settings.edge)
        except docs.DocsError:
            return "Microsoft Edge wasn't found. Choose msedge.exe."
        return f"Using {found}."

    def update_settings(self, shipments: str, edge: str) -> None:
        """Settings window → Save. The open cafe must be saved (or dropped) first: the list changes folder."""
        self._idle()
        s = shipments.strip()
        if not s:
            raise ControllerError("Choose a Shipments folder.")
        new = replace(self.settings, shipments=Path(s), edge=Path(edge.strip()) if edge.strip() else None,
                      load_problem=None)
        problems = new.problems()
        if problems:
            raise ControllerError(problems[0])
        try:
            new.save(self.settings_file)
        except BuildError as exc:
            raise ControllerError(exc.message) from None
        moved = Path(s) != self.settings.shipments
        self.settings = new
        if moved:
            self.profile = self.path = None
            self._saved = None
            self.field_errors = {}
        self.refresh_list()
        self.refresh_keys()
        self.status = "Settings saved."

    def shipments_folder(self) -> Path:
        return self.settings.shipments

    def open_shipments(self) -> None:
        folder = self.settings.shipments
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ControllerError(f"The Shipments folder {folder} can't be made. Choose another one in "
                                  "Settings.") from None
        self.opener(folder)

    # --- which buttons work ---------------------------------------------------------------------------------

    def _key_reason(self) -> str:
        k = self.keys
        if k.problem:
            return k.problem
        if not k.has_keys:
            return "Set up keys first."
        if not k.trusted:
            return "Finish Set up keys first: your key isn't in the program yet."
        return ""

    def _ready_reason(self) -> str:
        if self.profile is None:
            return NO_CAFE
        if self.field_errors or self.problems():
            return "Fix the marked fields first."
        return ""

    def actions(self) -> dict[str, Action]:
        busy = self.job is not None
        out: dict[str, Action] = {}
        ready = self._ready_reason()
        key = self._key_reason()
        settings = (self.settings.problems() or [""])[0]
        edge = ""
        try:
            self.backend.find_edge(self.settings.edge)
        except docs.DocsError as exc:
            edge = str(exc)

        def act(*reasons: str, label: str = "") -> Action:
            if busy:
                return Action(False, BUSY, label)
            r = next((x for x in reasons if x), "")
            return Action(not r, r, label)

        out["new"] = act()
        out["save"] = act("" if self.profile is not None else NO_CAFE,
                          "" if self.dirty else "Nothing to save.")
        if self.preview is not None:
            out["preview"] = Action(not busy, BUSY if busy else "", "Stop preview")
        else:
            out["preview"] = act(ready, label="Preview")
        video = ""
        if self.profile is not None:
            video = self.backend.video_problem(self.settings, self.profile.variant) or ""
        previewing = STOP_PREVIEW_FIRST if self.preview is not None else ""
        out["build"] = act(ready, settings, key, edge, video, previewing)
        upgrade = ""
        if not ready:
            if not self.profile.history:
                upgrade = "This cafe has no package yet. Use Build package first."
            else:
                try:
                    self.backend.upgrade_plan(self.profile, 0)
                except ProfileError as exc:
                    upgrade = str(exc)
        out["upgrade"] = act(ready, upgrade, settings, key, edge)
        built = any(e.profile is not None and e.profile.history for e in self.entries)
        out["rebuild"] = act("" if built else "No cafe has a package yet.", settings, key, edge, previewing)
        out["shipments"] = Action(True)
        out["settings"] = act()
        out["setup_keys"] = act()
        out["copy_key"] = act("" if self.keys.has_keys and not self.keys.problem else "Set up keys first.")
        out["cancel"] = Action(busy and self.job.cancellable and not self.job.cancelling,
                               "" if busy else "Nothing is running.")
        return out

    def hint(self) -> str:
        """One line under the buttons: what stops a build, or that the cafe is ready."""
        if self.job is not None:
            return self.job.text or self.job.title
        a = self.actions()["build"]
        if self.profile is None:
            return NO_CAFE
        return "Ready to build." if a.enabled else f"Build package: {a.reason}"

    # --- jobs --------------------------------------------------------------------------------------------------

    def _start(self, kind: str, title: str, work: Callable[[threading.Event, Callable[..., None]], Any], *,
               total: int = 0, cancellable: bool = True) -> JobState:
        self._idle()
        job = JobState(kind=kind, title=title, cancel=threading.Event(), total=total, text=title,
                       cancellable=cancellable, cafe_id=self.profile.cafe_id if self.profile is not None else None)
        q = self._queue

        def progress(done: int, total_: int, text: str) -> None:
            q.put(("progress", done, total_, text))

        def run() -> None:
            try:
                result = work(job.cancel, progress)
            except BaseException as exc:                  # every outcome reaches the window
                q.put(("error", exc, traceback.format_exc()))
            else:
                q.put(("done", result, ""))

        job.thread = threading.Thread(target=run, name=f"factory-{kind}", daemon=True)
        try:
            job.thread.start()
        except RuntimeError:                          # no thread could be started: nothing is running
            log.error("couldn't start the %s job", kind, exc_info=True)
            raise ControllerError("The job couldn't be started. Close other programs and try again.") from None
        self.job = job
        self.status = title
        return job

    def cancel_job(self) -> None:
        job = self.job
        if job is None or not job.cancellable:
            return
        job.cancel.set()
        job.cancelling = True
        job.text = "Cancelling… (cleaning up)"
        self.status = job.text

    def join(self, timeout: float | None = None) -> bool:
        """Wait for the worker (tests, and closing the window). True when it has ended."""
        job = self.job
        if job is None or job.thread is None:
            return True
        job.thread.join(timeout)
        return not job.thread.is_alive()

    def _keys_for_job(self) -> Keys:
        try:
            return self.backend.load_private(self.settings.keys_dir)
        except KeysError as exc:
            raise ControllerError(str(exc)) from None

    def _save_for_job(self) -> CafeProfile:
        """Jobs record history in the cafe's file, so unsaved edits are saved first (never lost or overwritten)."""
        p = self._need_profile()
        if self.dirty:
            self.save()
        return p.model_copy(deep=True)

    def start_build(self) -> JobState:
        a = self.actions()["build"]
        if not a.enabled:
            raise ControllerError(a.reason)
        profile = self._save_for_job()
        keys = self._keys_for_job()
        settings, store, fn, today = self.settings, self.store, self.backend.build_package, self.today()
        name = profile.name.strip()
        return self._start("build", f"Building the package for {name}…",
                           lambda cancel, progress: fn(profile, settings, None, keys, cancel, progress, store=store,
                                                       today=today),
                           total=len(BUILD_STEPS))

    def upgrade_default_price(self) -> tuple[int | None, str]:
        """(the price to suggest, the question) for Issue upgrade's price box."""
        p = self._need_profile()
        try:
            _, price = self.backend.upgrade_plan(p, None)
            return price, f"Price of the add-ons in rupees (the list price is {pricing.format_inr(price)}):"
        except ProfileError:
            return None, "Price of the add-ons in rupees:"

    def start_upgrade(self, price_text: str) -> JobState:
        a = self.actions()["upgrade"]
        if not a.enabled:
            raise ControllerError(a.reason)
        price = parse_price(price_text)
        try:
            self.backend.upgrade_plan(self._need_profile(), price)
        except ProfileError as exc:
            raise ControllerError(str(exc)) from None
        profile = self._save_for_job()
        keys = self._keys_for_job()
        settings, store, fn, today = self.settings, self.store, self.backend.issue_upgrade, self.today()
        return self._start("upgrade", f"Making the upgrade code for {profile.name.strip()}…",
                           lambda cancel, progress: fn(profile, settings, keys, None, price, cancel, progress,
                                                       store=store, today=today),
                           total=len(build.UPGRADE_STEPS))

    def start_rebuild_all(self) -> JobState:
        a = self.actions()["rebuild"]
        if not a.enabled:
            raise ControllerError(a.reason)
        if self.profile is not None and self.dirty:
            self.save()
        keys = self._keys_for_job()
        settings, store, fn, today = self.settings, self.store, self.backend.rebuild_all, self.today()
        return self._start("rebuild", "Rebuilding every cafe's package…",
                           lambda cancel, progress: fn(store, settings, None, keys, cancel, progress, today=today),
                           total=1)

    def toggle_preview(self) -> JobState:
        """Preview, or Stop preview while one runs. Both run in the worker (starting takes a few seconds)."""
        if self.preview is not None:
            return self.stop_preview()
        a = self.actions()["preview"]
        if not a.enabled:
            raise ControllerError(a.reason)
        profile = self._need_profile().model_copy(deep=True)
        try:
            keys = self.backend.load_private(self.settings.keys_dir) if self.keys.has_keys else None
        except KeysError:
            keys = None
        settings, store, fn = self.settings, self.store, self.backend.start_preview
        self.preview_cafe = profile.name.strip()

        def work(cancel: threading.Event, progress: Callable[..., None]) -> Any:
            progress(0, 0, f"Starting the preview of {profile.name.strip()}… (this takes a few seconds)")
            pv = fn(profile, settings, keys, store=store)
            if cancel.is_set():                          # cancelled while starting: stop it straight away
                pv.stop()
                raise BuildCancelled("The preview was cancelled.")
            return pv

        return self._start("preview", "Starting the preview…", work)

    def stop_preview(self) -> JobState:
        pv = self.preview
        if pv is None:
            raise ControllerError("No preview is running.")
        job = self._start("stop_preview", "Stopping the preview…", lambda cancel, progress: pv.stop(),
                          cancellable=False)
        self.preview = None
        return job

    def shutdown(self) -> None:
        """The window is closing: end a preview now (it also ends at exit)."""
        pv, self.preview = self.preview, None
        if pv is not None:
            self.shutdown_preview(pv)

    @staticmethod
    def shutdown_preview(pv: Any) -> None:
        """Stop a preview here and now (on the window's thread)."""
        try:
            pv.stop()
        except Exception:
            log.warning("couldn't stop the preview", exc_info=True)

    def close_prompt(self) -> str | None:
        """Why the window shouldn't close yet, or None."""
        if self.job is not None:
            if not self.job.cancellable:
                return "The factory is finishing a job. Wait a moment, then close it."
            return "A job is still running. Press Cancel and wait for it to stop, then close the factory."
        return None

    # --- the window's after() loop ---------------------------------------------------------------------------

    def poll(self) -> list[Notice]:
        """Apply what the worker reported (call from the window's thread). Returns notices to show."""
        notices: list[Notice] = []
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            job = self.job
            if job is None:
                continue
            if kind == "progress":
                _, done, total, text = event
                job.done, job.total = done, total
                if not job.cancelling:
                    job.text = text
                    self.status = text
            else:
                self.job = None
                try:
                    notices.extend(self._finish(job, event[1], event[2], ok=kind == "done"))
                except Exception:                 # never lose the outcome: say so, with the details
                    trace = traceback.format_exc()
                    log.error("finishing the %s job failed:\n%s", job.kind, trace)
                    self.status = "Something went wrong at the end of the job."
                    notices.append(Notice("error", "Factory", "Something went wrong at the end of the job. "
                                          "Check the Shipments folder; Show details has what happened.",
                                          details=trace))
        if self.preview is not None and self.job is None and not self.preview.running:
            pv, self.preview = self.preview, None
            self.status = "The preview has stopped."
            try:
                self._start("stop_preview", "Cleaning up the preview…", lambda c, p: pv.stop(), cancellable=False)
            except ControllerError:
                self.shutdown_preview(pv)
        return notices

    def _finish(self, job: JobState, result: Any, trace: str, ok: bool) -> list[Notice]:
        if job.kind in ("build", "upgrade", "rebuild"):
            self._reload_after_job(job)
        if not ok:
            return [self._error_notice(job, result, trace)]
        if job.kind == "build":
            self.status = f"Package saved: {result.path.name}"
            self.opener(result.path)
            return [Notice("info", "Package ready",
                           f"The package for {self._name_for(job)} is ready, in:\n{result.path}\n\n"
                           "Send the whole folder to the cafe.", details=result.details, folder=result.path)]
        if job.kind == "upgrade":
            self.status = f"Upgrade code saved: {result.folder.name}"
            self.opener(result.folder)
            return [Notice("upgrade", "Upgrade code ready",
                           f"Send this code to {self._name_for(job)}. The owner pastes it into the Licence card's "
                           "\"Enter new code\" box on the owner page and presses \"Use this code\". The upgrade "
                           f"certificate ({pricing.format_inr(result.price_inr)}) is in:\n{result.folder}",
                           details=result.details, code=self.upgrade_copy_text(result), folder=result.folder)]
        if job.kind == "rebuild":
            rows = self.rebuild_rows(result)
            ok_n = sum(1 for r in result if r.status == "ok")
            self.status = f"Rebuild all: {ok_n} of {len(result)} built."
            details = "\n\n".join(f"== {r.cafe}\n{r.details}" for r in result if r.details)
            return [Notice("rebuild", "Rebuild all", self.status, details=details, rows=rows,
                           folder=self.settings.shipments)]
        if job.kind == "preview":
            self.preview = result
            self.status = f"Preview of {self.preview_cafe} is open. Press Stop preview when you're done."
            notes = list(getattr(result, "notes", []) or [])
            return [Notice("info", "Preview", "\n\n".join(["The preview windows are opening."] + notes),
                           details=getattr(result, "details", ""))]
        if job.kind == "stop_preview":
            self.status = "Preview stopped."
        return []

    def _name_for(self, job: JobState) -> str:
        if self.profile is not None and self.profile.cafe_id == job.cafe_id:
            return self.profile.name.strip() or "the cafe"
        return "the cafe"

    def _reload_after_job(self, job: JobState) -> None:
        """A build wrote the cafe's history to its file: read it back (the form was locked meanwhile)."""
        self.refresh_list()
        if self.profile is None or (job.kind != "rebuild" and self.profile.cafe_id != job.cafe_id):
            return
        path = self.store.find(self.profile.cafe_id)
        if path is None:
            return
        try:
            self._open(load(path), path)
        except ProfileError:
            pass

    def _error_notice(self, job: JobState, exc: BaseException, trace: str) -> Notice:
        titles = {"build": "Build package", "upgrade": "Issue upgrade", "rebuild": "Rebuild all",
                  "preview": "Preview", "stop_preview": "Stop preview"}
        title = titles.get(job.kind, "Factory")
        if isinstance(exc, BuildCancelled):
            self.status = exc.message
            return Notice("info", title, exc.message, details=exc.details)
        if isinstance(exc, (BuildError, PreviewError)):
            self.status = f"{title} stopped."
            return Notice("error", title, exc.message, details=exc.details)
        if isinstance(exc, (ProfileError, KeysError, ControllerError, docs.DocsError)):
            self.status = f"{title} stopped."
            return Notice("error", title, str(exc))
        log.error("%s failed:\n%s", title, trace)
        self.status = f"{title} stopped."
        return Notice("error", title, "Something went wrong. Try again; Show details has what happened.",
                      details=trace)

    # --- results for the window ------------------------------------------------------------------------------

    @staticmethod
    def upgrade_copy_text(result: Any) -> str:
        """What the Copy button puts on the clipboard: the code alone, as the owner page wants it."""
        return result.code.strip()

    @staticmethod
    def rebuild_rows(rows: list[Any]) -> list[tuple[str, str, str, str]]:
        """(cafe, result, message, package folder) for the Rebuild all table."""
        labels = {"ok": "Built", "failed": "Failed", "skipped": "Skipped"}
        return [(r.cafe, labels.get(r.status, r.status), r.message, r.package.name if r.package else "")
                for r in rows]

    @staticmethod
    def accent_swatches() -> tuple[str, ...]:
        return ACCENT_SWATCHES

    @staticmethod
    def variant_choices() -> list[tuple[str, str, str]]:
        return [(v, VARIANT_LABELS[v], VARIANT_NOTES[v]) for v in ("9t7", "unbranded")]
