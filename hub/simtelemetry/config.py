"""Hub configuration: TOML file -> validated pydantic model. No cafe data is hard-coded."""

from __future__ import annotations

import difflib
import tomllib
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_CONFIG_PATH = Path("config/hub.toml")


class ConfigError(Exception):
    """Invalid config file; the message is meant to be shown to the user as-is."""


class _Section(BaseModel):
    # Unknown keys are errors: a misspelt or outdated key must not be silently ignored.
    model_config = ConfigDict(extra="forbid")


class CafeConfig(_Section):
    name: str = "Sim Racing Cafe"
    # CSS custom properties for the dashboard, e.g. {"--brand-accent" = "#e10600"}.
    branding: dict[str, str] = Field(default_factory=dict)


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


class HealthConfig(_Section):
    summary_interval_s: float = 10.0
    no_motion_after_s: float = 2.0  # packets but no Motion for this long -> "in menu / paused"
    no_data_after_s: float = 5.0    # no packets at all for this long -> "no data"


class RigConfig(_Section):
    ip: str
    name: str | None = None
    colour: str | None = None


class AppConfig(_Section):
    data_dir: Path = Path("data")
    cafe: CafeConfig = Field(default_factory=CafeConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    recorder: RecorderConfig = Field(default_factory=RecorderConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    rigs: list[RigConfig] = Field(default_factory=list)
    track_names: dict[int, str] = Field(default_factory=dict)  # trackId -> display name override

    def rig_by_ip(self, ip: str) -> RigConfig | None:
        return next((r for r in self.rigs if r.ip == ip), None)


def load_config(path: Path | None = None) -> AppConfig:
    """Load the given file, else config/hub.toml if present, else defaults."""
    if path is None:
        if not DEFAULT_CONFIG_PATH.exists():
            return AppConfig()
        path = DEFAULT_CONFIG_PATH
    with path.open("rb") as f:
        data = tomllib.load(f)
    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        problems = "\n".join(f"  {_describe(path, err)}" for err in exc.errors())
        raise ConfigError(f"Invalid config file {path}:\n{problems}") from None


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
