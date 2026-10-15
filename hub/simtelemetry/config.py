"""Hub configuration: TOML file -> validated pydantic model. No cafe data is hard-coded."""

from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, ValidationInfo, field_validator

from . import paths


class ConfigError(Exception):
    """Invalid config file; the message is meant to be shown to the user as-is."""


@dataclass(frozen=True)
class ConfigProblem:
    """A mistake in hub.toml that the hub worked around (load_config_safe)."""
    message: str          # plain English, for the staff and setup pages
    detail: str           # file, section, key and line, for the log
    loc: tuple = ()       # the key that was dropped, e.g. ("data_dir",) or ("backup", "directory")
    whole_file: bool = False   # the file couldn't be used at all: every setting is a default

    def touches(self, *prefixes: tuple) -> bool:
        """True when the whole file fell back to defaults, or the dropped key is (inside) one of `prefixes`."""
        return self.whole_file or any(self.loc[:len(p)] == p for p in prefixes)


class _Section(BaseModel):
    # Unknown keys are reported: a misspelt or outdated key must not be silently ignored
    # (load_config raises; load_config_safe ignores the key and warns).
    model_config = ConfigDict(extra="forbid")


class CafeConfig(_Section):
    name: str = "Sim Racing Cafe"
    tagline: str = ""
    logo: str | None = None  # file name in <data_dir>/branding/, set from /setup
    # CSS custom properties for the dashboard, e.g. {"--brand-accent" = "#e10600"}.
    branding: dict[str, str] = Field(default_factory=dict)
    # Optional guest Wi-Fi, set from /setup; the password is only ever sent inside the TV's QR string.
    wifi_ssid: str = ""
    wifi_password: str = ""
    wifi_security: str = "WPA"


class NetworkConfig(_Section):
    udp_host: str = "0.0.0.0"
    udp_port: int = Field(20777, ge=1, le=65535)
    udp_receive_buffer_bytes: int = 4 * 1024 * 1024
    http_host: str = "0.0.0.0"
    http_port: int = Field(8000, ge=1, le=65535)


class RecorderConfig(_Section):
    # Raw capture is for debugging. Off in production `run` (10 rigs ~ 7.5 GB/hour), on for `listen`.
    enabled_in_run: bool = False
    enabled_in_listen: bool = True
    max_file_mb: int = Field(256, ge=1)
    keep_files: int = Field(24, ge=0)  # 0 = never delete old recordings
    # Where recordings go; default <data_dir>/recordings. Can be on another drive.
    directory: Path | None = None
    warn_free_gb: float = Field(5.0, ge=0)    # warn when free space on that drive drops below this
    stop_free_gb: float = Field(1.0, ge=0)    # stop recording (hub keeps running) below this
    disk_check_interval_s: float = Field(30.0, gt=0)

    @field_validator("stop_free_gb")
    @classmethod
    def _floor_not_above_warning(cls, value: float, info: ValidationInfo) -> float:
        warn = info.data.get("warn_free_gb")
        if warn is not None and value > warn:
            raise ValueError(f"must not be above warn_free_gb ({warn:g})")
        return value


class MapConfig(_Section):
    # How the game's world coordinates are drawn on the TV map (screen right = +x, down = +z after
    # these). Confirm against the in-game minimap during testing (?map=... in the dashboard URL).
    flip_x: bool = False
    flip_z: bool = False
    rotate_deg: float = 0.0


def _pin_text(value: Any) -> Any:
    """pin = 1234 (a TOML number) means the same as pin = "1234". Write PINs in quotes all the same:
    a number can't start with 0 in TOML (pin = 0123 is a mistake in the file), but "0123" is fine."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


class StaffConfig(_Section):
    # PIN for the /staff page (setting driver names). Empty = no PIN; anyone on the LAN can change names.
    pin: str = ""

    @field_validator("pin", mode="before")
    @classmethod
    def _pin(cls, value: Any) -> Any:
        return _pin_text(value)


class OwnerConfig(_Section):
    # PIN for the /owner analytics page. Empty = the owner page is locked (it shows business figures).
    pin: str = ""

    @field_validator("pin", mode="before")
    @classmethod
    def _pin(cls, value: Any) -> Any:
        return _pin_text(value)
    # Opening hours (local hours). A closing hour of 0 to 6 at or before the opening hour means the next day.
    open_hour: int = Field(10, ge=0, le=23)
    close_hour: int = Field(22, ge=0, le=24)

    @field_validator("close_hour")
    @classmethod
    def _close_after_open(cls, value: int, info: ValidationInfo) -> int:
        from .core.hours import hours_problem
        opens = info.data.get("open_hour")
        if opens is not None and hours_problem(opens, value):
            raise ValueError(f"must be after open_hour ({opens}), or 0 to 6 for closing after midnight")
        return value


class LeaderboardConfig(_Section):
    # "Today" starts at this hour (local time). Normally automatic (left out, or 0): the closing hour when the
    # cafe closes after midnight, else midnight. See AppConfig.day_start_hour.
    day_start_hour: int | None = Field(None, ge=0, le=23)


class DashboardConfig(_Section):
    frame_hz: float = Field(15.0, ge=10, le=20)  # WebSocket frame rate (docs/WS_SCHEMA.md)
    # Total lock-to-lock rotation of the steering wheel graphic (game steer -1..1 maps to +-half of this).
    steering_wheel_rotation_deg: float = Field(360.0, gt=0, le=1080)
    # Built dashboard files; default <project>/dashboard/dist (run `npm run build` in dashboard/).
    directory: Path | None = None


class FeaturesConfig(_Section):
    # Every optional feature can be switched off (future licence tiers). Off = not shown or offered.
    moments: bool = True          # full-screen "now driving" and "record broken" moments on the TV
    battles: bool = True          # battle pop-ups on the TV
    podium: bool = True           # podium screen (hourly and on staff command)
    attract: bool = True          # attract mode when nobody is driving
    portrait: bool = True         # /portrait layout for vertical screens
    head_to_head: bool = True     # head-to-head analysis view
    onboard: bool = True          # the MULTIVIEW page (one tile per rig); off = LIVE only
    sharing: bool = True          # story card + QR code when a session ends
    challenges: bool = True       # weekly challenges on the TV
    events: bool = True           # corporate events: teams, team leaderboard, company branding
    owner: bool = True            # /owner analytics page
    race_podium: bool = True      # race podium + race cards when a race ends (needs sharing)
    self_checkin: bool = True     # guests put their own name on a rig from their phone (QR sticker per rig)
    auto_end_sessions: bool = True  # end sessions at closing time, and timed sessions once over time and idle
    backup_warning: bool = True   # owner page and staff Health warn when the last backup is over 2 days old


class CheckinConfig(_Section):
    # Extra words the self check-in name filter rejects, on top of the built-in list (whole words, case-insensitive).
    blocked_words: list[str] = Field(default_factory=list)


class MomentsConfig(_Section):
    # Battle pop-up when two drivers' best laps are within this, or one is on course to beat the leader.
    battle_margin_ms: int = Field(300, ge=0, le=5000)
    # Podium screen at the end of each period of this many minutes (on the clock; 60 = every full hour).
    # 0 = only when staff ask for it.
    podium_every_min: int = Field(60, ge=0, le=24 * 60)


class SoundsConfig(_Section):
    enabled: bool = False         # session start and record-broken sounds on the TV
    volume: float = Field(0.6, ge=0, le=1)


class HealthConfig(_Section):
    summary_interval_s: float = 10.0
    no_motion_after_s: float = 2.0  # packets but no Motion for this long -> "in menu / paused"
    no_data_after_s: float = 5.0    # no packets at all for this long -> "no data"


class RigConfig(_Section):
    ip: str
    name: str | None = None
    colour: str | None = None


class BackupConfig(_Section):
    enabled: bool = True
    directory: Path | None = None   # default: <data_dir>/../backups; a USB stick or synced folder is better
    hour: int = Field(4, ge=0, le=23)   # local hour for the nightly backup
    keep: int = Field(14, ge=1, le=365)


class AppConfig(_Section):
    data_dir: Path = Path("data")
    cafe: CafeConfig = Field(default_factory=CafeConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    recorder: RecorderConfig = Field(default_factory=RecorderConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    map: MapConfig = Field(default_factory=MapConfig)
    leaderboard: LeaderboardConfig = Field(default_factory=LeaderboardConfig)
    staff: StaffConfig = Field(default_factory=StaffConfig)
    owner: OwnerConfig = Field(default_factory=OwnerConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    checkin: CheckinConfig = Field(default_factory=CheckinConfig)
    moments: MomentsConfig = Field(default_factory=MomentsConfig)
    sounds: SoundsConfig = Field(default_factory=SoundsConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    rigs: list[RigConfig] = Field(default_factory=list)
    track_names: dict[int, str] = Field(default_factory=dict)  # trackId -> display name override
    # The backup folder the owner chose on the owner page (settings.json); [backup] directory is the fallback.
    _owner_backup_dir: Path | None = PrivateAttr(default=None)

    def rig_by_ip(self, ip: str) -> RigConfig | None:
        return next((r for r in self.rigs if r.ip == ip), None)

    @property
    def day_start_hour(self) -> int:
        """The hour the business day starts: [leaderboard] day_start_hour when set to 1-23, otherwise derived from
        the opening hours (0, the old starter file's value, counts as not set)."""
        from .core.hours import derived_day_start
        explicit = self.leaderboard.day_start_hour
        return explicit if explicit else derived_day_start(self.owner.open_hour, self.owner.close_hour)

    @property
    def recordings_dir(self) -> Path:
        return self.recorder.directory or self.data_dir / "recordings"

    @property
    def backups_dir(self) -> Path:
        return self._owner_backup_dir or self.backup.directory or self.data_dir.parent / "backups"

    @property
    def default_backups_dir(self) -> Path:
        """The folder used when the owner hasn't chosen one: hub.toml's [backup] directory, else ../backups."""
        return self.backup.directory or self.data_dir.parent / "backups"

    @property
    def owner_backup_dir(self) -> Path | None:
        return self._owner_backup_dir

    def set_owner_backup_dir(self, folder: Path | None) -> None:
        self._owner_backup_dir = folder


def load_config(path: Path | None = None) -> AppConfig:
    """Load the given file, else <home>/config/hub.toml if present, else defaults.

    A relative data_dir is taken relative to the home folder (see paths.py), so an installed hub keeps
    its data in ProgramData whatever folder it was started from.
    """
    if path is None:
        path = paths.config_path()
        if not path.exists():
            return _anchored(AppConfig())
    with path.open("rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid config file {path}:\n  {_describe_syntax_error(path, exc)}") from None
    try:
        return _anchored(AppConfig.model_validate(data))
    except ValidationError as exc:
        problems = "\n".join(f"  {_describe(path, err)}" for err in exc.errors())
        raise ConfigError(f"Invalid config file {path}:\n{problems}") from None


_FILE = "Your settings file (hub.toml)"
_MAX_FIXES = 50


def load_config_safe(path: Path | None = None) -> tuple[AppConfig, list[ConfigProblem]]:
    """Like load_config, but never fails: the hub must start whatever is in hub.toml.

    - A file that can't be read or parsed: all defaults, one problem.
    - An unknown key: ignored, one problem.
    - A bad value: that key is left out (its default is used), one problem; the rest of the file still applies,
      so e.g. a custom data_dir is kept when an unrelated key is wrong.
    """
    if path is None:
        path = paths.config_path()
        if not path.exists():
            return _anchored(AppConfig()), []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return _anchored(AppConfig()), [ConfigProblem(
            f"{_FILE} could not be read ({exc.__class__.__name__}). The hub started with default settings.",
            f"Could not read config file {path}: {exc}", whole_file=True)]
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        line, msg = _syntax_line(exc)
        where = f" on line {line}" if line else ""
        return _anchored(AppConfig()), [ConfigProblem(
            f"{_FILE} has a mistake{where}: {msg}. The hub started with default settings.",
            f"Invalid config file {_describe_syntax_error(path, exc)}", whole_file=True)]
    problems: list[ConfigProblem] = []
    for _ in range(_MAX_FIXES):
        try:
            return _anchored(AppConfig.model_validate(data)), problems
        except ValidationError as exc:
            err = exc.errors()[0]
            loc = tuple(err["loc"])
            if not _remove(data, loc):
                break
            problems.append(_problem(path, text, err))
    problems.append(ConfigProblem(f"{_FILE} has mistakes the hub could not work around. "
                                  "The hub started with default settings.",
                                  f"Invalid config file {path}: falling back to all defaults", whole_file=True))
    return _anchored(AppConfig()), problems


def _syntax_line(exc: tomllib.TOMLDecodeError) -> tuple[int | None, str]:
    line = getattr(exc, "lineno", None)
    msg = getattr(exc, "msg", None) or str(exc)
    m = _TOML_POSITION.match(str(exc))
    if m:
        line, msg = int(m["line"]), m["msg"]
    elif str(exc).endswith(" (at end of document)"):
        msg = str(exc).removesuffix(" (at end of document)") + " at the end of the file"
    return line, msg


def _remove(data: Any, loc: tuple) -> bool:
    """Delete the value at loc (or the nearest enclosing key/item that exists). False when nothing could go."""
    for depth in range(len(loc), 0, -1):
        parent, ok = data, True
        for part in loc[:depth - 1]:
            try:
                parent = parent[part]
            except (KeyError, IndexError, TypeError):
                ok = False
                break
        if not ok:
            continue
        try:
            del parent[loc[depth - 1]]
            return True
        except (KeyError, IndexError, TypeError):
            continue
    return False


_PLAIN = {
    "missing": "is missing",
    "int_parsing": "should be a whole number", "int_type": "should be a whole number",
    "int_from_float": "should be a whole number",
    "float_parsing": "should be a number", "float_type": "should be a number",
    "string_type": "should be text in quotes",
    "bool_parsing": "should be true or false", "bool_type": "should be true or false",
    "list_type": "should be a list in square brackets",
    "dict_type": "should be a section of settings", "model_type": "should be a section of settings",
    "model_attributes_type": "should be a section of settings",
    "path_type": "should be a folder path in quotes",
    "string_too_short": "is too short", "string_too_long": "is too long",
}
_LIMITS = {"less_than_equal": ("le", "should be {} or less"), "less_than": ("lt", "should be less than {}"),
           "greater_than_equal": ("ge", "should be {} or more"), "greater_than": ("gt", "should be more than {}")}


def _plain(err: dict[str, Any]) -> str:
    """A pydantic error as a short plain-English phrase that follows the key's name."""
    kind = err.get("type", "")
    if kind in _PLAIN:
        return _PLAIN[kind]
    if kind in _LIMITS:
        name, phrase = _LIMITS[kind]
        limit = (err.get("ctx") or {}).get(name)
        if limit is not None:
            return phrase.format(f"{limit:g}" if isinstance(limit, float) else limit)
    msg = str(err.get("msg", "")).removeprefix("Value error, ")
    return msg[:1].lower() + msg[1:]


def _problem(path: Path, text: str, err: dict[str, Any]) -> ConfigProblem:
    loc = tuple(err["loc"])
    detail = _describe(path, err)
    if loc and loc[-1] == "[key]":          # a bad key in a free-form table, e.g. [track_names]
        loc = loc[:-1]
    line = _line_of(text, loc)
    where = f" on line {line}" if line else ""
    key = loc[-1] if loc else "?"
    section = _section_label(loc).strip()
    in_section = f" in {section}" if section and not line else ""     # the line number says where; less jargon
    detail += f" (line {line})" if line else ""
    if err["type"] == "extra_forbidden":
        model = _section_model(loc)
        hints = _suggest(str(key), list(model.model_fields)) if model else []
        hint = f" (did you mean {' / '.join(hints)}?)" if hints else ""
        return ConfigProblem(f"{_FILE} has a setting the hub doesn't know{where}: '{key}'{in_section}{hint}. "
                             "It was ignored.", detail, loc=loc)
    return ConfigProblem(f"{_FILE} has a mistake{where}: '{key}'{in_section} {_plain(err)}. "
                         "The hub started with the default for that setting.", detail, loc=loc)


_HEADER = re.compile(r"^\s*(\[\[?)\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
_KEY = re.compile(r"""^\s*(?:"([^"]+)"|'([^']+)'|([A-Za-z0-9_-]+))\s*=""")


def _line_of(text: str, loc: tuple) -> int | None:
    """Best-effort line number of the key at loc in the TOML text (1-based)."""
    if not loc:
        return None
    *section, key = loc
    want_index = None
    if section and isinstance(section[-1], int):
        want_index, section = section[-1], section[:-1]
    target = ".".join(str(p) for p in section)
    current, index, counts = "", None, {}
    lines = text.splitlines()
    for n, line in enumerate(lines, 1):
        h = _HEADER.match(line)
        if h:
            current = h[2].replace(" ", "")
            if h[1] == "[[":
                counts[current] = counts.get(current, -1) + 1
                index = counts[current]
            else:
                index = None
            continue
        k = _KEY.match(line)
        if (k and current == target and (want_index is None or index == want_index)
                and (k[1] or k[2] or k[3]) == str(key)):
            return n
    whole = ".".join(str(p) for p in loc if not isinstance(p, int))
    for n, line in enumerate(lines, 1):             # an unknown or bad section: point at its header
        h = _HEADER.match(line)
        if h and h[2].replace(" ", "") == whole:
            return n
    return None


def _anchored(config: AppConfig) -> AppConfig:
    if not config.data_dir.is_absolute():
        config.data_dir = paths.home() / config.data_dir
    return config


# Python 3.11's TOMLDecodeError only carries the position inside its message.
_TOML_POSITION = re.compile(r"^(?P<msg>.*?) \(at line (?P<line>\d+), column (?P<col>\d+)\)$", re.S)


def _describe_syntax_error(path: Path, exc: tomllib.TOMLDecodeError) -> str:
    line, col = getattr(exc, "lineno", None), getattr(exc, "colno", None)  # Python 3.14+
    msg = getattr(exc, "msg", None) or str(exc)
    position = ""
    m = _TOML_POSITION.match(str(exc))
    if m:
        msg, line, col = m["msg"], int(m["line"]), int(m["col"])
    elif str(exc).endswith(" (at end of document)"):
        msg, position = str(exc).removesuffix(" (at end of document)"), " at end of file"
    if line is not None:
        position = f" line {line}, column {col}"
    return f"{path}{position}: TOML syntax error: {msg}"


def _section_model(loc: tuple) -> type[BaseModel] | None:
    """The config model that owns the key at loc[-1]."""
    model: type[BaseModel] = AppConfig
    for part in loc[:-1]:
        if isinstance(part, int):
            continue  # list index: the item type was resolved with the list field
        field = model.model_fields.get(part)
        if field is None:
            return None
        annotation = field.annotation
        if get_origin(annotation) is list:
            annotation = get_args(annotation)[0]
        if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
            return None
        model = annotation
    return model


def _section_label(loc: tuple) -> str:
    parts = loc[:-1]
    if not parts:
        return ""
    if isinstance(parts[-1], int):  # array of tables, e.g. [[rigs]]
        return f" [[{'.'.join(str(p) for p in parts[:-1])}]] #{parts[-1] + 1}"
    return f" [{'.'.join(str(p) for p in parts)}]"


def _suggest(key: str, known: list[str]) -> list[str]:
    related = [k for k in known if key in k or k in key]
    scores = {k: difflib.SequenceMatcher(None, key, k).ratio() for k in known}
    best = max(scores.values(), default=0.0)
    close = [k for k in known if scores[k] >= 0.6 and scores[k] >= best - 0.1]  # only the nearest spellings
    return list(dict.fromkeys(related + close))


def _describe(path: Path, err: dict[str, Any]) -> str:
    loc = tuple(err["loc"])
    where = f"{path}{_section_label(loc)}"
    key = loc[-1] if loc else "?"
    if err["type"] == "extra_forbidden":
        model = _section_model(loc)
        hints = _suggest(str(key), list(model.model_fields)) if model else []
        hint = f" (did you mean {' / '.join(hints)}?)" if hints else ""
        return f"{where}: unknown key '{key}'{hint}"
    return f"{where}: '{key}' {err['msg']}"
