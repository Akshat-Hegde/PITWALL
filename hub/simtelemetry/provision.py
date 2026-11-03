"""Provisioning: apply a cafe's baked-in profile when its installer runs (spec 2.4).

`<exe> provision <dir> [--check] [--force-other-cafe]` runs as SYSTEM from the cafe's installer, before the hub
starts. `<dir>` is the baked folder the factory (factory/profile.py `baked_profile()`) puts into the installer:

    profile.json   a BakedProfile (below), UTF-8 JSON
    <logo>         the logo image named in profile.json "logo" (PNG, JPEG or WebP, at most 1 MB), if any
    licence.txt    the cafe's licence code (licence.py)

profile.json, version 1 (unknown keys are ignored, so a newer factory's v1 file still loads):

    {"v": 1,
     "cafe_id": "c-7f3a...",                 # the licence binds to it; also stamped on the PC (cafe.json)
     "name": "Apex Lounge",                  # 1-40 characters
     "tagline": "Race the city",             # optional, at most 60
     "logo": "logo.png",                     # optional: a file name in <dir>, no folders
     "accent": "#E10600",                    # #RRGGBB, one of the setup page's colours
     "wifi": {"ssid": "Apex Guests", "password": "racing123", "security": "WPA"},   # optional; or "nopass"
     "hours": {"open_hour": 11, "close_hour": 1},                                   # optional; as on /setup
     "rigs": 6,                              # 1-24
     "rig_names": ["Senna", "", "Lauda"],    # optional, by rig number (1 first); "" or null = no name
     "games": ["f1_25"],
     "features": {"events": false, ...},     # [features] flag -> on/off; flags not listed keep hub.toml's value
     "variant": "9t7"}                       # or "unbranded"

What it does, decided by the PC's state (data folder, `cafe.json` stamp):
- **fresh** (no settings.json, or one left by an unfinished provisioning: no owner PIN and setup not done; and no
  stamp): installs the licence; pre-fills settings.json (name, tagline, logo, accent, Wi-Fi, hours) with no PINs and
  setup_done false, so the owner still finishes /setup with the setup code; writes the rig names as pending names
  into rigs.json (core/rigs.py applies them as rigs appear); sets hub.toml's [features] to the profile's, keeping
  the rest of the file and its comments; writes the stamp last (an interrupted run is simply run again).
- **upgrade** (stamp of this cafe): only a newer licence of the same cafe is installed (licence.accept_new).
  Settings, PINs, rig names, logo, Wi-Fi and hub.toml are never touched.
- **adopt** (no stamp, but the PC is already set up, e.g. a 0.5.0 cafe upgraded with its first cafe installer, or
  settings that can't be read): like upgrade, and the stamp is written.
- **another cafe** (the stamp, or with no stamp the installed licence, names another cafe): refused with exit code
  3, unless --force-other-cafe: then the PC is re-stamped and given this licence, but its settings, PINs, rigs and
  hub.toml are kept (fresh only when there is nothing to keep).
- `--check` only answers whether this installer may go on this PC (0 yes, 3 another cafe, 2 bad files); it writes
  nothing.

Exit codes: 0 done, 1 couldn't save (disk), 2 the baked files can't be used, 3 another cafe's PC.
Every message is plain English for the installer to show; nothing is a stack trace.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator,
                      model_validator)

from . import brand, licence
from .config import FeaturesConfig
from .core.rigs import RIG_NAME_MAX, RigError, clean_rig_name
from .core.settings import SETTINGS_VERSION, CafeSettings, SettingsStore

log = logging.getLogger(__name__)

PROFILE_FILE = "profile.json"
STAMP_FILE = "cafe.json"
RIGS_FILE = "rigs.json"
MAX_PROFILE_BYTES = 256 * 1024
MAX_RIGS = 24

EXIT_OK, EXIT_FAILED, EXIT_BAD_INPUT, EXIT_OTHER_CAFE = 0, 1, 2, 3

ASK_SUPPLIER = "Ask your supplier for a new installer."
SAVE_FAILED = (f"{brand.PRODUCT_NAME} couldn't save the cafe's details on this PC. Restart the PC and run the "
               "installer again; if it keeps happening, contact your supplier.")

# Logo files: the same rules as an upload on /setup (api/setup.py), told apart by their first bytes.
_LOGO_MAGIC = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"))
_RIG_N = re.compile(r"rig\s*0*(\d+)", re.IGNORECASE)
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CTRL = r"\x00-\x1f\x7f"
Text = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=rf"^[^{_CTRL}]*[^\s{_CTRL}][^{_CTRL}]*$")]


class ProvisionError(Exception):
    """Provisioning can't go on; the message is plain English and `code` is the exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


class BakedWifi(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    ssid: str = Field(max_length=64)
    password: str = Field("", max_length=63)
    security: Literal["WPA", "nopass"] = "WPA"


class BakedHours(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    open_hour: int = Field(ge=0, le=23)
    close_hour: int = Field(ge=0, le=24)


class BakedProfile(BaseModel):
    """profile.json in the baked folder (see the module docstring). The factory writes exactly this."""

    model_config = ConfigDict(extra="ignore", strict=True)

    v: Literal[1]
    cafe_id: Text
    name: str = Field(min_length=1, max_length=40)
    tagline: str = Field("", max_length=60)
    logo: str | None = None
    accent: str = "#E10600"
    wifi: BakedWifi | None = None
    hours: BakedHours | None = None
    rigs: int = Field(ge=1, le=MAX_RIGS)
    rig_names: list[str | None] = Field(default_factory=list)
    games: list[Text] = Field(min_length=1)
    features: dict[str, bool] = Field(default_factory=dict)
    variant: Literal["9t7", "unbranded"]

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the cafe name is empty")
        return value.strip()

    @field_validator("logo")
    @classmethod
    def _logo(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value in (".", "..") or any(c in value for c in "/\\:") or value != value.strip():
            raise ValueError("the logo must be a file name in the installer's folder")
        return value

    @field_validator("accent")
    @classmethod
    def _accent(cls, value: str) -> str:
        if not _HEX.match(value):
            raise ValueError("the accent colour must look like #E10600")
        return value.upper()

    @model_validator(mode="after")
    def _rig_names(self) -> "BakedProfile":
        if len(self.rig_names) > self.rigs:
            raise ValueError(f"there are more rig names than rigs ({self.rigs})")
        names: list[str | None] = []
        seen: set[str] = set()
        for number, raw in enumerate(self.rig_names, 1):
            try:
                name = clean_rig_name(raw)
            except RigError:
                raise ValueError(f"the name for rig {number} is longer than {RIG_NAME_MAX} characters") from None
            m = _RIG_N.fullmatch(name) if name else None
            if m and int(m.group(1)) == number:
                name = None                           # "Rig 2" for rig 2 is just its number
            elif m:
                raise ValueError(f'the name for rig {number} looks like another rig\'s number ("{name}")')
            if name and name.casefold() in seen:
                raise ValueError(f'two rigs are called "{name}"')
            if name:
                seen.add(name.casefold())
            names.append(name)
        self.rig_names = names
        return self

    def settings(self) -> CafeSettings:
        """settings.json as provisioned: the cafe's details, no PINs, setup not done."""
        wifi = self.wifi
        hours = self.hours
        return CafeSettings(
            name=self.name, tagline=self.tagline, accent=self.accent, logo=None,
            setup_done=False, owner_pin="", staff_pin="",
            wifi_ssid=wifi.ssid if wifi else "", wifi_password=wifi.password if wifi else "",
            wifi_security=wifi.security if wifi else "WPA",
            **({"open_hour": hours.open_hour, "close_hour": hours.close_hour} if hours else {}),
            settings_version=SETTINGS_VERSION)

    def pending_rig_names(self) -> dict[int, str]:
        return {n: name for n, name in enumerate(self.rig_names, 1) if name}

    def known_features(self) -> dict[str, bool]:
        return {k: v for k, v in self.features.items() if k in FeaturesConfig.model_fields}


_FIELD_WORDS = {"v": "the version", "cafe_id": "the cafe's id", "name": "the cafe name", "tagline": "the tagline",
                "logo": "the logo", "accent": "the accent colour", "wifi": "the guest Wi-Fi",
                "hours": "the opening hours", "rigs": "the number of rigs", "rig_names": "the list of rig names",
                "games": "the list of games", "features": "the feature list", "variant": "the branding",
                "wifi_ssid": "the Wi-Fi name", "wifi_password": "the Wi-Fi password",
                "wifi_security": "the Wi-Fi security", "open_hour": "the opening time",
                "close_hour": "the closing time"}


_KIND_WORDS = {"missing": "is missing", "string_too_short": "is empty", "too_short": "is empty",
               "string_too_long": "is too long", "too_long": "has too many entries",
               "greater_than_equal": "is too small", "less_than_equal": "is too big"}


def _plain(exc: ValidationError) -> str:
    """The first mistake in plain words: "the Wi-Fi password: a WPA Wi-Fi password is 8 to 63 characters"."""
    err = exc.errors()[0]
    loc = [p for p in err.get("loc", ()) if isinstance(p, str)]
    what = next((_FIELD_WORDS[p] for p in reversed(loc) if p in _FIELD_WORDS), None)
    kind = str(err.get("type", ""))
    if kind == "value_error":                    # our own checks (and CafeSettings') are already plain
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        msg = msg[:1].lower() + msg[1:]
        return f"{what}: {msg}" if what else msg
    phrase = _KIND_WORDS.get(kind, "isn't right")
    return f"{what or 'something'} {phrase}"


def _bad(detail: str) -> ProvisionError:
    return ProvisionError(f"This installer's cafe details can't be used ({detail}). {ASK_SUPPLIER}", EXIT_BAD_INPUT)


@dataclass
class Baked:
    profile: BakedProfile
    settings: CafeSettings
    logo: tuple[bytes, str] | None = None            # image bytes and extension
    licence: licence.Licence | None = None           # None when the baked code didn't verify
    licence_problem: str | None = None


def logo_kind(data: bytes) -> str | None:
    """The file extension for a PNG, JPEG or WebP image, from its first bytes; None for anything else."""
    for magic, ext in _LOGO_MAGIC:
        if data.startswith(magic):
            return ext
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def load_baked(src: Path) -> Baked:
    """Read and check the baked folder. Raises ProvisionError(EXIT_BAD_INPUT) with a plain message."""
    from .api.setup import MAX_LOGO_BYTES
    src = Path(src)
    if not src.is_dir():
        raise _bad("the folder with the cafe's files is missing")
    try:
        with open(src / PROFILE_FILE, "rb") as f:
            raw = f.read(MAX_PROFILE_BYTES + 1)
    except OSError:
        raise _bad("the cafe's profile is missing") from None
    if len(raw) > MAX_PROFILE_BYTES:
        raise _bad("the cafe's profile is too big")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise _bad("the cafe's profile is damaged") from None
    if not isinstance(data, dict):
        raise _bad("the cafe's profile is damaged")
    if data.get("v") not in (1, None) or isinstance(data.get("v"), bool):
        raise _bad("it was made for a different version")
    try:
        profile = BakedProfile.model_validate(data)
        settings = profile.settings()
    except ValidationError as exc:
        raise _bad(_plain(exc)) from None
    baked = Baked(profile=profile, settings=settings)
    if profile.logo:
        try:
            with open(src / profile.logo, "rb") as f:
                image = f.read(MAX_LOGO_BYTES + 1)
        except OSError:
            raise _bad("the logo file is missing") from None
        ext = logo_kind(image)
        if ext is None:
            raise _bad("the logo isn't a PNG, JPEG or WebP image")
        if len(image) > MAX_LOGO_BYTES:
            raise _bad("the logo must be under 1 MB")
        baked.logo = (image, ext)
    try:
        lic = licence.read_file(src)
    except licence.LicenceError:
        lic = None
        baked.licence_problem = "unverified"
    else:
        if lic is None:
            raise _bad("the licence file is missing")
        if lic.payload.cafe_id != profile.cafe_id:
            raise _bad("the licence is for a different cafe")
    baked.licence = lic
    return baked


# --- the PC's side ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Stamp:
    cafe_id: str
    name: str


def read_stamp(data_dir: Path) -> Stamp | None:
    """<data>/cafe.json; None when missing or damaged (then the installed licence tells whose PC it is)."""
    try:
        raw = json.loads((Path(data_dir) / STAMP_FILE).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("Ignoring the unreadable cafe stamp in %s (%s)", data_dir, exc)
        return None
    if not (isinstance(raw, dict) and isinstance(raw.get("cafe_id"), str) and raw["cafe_id"].strip()):
        log.warning("Ignoring the damaged cafe stamp in %s", data_dir)
        return None
    name = raw.get("name") if isinstance(raw.get("name"), str) and raw["name"].strip() else "another cafe"
    return Stamp(cafe_id=raw["cafe_id"], name=name)


def write_stamp(data_dir: Path, profile: BakedProfile) -> None:
    text = json.dumps({"cafe_id": profile.cafe_id, "name": profile.name}, indent=2, ensure_ascii=False)
    write_atomic(Path(data_dir) / STAMP_FILE, (text + "\n").encode("utf-8"))


def write_atomic(path: Path, data: bytes) -> None:
    """Write via a temporary file and a rename: a power cut never leaves half a file. Raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def installed_licence(data_dir: Path) -> licence.Licence | None:
    """The PC's verified licence, or None (missing or damaged)."""
    try:
        return licence.read_file(data_dir)
    except licence.LicenceError:
        return None


def settings_state(data_dir: Path) -> Literal["missing", "unfinished", "set_up"]:
    """Read without changing anything (SettingsStore.read may rewrite the file).
    "unfinished": pre-filled by an earlier provisioning that didn't get to the stamp (no owner PIN, setup not done).
    "set_up": anything else, including a file that can't be read: the cafe's own, never overwritten."""
    path = Path(data_dir) / "settings.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "missing"
    except (OSError, ValueError):
        return "set_up"
    if isinstance(raw, dict) and raw.get("setup_done") is False and not raw.get("owner_pin") \
            and not raw.get("staff_pin"):
        return "unfinished"
    return "set_up"


# --- hub.toml [features] ----------------------------------------------------------------------

class HubTomlError(Exception):
    pass


_HEADER = re.compile(r"^\s*\[")
_FEATURES_HEADER = re.compile(r"^\s*\[\s*features\s*\]\s*(#.*)?$")
_FLAG = re.compile(r"^(?P<indent>\s*)(?P<hash>#\s*)?(?P<key>[A-Za-z0-9_]+)(?P<eq>\s*=\s*)(?P<value>true|false)\b"
                   r"(?P<rest>.*)$")


def set_features(text: str, wanted: dict[str, bool]) -> str:
    """hub.toml text with [features] set to `wanted`, everything else (comments too) kept as it was.

    A flag already written in [features] gets the new value; a flag left at its default stays as it is (commented
    out, as in the starter file); otherwise its commented-out line is switched on, or a line is added. The result is
    checked by reading both files back: only those flags may differ. Raises HubTomlError when the file can't be
    read as TOML or the edit can't be made safely; the caller then leaves the file alone."""
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise HubTomlError(f"hub.toml can't be read: {exc}") from None
    defaults = {k: f.default for k, f in FeaturesConfig.model_fields.items()}
    current = before.get("features") if isinstance(before.get("features"), dict) else {}
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if _FEATURES_HEADER.match(line)), None)
    if start is None:
        missing = {k: v for k, v in wanted.items() if current.get(k, defaults.get(k)) != v}
        if not missing:
            return text
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += nl
        lines += ([nl] if lines else []) + [f"[features]{nl}"] + [f"{k} = {str(v).lower()}{nl}" for k, v in missing.items()]
    else:
        end = next((i for i in range(start + 1, len(lines)) if _HEADER.match(lines[i])), len(lines))
        todo = dict(wanted)
        for i in range(start + 1, end):                      # flags already written: set them
            m = _FLAG.match(lines[i].rstrip("\r\n"))
            if m and not m["hash"] and m["key"] in todo:
                lines[i] = _flag_line(m, todo.pop(m["key"]), lines[i])
        todo = {k: v for k, v in todo.items() if current.get(k, defaults.get(k)) != v}
        for i in range(start + 1, end):                      # commented-out examples: switch on
            m = _FLAG.match(lines[i].rstrip("\r\n"))
            if m and m["hash"] and m["key"] in todo:
                lines[i] = _flag_line(m, todo.pop(m["key"]), lines[i])
        if todo:                                             # still missing: add after the section's last line
            at = end
            while at > start + 1 and not lines[at - 1].strip():
                at -= 1
            if at > 0 and not lines[at - 1].endswith(("\n", "\r")):
                lines[at - 1] += nl
            lines[at:at] = [f"{k} = {str(v).lower()}{nl}" for k, v in todo.items()]
    out = "".join(lines)
    try:
        after = tomllib.loads(out)
    except tomllib.TOMLDecodeError as exc:
        raise HubTomlError(f"the edited hub.toml wouldn't read back: {exc}") from None

    def flags(feats: Any) -> dict[str, Any]:          # a flag left out reads as its default
        feats = feats if isinstance(feats, dict) else {}
        return {k: feats.get(k, defaults.get(k)) for k in set(feats) | set(defaults)}

    rest_same = {k: v for k, v in after.items() if k != "features"} == \
        {k: v for k, v in before.items() if k != "features"}
    if not rest_same or flags(after.get("features")) != flags({**current, **wanted}):
        raise HubTomlError("the edited hub.toml didn't come out as intended")
    return out


def _flag_line(m: re.Match, value: bool, original: str) -> str:
    """`key = value`, keeping the line's indent, its trailing comment and that comment's column."""
    ending = original[len(original.rstrip("\r\n")):]
    head = f"{m['indent']}{m['key']}{m['eq']}{str(value).lower()}"
    rest = m["rest"]
    comment = rest.lstrip()
    if not comment.startswith("#"):
        return head + ending
    column = m.start("rest") + len(rest) - len(comment)
    return head + " " * max(1, column - len(head)) + comment + ending


def write_features(config_path: Path, wanted: dict[str, bool]) -> bool:
    """Set hub.toml's [features]; True when the file changed. A missing file is created with only [features].
    Raises HubTomlError (file left alone) or OSError."""
    if not wanted:
        return False
    try:
        raw = config_path.read_bytes()
    except FileNotFoundError:
        raw = b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HubTomlError("hub.toml isn't UTF-8 text") from None
    out = set_features(text, wanted)
    if out == text:
        return False
    write_atomic(config_path, (b"\xef\xbb\xbf" if bom else b"") + out.encode("utf-8"))
    return True


# --- rigs.json pending names ------------------------------------------------------------------

def write_pending_rig_names(data_dir: Path, names: dict[int, str]) -> None:
    """Put the profile's rig names into rigs.json "pending_names" (core/rigs.py applies them), keeping the rest."""
    path = Path(data_dir) / RIGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as exc:
        log.warning("Replacing the unreadable %s (%s)", path, exc)
        data = {}
    if names:
        data["pending_names"] = {str(n): name for n, name in sorted(names.items())}
    else:
        data.pop("pending_names", None)
        if not data:
            return
    write_atomic(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


# --- the whole job ----------------------------------------------------------------------------

@dataclass
class Result:
    code: int
    lines: list[str] = field(default_factory=list)
    mode: str | None = None          # "fresh", "upgrade", "adopt" (None for --check and refusals)


def other_cafe_message(profile: BakedProfile, owner: Stamp) -> str:
    return f"This installer is for {profile.name}. This PC belongs to {owner.name}."


def provision(src: Path, data_dir: Path, config_path: Path, *, check: bool = False, force: bool = False) -> Result:
    """Apply the baked folder `src` to this PC (see the module docstring). Never raises for bad input or a full
    disk: the Result carries the exit code and the plain messages."""
    try:
        return _provision(Path(src), Path(data_dir), Path(config_path), check, force)
    except ProvisionError as exc:
        log.warning("Provisioning stopped: %s", exc)
        return Result(exc.code, [str(exc)])
    except OSError:
        log.exception("Provisioning could not save the cafe's details")
        return Result(EXIT_FAILED, [SAVE_FAILED])


def _provision(src: Path, data_dir: Path, config_path: Path, check: bool, force: bool) -> Result:
    baked = load_baked(src)
    profile = baked.profile
    stamp = read_stamp(data_dir)
    current = installed_licence(data_dir)
    owner = stamp or (Stamp(current.payload.cafe_id, current.payload.cafe_name) if current else None)
    other = owner is not None and owner.cafe_id != profile.cafe_id
    if other and not force:
        log.warning("Refused: this installer is for %s (%s), the PC belongs to %s (%s)",
                    profile.name, profile.cafe_id, owner.name, owner.cafe_id)
        return Result(EXIT_OTHER_CAFE, [other_cafe_message(profile, owner)])
    if check:
        return Result(EXIT_OK, [f"This installer is for {profile.name}. It can be installed on this PC."])

    if stamp is not None and not other:
        mode = "upgrade"
    elif settings_state(data_dir) in ("missing", "unfinished"):
        mode = "fresh"
    else:
        mode = "adopt"
    if other:
        log.warning("Installing %s (%s) over %s (%s) on request (--force-other-cafe); the PC's settings are kept",
                    profile.name, profile.cafe_id, owner.name, owner.cafe_id)
    log.info("Provisioning %s (%s): %s", profile.name, profile.cafe_id, mode)

    lines: list[str] = []
    if other:
        lines.append(f"This PC belonged to {owner.name}. It now belongs to {profile.name}.")
    if mode == "fresh":
        lines.append(f"Set up for {profile.name}.")
    elif mode == "upgrade":
        lines.append(f"This PC is already set up for {owner.name}. Its settings, PINs, rig names, logo and "
                     "Wi-Fi were kept.")
    else:
        lines.append(f"This PC was already set up. Its settings, PINs, rig names, logo and Wi-Fi were kept, and "
                     f"it is now registered to {profile.name}.")

    lines.append(_install_licence(data_dir, baked, None if other else current))

    if mode == "fresh":
        settings = baked.settings
        if baked.logo is not None:
            from .api.setup import save_logo
            image, ext = baked.logo
            settings = settings.model_copy(update={"logo": save_logo(SettingsStore(data_dir).branding_dir,
                                                                     image, ext)})
        SettingsStore(data_dir).save(settings)
        write_pending_rig_names(data_dir, profile.pending_rig_names())
        try:
            if write_features(config_path, profile.known_features()):
                log.info("Set the features in %s to the cafe's", config_path)
        except HubTomlError as exc:
            log.warning("Left %s as it was: %s", config_path, exc)
            lines.append("The feature switches in the settings file (hub.toml) were left as they were, because "
                         "the file has a mistake.")
        lines.append("The cafe's name, logo, colour, Wi-Fi and opening hours are filled in. Open the setup page "
                     "to check them and choose the PINs.")
    unknown = sorted(set(profile.features) - set(FeaturesConfig.model_fields))
    if unknown:
        log.warning("Features this version doesn't know were ignored: %s", ", ".join(unknown))
    if mode != "upgrade":
        write_stamp(data_dir, profile)                       # last: an interrupted run is simply run again
    return Result(EXIT_OK, lines, mode)


def _install_licence(data_dir: Path, baked: Baked, current: licence.Licence | None) -> str:
    new = baked.licence
    if new is None:
        log.warning("The installer's licence didn't verify with this version's key; not installed")
        return ("The licence in this installer couldn't be checked, so it wasn't installed. "
                f"{brand.PRODUCT_NAME} still works; enter the licence code on the owner page, or contact your "
                "supplier.")
    try:
        ent = licence.accept_new(licence.entitlements_from(current) if current else None, new)
    except licence.LicenceError as exc:
        log.info("Kept this PC's licence: %s", exc)
        if str(exc) == licence.OTHER_CAFE:
            return "The licence in this installer is for a different cafe, so the one on this PC was kept."
        return "The licence on this PC is already up to date, so it was kept."
    licence.write_file(data_dir, new)
    log.info("Installed licence %s (seq %d)", ent.licence_id, ent.seq)
    return f"Licence installed: {licence.summary(ent)}."
