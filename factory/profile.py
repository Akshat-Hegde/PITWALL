"""The cafe profile (spec 2.1): one JSON file per cafe, the form the factory edits and builds from.

Files (the Shipments folder is chosen in the factory's settings, outside the repo):

    <Shipments>/profiles/<slug>.json             one CafeProfile per cafe
    <Shipments>/profiles/logos/<cafe_id>-<hash>.<ext>   the cafe's logo, copied in by `ProfileStore.import_logo`

`logo` in the profile is that file's name (no folders), so the Shipments folder can be moved or copied whole.
The logo is named by cafe_id, not slug, so renaming a cafe never loses it.

A profile can be saved half filled (a draft): the model only checks types. `problems()` lists what still needs
fixing, in plain English, keyed by field; a package can't be built, nor a licence issued, while there is any.

Two dicts leave the factory, and neither ever holds the seller's `contact` records:
- `licence_payload(seq, licence_id, issued)`: simtelemetry.licence's signed payload;
- `baked_profile()`: simtelemetry.provision.BakedProfile, the installer's profile.json.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from simtelemetry import adapters, brand, licence
from simtelemetry.api.setup import MAX_LOGO_BYTES
from simtelemetry.config import FeaturesConfig
from simtelemetry.core.hours import hours_problem
from simtelemetry.core.rigs import RIG_NAME_MAX, RigError, clean_rig_name
from simtelemetry.core.settings import ACCENT_SWATCHES
from simtelemetry.provision import MAX_RIGS, BakedProfile, logo_kind, write_atomic

from . import pricing

PROFILE_VERSION = 1
NAME_MAX = 40
TAGLINE_MAX = 60
NOTE_MAX = 200
CONTACT_MAX = 80
SLUG_MAX = 40                     # build.ps1 allows 60; leaves room for a "-<id>" suffix
FILE_NAME_MAX = 60
PROFILES_DIR = "profiles"
LOGOS_DIR = "logos"
DEFAULT_ACCENT = ACCENT_SWATCHES[0]

# build.ps1's -CafeSlug check, and the installer's file name pitwall.iss makes from it.
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,59}$")
_CAFE_ID_RE = re.compile(r"^c-[0-9a-f]{16}$")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_RIG_N = re.compile(r"rig\s*0*(\d+)", re.IGNORECASE)
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
# Windows also reserves COM¹ COM² COM³ and LPT¹ LPT² LPT³ (superscript digits).
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL",
                 *(f"{p}{i}" for p in ("COM", "LPT") for i in (*range(1, 10), "¹", "²", "³"))}
# Latin letters NFKD can't split into an ASCII letter and an accent: "Straße" -> "Strasse", not "Strae".
_TRANSLIT = str.maketrans({"ß": "ss", "ẞ": "SS", "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "Ø": "O",
                           "ø": "o", "Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "Þ": "Th", "þ": "th", "ı": "i"})

# --- features and presets ------------------------------------------------------------------------

FEATURES: tuple[str, ...] = tuple(FeaturesConfig.model_fields)      # follows hub.toml [features] automatically
# Hub-side safety switches (closing-time session end, backup warning): not products, never in a licence's say, and
# never switched off by a preset.
SAFETY_FLAGS = licence.NOT_LICENSED_FLAGS

# BASIC switches off the extras a small cafe can buy later as add-ons. All five are real FeaturesConfig flags
# (checked below and by a test): events (corporate events: teams, team board, company branding), head_to_head (the
# head-to-head view), owner (the owner page's business figures; the licence card and backups stay, C3), challenges
# (weekly challenges) and race_podium (race podium and race cards). None of them is a safety flag.
BASIC_OFF = frozenset({"events", "head_to_head", "owner", "challenges", "race_podium"})
assert BASIC_OFF <= set(FEATURES) and not BASIC_OFF & SAFETY_FLAGS

PRESETS: dict[str, dict[str, bool]] = {
    "full": {name: True for name in FEATURES},
    "basic": {name: name not in BASIC_OFF for name in FEATURES},
}
PRESET_NAMES = {"full": "Full", "basic": "Basic"}


def feature_defaults() -> dict[str, bool]:
    return {name: bool(f.default) for name, f in FeaturesConfig.model_fields.items()}


def available_games() -> dict[str, str]:
    """Game id -> name for every game this version can read (the hub's adapters): only these can be chosen."""
    return {gid: licence.game_name(gid) for gid in adapters.registry()}


def new_cafe_id() -> str:
    return "c-" + secrets.token_hex(8)


class ProfileError(ValueError):
    """Something the seller has to fix; the message is plain English for the factory window."""


# --- the model -----------------------------------------------------------------------------------

class _Part(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class Wifi(_Part):
    ssid: str = ""
    password: str = ""
    security: Literal["WPA", "nopass"] = "WPA"


class Hours(_Part):
    open_hour: int = 10
    close_hour: int = 22


class Contact(_Part):
    """The seller's own records. Never baked into the installer and never in a licence."""
    name: str = ""
    phone: str = ""
    city: str = ""


class HistoryEntry(_Part):
    """One per build or upgrade code, appended by the factory (C10)."""
    kind: Literal["build", "upgrade"] = "build"
    pitwall_version: str
    licence_id: str
    seq: int
    date: dt.date
    price_inr: int | None = None
    package: str = ""             # the package folder ("" for an upgrade code without a package)
    rigs: int | None = None       # what that licence covered, so an upgrade can list only the add-ons
    games: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)


class CafeProfile(BaseModel):
    """A cafe, as the seller fills it in. Types only; `problems()` says what's missing or wrong."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    v: int = PROFILE_VERSION
    cafe_id: str = Field(default_factory=new_cafe_id)
    name: str = ""
    tagline: str = ""
    logo: str | None = None                  # a file name in <profiles>/logos
    accent: str = DEFAULT_ACCENT
    wifi: Wifi | None = None
    hours: Hours | None = None
    rigs: int = pricing.BASE_RIGS
    rig_names: list[str] = Field(default_factory=list)
    games: list[str] = Field(default_factory=lambda: list(adapters.registry()))
    features: dict[str, bool] = Field(default_factory=lambda: dict(PRESETS["full"]))
    variant: Literal["9t7", "unbranded"] = "9t7"
    price_inr: int | None = None
    price_auto: bool = True                  # 9t7: the price follows the rig count until the seller types one
    discount_note: str = ""
    contact: Contact = Field(default_factory=Contact)
    history: list[HistoryEntry] = Field(default_factory=list)

    @field_validator("features", mode="before")
    @classmethod
    def _sync_features(cls, value: Any) -> dict[str, bool]:
        """Exactly FeaturesConfig's flags: a flag new in this version gets its default, one that no longer exists
        is dropped, so a profile saved by an older factory stays in step with hub.toml [features]."""
        given = value if isinstance(value, dict) else {}
        return {name: given[name] if isinstance(given.get(name), bool) else default
                for name, default in feature_defaults().items()}

    @field_validator("rig_names", mode="before")
    @classmethod
    def _names(cls, value: Any) -> list[str]:
        return ["" if n is None else n for n in value] if isinstance(value, list) else value

    @model_validator(mode="after")
    def _price(self) -> "CafeProfile":
        if self.variant == "unbranded" and self.price_auto:
            # An unbranded price has no default: an automatic (never typed) price is dropped.
            object.__setattr__(self, "price_auto", False)
            object.__setattr__(self, "price_inr", None)
        elif self.variant == "9t7" and self.price_auto and 1 <= self.rigs <= MAX_RIGS:
            object.__setattr__(self, "price_inr", pricing.retail_price(self.rigs))
        return self

    # --- creating and editing --------------------------------------------------------------------

    @classmethod
    def new(cls, name: str = "", variant: Literal["9t7", "unbranded"] = "9t7", rigs: int = pricing.BASE_RIGS,
            preset: str = "full") -> "CafeProfile":
        """A new cafe: a fresh cafe_id, F1 25 (every game this version reads), the preset's features and, for the
        9t7 variant, the list price."""
        p = cls(name=name, variant=variant, rigs=rigs, price_auto=variant == "9t7")
        p.apply_preset(preset)
        return p

    def apply_preset(self, preset: str) -> None:
        """FULL or BASIC. The safety flags (SAFETY_FLAGS) are on in both and are never switched off by a preset."""
        if preset not in PRESETS:
            raise ProfileError(f"There is no preset called {preset!r}.")
        self.features = {**PRESETS[preset], **{f: True for f in SAFETY_FLAGS if f in FEATURES}}

    def preset(self) -> str | None:
        """'full' or 'basic' when the features are exactly that preset, else None (custom)."""
        return next((k for k, v in PRESETS.items() if v == self.features), None)

    def set_price(self, price_inr: int | None) -> None:
        """The seller typed a price: it stays as typed (a discount), even if the rigs change later."""
        self.price_auto = False
        self.price_inr = price_inr

    def use_list_price(self) -> None:
        """Back to the automatic list price (9t7 only; unbranded has no list price)."""
        if self.variant == "9t7":
            self.price_auto = True
            self.price_inr = pricing.retail_price(self.rigs) if 1 <= self.rigs <= MAX_RIGS else None

    def list_price(self) -> int | None:
        if self.variant != "9t7" or not 1 <= self.rigs <= MAX_RIGS:
            return None
        return pricing.retail_price(self.rigs)

    def price_breakdown(self) -> pricing.Breakdown:
        if self.price_inr is None or not 1 <= self.rigs <= MAX_RIGS:
            raise ProfileError("Enter the price first.")
        return pricing.breakdown(self.rigs, self.price_inr, self.variant)

    def features_on(self) -> list[str]:
        return [name for name in FEATURES if self.features.get(name)]

    def next_seq(self) -> int:
        """The seq for this cafe's next licence: one more than any in the history (1 for the first)."""
        return max((h.seq for h in self.history), default=0) + 1

    # --- checks ----------------------------------------------------------------------------------

    def problems(self, logo_dir: Path | None = None) -> list[tuple[str, str]]:
        """(field, plain-English message) for everything that stops a build; [] when the profile is ready.

        With `logo_dir` (the profiles' logos folder; `ProfileStore.problems` passes it) the logo file itself is
        checked too: it must be there, a PNG, JPEG or WebP picture, and under 1 MB.
        """
        out: list[tuple[str, str]] = []
        add = lambda field, message: out.append((field, message))          # noqa: E731

        if not _CAFE_ID_RE.match(self.cafe_id):
            add("cafe_id", "This cafe's id is damaged. Make the cafe again with New cafe.")
        name = self.name.strip()
        if not name:
            add("name", "Enter the cafe's name.")
        elif len(name) > NAME_MAX:
            add("name", f"The cafe name can be at most {NAME_MAX} characters.")
        elif _CTRL.search(name):
            add("name", "The cafe name must be one line of text.")
        tagline = self.tagline.strip()
        if len(tagline) > TAGLINE_MAX:
            add("tagline", f"The tagline can be at most {TAGLINE_MAX} characters.")
        elif _CTRL.search(tagline):
            add("tagline", "The tagline must be one line of text.")

        if self.logo is not None:
            msg = _logo_name_problem(self.logo)
            if msg is None and logo_dir is not None:
                msg = logo_file_problem(Path(logo_dir) / self.logo)
            if msg:
                add("logo", msg)
        if not _HEX.match(self.accent):
            add("accent", "Choose an accent colour.")

        if self.wifi is not None:
            out.extend(("wifi", m) for m in _wifi_problems(self.wifi))
        if self.hours is not None:
            h = self.hours
            if not (0 <= h.open_hour <= 23 and 0 <= h.close_hour <= 24):
                add("hours", "Choose an opening and a closing time.")
            else:
                problem = hours_problem(h.open_hour, h.close_hour)
                if problem:
                    add("hours", problem[:1].upper() + problem[1:] + ".")

        if not 1 <= self.rigs <= MAX_RIGS:
            add("rigs", f"Choose 1 to {MAX_RIGS} rigs.")
        else:
            out.extend(("rig_names", m) for m in self._rig_name_problems())

        games = available_games()
        if not self.games:
            add("games", "Choose at least one game.")
        for gid in self.games:
            if gid not in games:
                add("games", f"{licence.game_name(gid)} isn't a game this version of {brand.PRODUCT_NAME} can "
                             "read. Untick it.")
        if len(set(self.games)) != len(self.games):
            add("games", "A game is listed twice.")

        if self.price_inr is None:
            add("price_inr", "An unbranded build needs a price." if self.variant == "unbranded"
                else "Enter the price.")
        elif self.price_inr < 0:
            add("price_inr", "The price can't be less than ₹0.")
        if len(self.discount_note) > NOTE_MAX:
            add("discount_note", f"The discount note can be at most {NOTE_MAX} characters.")
        for key, label in (("name", "contact's name"), ("phone", "contact's phone number"), ("city", "city")):
            if len(getattr(self.contact, key)) > CONTACT_MAX:
                add("contact", f"The {label} can be at most {CONTACT_MAX} characters.")

        if not out:
            # A last check with the hub's own models, so the factory can never build what a cafe PC would refuse.
            try:
                baked = BakedProfile.model_validate(self.baked_profile())
                baked.settings()
                licence.check_payload(licence.encode_payload(
                    self.licence_payload(seq=max(1, self.next_seq()), licence_id="check", issued=dt.date.today())))
            except (ValidationError, licence.LicenceError, ValueError):
                add("name", "Some of these details can't be used. Check every tab, or make the cafe again.")
        return out

    def _rig_name_problems(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for number, raw in enumerate(self.rig_names, 1):
            try:
                name = clean_rig_name(raw)
            except RigError:
                out.append(f"Rig {number}'s name can be at most {RIG_NAME_MAX} characters.")
                continue
            if not name:
                continue
            if number > self.rigs:
                out.append(f"Rig {number} has a name, but the cafe has {self.rigs} "
                           f"rig{'s' if self.rigs != 1 else ''}. Clear the name or add rigs.")
                continue
            m = _RIG_N.fullmatch(name)
            if m and int(m.group(1)) != number:
                out.append(f'Rig {number} can\'t be called "{name}": that is another rig\'s number.')
            elif name.casefold() in seen:
                out.append(f'Two rigs are called "{name}". Give each rig its own name.')
            seen.add(name.casefold())
        return out

    def ready(self, logo_dir: Path | None = None) -> bool:
        return not self.problems(logo_dir)

    # --- what leaves the factory (never `contact`) -------------------------------------------------

    def licence_payload(self, seq: int, licence_id: str, issued: dt.date) -> dict[str, Any]:
        """The licence's signed payload (simtelemetry.licence.LicencePayload); `features` lists the flags that are
        on. Sign `licence.encode_payload(...)` of it. No contact details."""
        return {"v": 1, "licence_id": licence_id, "cafe_id": self.cafe_id, "cafe_name": self.name.strip(),
                "rigs": self.rigs, "games": list(dict.fromkeys(self.games)), "features": self.features_on(),
                "variant": self.variant, "issued": issued.isoformat(), "seq": seq}

    def baked_logo_name(self) -> str | None:
        """The logo's file name in the installer's baked folder ("logo.png"), or None without a logo."""
        if not self.logo:
            return None
        return "logo" + Path(self.logo).suffix.lower()

    def baked_profile(self) -> dict[str, Any]:
        """The installer's profile.json: exactly simtelemetry.provision.BakedProfile. No contact details, no price.

        `features` writes every licensed feature as **on** (the safety flags as set): the licence alone keeps the
        features the cafe didn't buy off, so an add-on code that adds one later switches it on with no reinstall
        (spec F3). Writing false, or leaving a flag out (an old hub.toml kept from an earlier install could hold
        `owner = false`), could hide it even after the cafe bought it, and `owner = false` closes the owner page
        where add-on codes are entered.
        """
        names: list[str | None] = [clean_rig_name(n) if _fits(n) else n for n in self.rig_names[:self.rigs]]
        while names and not names[-1]:
            names.pop()
        rig_names: list[str | None] = []
        for number, name in enumerate(names, 1):
            m = _RIG_N.fullmatch(name) if name else None
            rig_names.append(None if not name or (m and int(m.group(1)) == number) else name)
        wifi = self.wifi if self.wifi is not None and self.wifi.ssid.strip() else None
        return {
            "v": 1,
            "cafe_id": self.cafe_id,
            "name": self.name.strip(),
            "tagline": self.tagline.strip(),
            "logo": self.baked_logo_name(),
            "accent": self.accent.upper(),
            "wifi": None if wifi is None else {"ssid": wifi.ssid.strip(), "password": wifi.password,
                                               "security": wifi.security},
            "hours": None if self.hours is None else {"open_hour": self.hours.open_hour,
                                                      "close_hour": self.hours.close_hour},
            "rigs": self.rigs,
            "rig_names": rig_names,
            "games": list(dict.fromkeys(self.games)),
            "features": {name: on if name in SAFETY_FLAGS else True for name, on in self.features.items()},
            "variant": self.variant,
        }

    # --- names -------------------------------------------------------------------------------------

    def slug(self) -> str:
        """An ASCII name for files and build.ps1's -CafeSlug: "Apex Lounge" -> "Apex-Lounge". Accents are dropped
        ("Café" -> "Cafe"); a name with no Latin letters (Devanagari, say) uses the cafe id ("cafe-7f3a09c1")."""
        return slugify(self.name, self.cafe_id)

    def installer_name(self) -> str:
        """The installer pitwall.iss writes for this cafe: <exe>-Setup-<slug>.exe."""
        return f"{brand.EXE_NAME}-Setup-{self.slug()}.exe"

    def package_folder_name(self, day: dt.date) -> str:
        """The package folder in Shipments: "<Cafe name> (<date>)", safe as a Windows folder name."""
        return f"{safe_file_name(self.name, self.slug())} ({day.isoformat()})"

    def guide_pdf_name(self) -> str:
        return f"Setup guide - {safe_file_name(self.name, self.slug())}.pdf"

    def certificate_pdf_name(self) -> str:
        return f"Licence certificate - {safe_file_name(self.name, self.slug())}.pdf"


def _fits(raw: str) -> bool:
    try:
        clean_rig_name(raw)
        return True
    except RigError:
        return False


def _logo_name_problem(name: str) -> str | None:
    if not name or name in (".", "..") or any(c in name for c in "/\\:") or name != name.strip():
        return "The logo file is missing. Choose the logo again."
    return None


def logo_file_problem(path: Path) -> str | None:
    """Why an image file can't be the cafe's logo (as on /setup), or None when it can."""
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_LOGO_BYTES + 1)
    except OSError:
        return "The logo file is missing. Choose the logo again."
    if logo_kind(data) is None:
        return "Choose a PNG, JPEG or WebP picture for the logo."
    if len(data) > MAX_LOGO_BYTES:
        return "Choose a logo under 1 MB."
    return None


def _wifi_problems(w: Wifi) -> list[str]:
    ssid = w.ssid.strip()
    if not ssid:
        return ["Enter the Wi-Fi name, or leave the guest Wi-Fi out."]
    out = []
    if len(ssid.encode("utf-8")) > 32:
        out.append("The Wi-Fi name is too long: at most 32 letters (fewer with accents or emoji).")
    if w.security == "WPA" and not 8 <= len(w.password) <= 63:
        out.append("A WPA Wi-Fi password is 8 to 63 characters.")
    if w.security == "nopass" and w.password:
        out.append("An open Wi-Fi network has no password. Clear the password or choose WPA.")
    return out


# --- file names ------------------------------------------------------------------------------------

def slugify(name: str, cafe_id: str) -> str:
    """See CafeProfile.slug. Always matches SLUG_RE."""
    latin = (name or "").translate(_TRANSLIT)
    ascii_text = unicodedata.normalize("NFKD", latin).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-")[:SLUG_MAX].strip("-")
    if not slug:
        slug = "cafe-" + (re.sub(r"[^a-z0-9]", "", cafe_id.lower().removeprefix("c-"))[:8] or "new")
    assert SLUG_RE.match(slug), slug
    return slug


def safe_file_name(text: str, fallback: str) -> str:
    """`text` as a Windows file or folder name: no \\ / : * ? " < > | or control characters, no trailing dot or
    space, not a reserved name (CON, NUL, COM1...), at most 60 characters. Other scripts are kept (Windows names
    are Unicode). `fallback` when nothing is left."""
    s = _WIN_BAD.sub(" ", unicodedata.normalize("NFC", text or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Cf" or c in "‌‍")
    s = " ".join(s.split())[:FILE_NAME_MAX].rstrip(" .").lstrip()
    if not s:
        s = fallback
    if s.split(".")[0].upper().rstrip() in _WIN_RESERVED:
        s = "_" + s
    return s


# --- storage ---------------------------------------------------------------------------------------

@dataclass
class ProfileEntry:
    """One file in the profiles folder: the profile, or a plain reason it can't be opened."""
    path: Path
    profile: CafeProfile | None
    error: str | None = None

    @property
    def title(self) -> str:
        if self.profile is None:
            return self.path.stem
        return self.profile.name.strip() or "(no name yet)"


class ProfileStore:
    """The profiles in <Shipments>/profiles. Every write is atomic (temporary file, then a rename)."""

    def __init__(self, shipments_dir: Path) -> None:
        self.shipments = Path(shipments_dir)
        self.dir = self.shipments / PROFILES_DIR
        self.logo_dir = self.dir / LOGOS_DIR

    # reading
    def list(self) -> list[ProfileEntry]:
        """Every profile, by cafe name; damaged files are listed with a plain error, never skipped silently."""
        out = []
        for path in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            try:
                out.append(ProfileEntry(path, load(path)))
            except ProfileError as exc:
                out.append(ProfileEntry(path, None, str(exc)))
        return sorted(out, key=lambda e: (e.profile is None, e.title.casefold()))

    def find(self, cafe_id: str) -> Path | None:
        """The file holding this cafe's profile, if saved."""
        for entry in self.list():
            if entry.profile is not None and entry.profile.cafe_id == cafe_id:
                return entry.path
        return None

    def path_for(self, profile: CafeProfile) -> Path:
        """<slug>.json, or <slug>-<id>.json when that file is another cafe's (or damaged: it is never overwritten),
        or when the slug is a name Windows reserves (CON.json, NUL.json... can't be created)."""
        slug = profile.slug()
        path = self.dir / f"{slug}.json"
        taken = path.exists() and _peek_cafe_id(path) != profile.cafe_id
        if taken or slug.upper() in _WIN_RESERVED:
            path = self.dir / f"{slug}-{profile.cafe_id.removeprefix('c-')[:8]}.json"
        return path

    def problems(self, profile: CafeProfile) -> list[tuple[str, str]]:
        """profile.problems() with the logo file checked too: what the build (C10) uses."""
        return profile.problems(self.logo_dir)

    def logo_path(self, profile: CafeProfile) -> Path | None:
        return self.logo_dir / profile.logo if profile.logo else None

    # writing
    def save(self, profile: CafeProfile) -> Path:
        """Write the profile (a draft is fine) and return its file. A renamed cafe moves to its new file name; the
        old file goes only once the new one is written. Raises ProfileError when the disk refuses."""
        old = self.find(profile.cafe_id)
        path = self.path_for(profile)
        if old is not None and old.stem.startswith(profile.slug()) and old.stem in (
                profile.slug(), f"{profile.slug()}-{profile.cafe_id.removeprefix('c-')[:8]}"):
            path = old                                        # same name as before: keep its file
        try:
            save(profile, path)
            if old is not None and old != path:
                old.unlink(missing_ok=True)
        except OSError:
            raise ProfileError("The cafe couldn't be saved. Check the Shipments folder is there and not "
                               "read-only, then try again.") from None
        return path

    def import_logo(self, profile: CafeProfile, source: Path) -> str:
        """Check a picture the seller chose and copy it into the logos folder; sets and returns profile.logo.
        The profile itself still needs saving. Raises ProfileError with a plain message."""
        problem = logo_file_problem(Path(source))
        if problem:
            raise ProfileError(problem)
        data = Path(source).read_bytes()
        ext = logo_kind(data)
        name = f"{profile.cafe_id}-{hashlib.sha256(data).hexdigest()[:8]}{ext}"
        try:
            write_atomic(self.logo_dir / name, data)
        except OSError:
            raise ProfileError("The logo couldn't be copied. Check the Shipments folder, then try again.") from None
        profile.logo = name
        return name

    def copy_logo(self, profile: CafeProfile, dest_dir: Path) -> Path | None:
        """Copy the logo into a baked folder under `baked_logo_name()` (for the build, C10)."""
        src = self.logo_path(profile)
        if src is None:
            return None
        dest = Path(dest_dir) / profile.baked_logo_name()
        shutil.copyfile(src, dest)
        return dest


def _peek_cafe_id(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data.get("cafe_id") if isinstance(data, dict) and isinstance(data.get("cafe_id"), str) else None


def load(path: Path) -> CafeProfile:
    """Read a profile file. Raises ProfileError when it's missing or damaged."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ProfileError("This cafe's file is missing.") from None
    except (OSError, UnicodeDecodeError):
        raise ProfileError("This cafe's file can't be read.") from None
    try:
        return CafeProfile.model_validate_json(text)
    except ValidationError:
        raise ProfileError("This cafe's file is damaged.") from None


def save(profile: CafeProfile, path: Path) -> None:
    """Atomic: a power cut never leaves half a file. Raises OSError."""
    text = json.dumps(profile.model_dump(mode="json"), indent=2, ensure_ascii=False)
    write_atomic(Path(path), (text + "\n").encode("utf-8"))
