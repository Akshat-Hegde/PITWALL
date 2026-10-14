"""Hub configuration: TOML file -> validated pydantic model. No cafe data is hard-coded."""

from __future__ import annotations

import difflib
import re
import tomllib
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator

from . import paths


class ConfigError(Exception):
    """Invalid config file; the message is meant to be shown to the user as-is."""


class _Section(BaseModel):
    # Unknown keys are errors: a misspelt or outdated key must not be silently ignored.
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


class StaffConfig(_Section):
    # PIN for the /staff page (setting driver names). Empty = no PIN; anyone on the LAN can change names.
    pin: str = ""


class OwnerConfig(_Section):
    # PIN for the /owner analytics page. Empty = the owner page is locked (it shows business figures).
    pin: str = ""
    # Opening hours, for rig utilisation (local hours, close after open).
    open_hour: int = Field(10, ge=0, le=23)
    close_hour: int = Field(22, ge=1, le=24)

    @field_validator("close_hour")
    @classmethod
    def _close_after_open(cls, value: int, info: ValidationInfo) -> int:
        opens = info.data.get("open_hour")
        if opens is not None and value <= opens:
            raise ValueError(f"must be after open_hour ({opens})")
        return value


class LeaderboardConfig(_Section):
    # "Today" starts at this hour (local time), so a session running past midnight stays on one day.
    day_start_hour: int = Field(0, ge=0, le=23)


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

    def rig_by_ip(self, ip: str) -> RigConfig | None:
        return next((r for r in self.rigs if r.ip == ip), None)

    @property
    def recordings_dir(self) -> Path:
        return self.recorder.directory or self.data_dir / "recordings"

    @property
    def backups_dir(self) -> Path:
        return self.backup.directory or self.data_dir.parent / "backups"


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
