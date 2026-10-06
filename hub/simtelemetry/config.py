"""Hub configuration: TOML file -> validated pydantic model. No cafe data is hard-coded."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path("config/hub.toml")


class CafeConfig(BaseModel):
    name: str = "Sim Racing Cafe"
    # CSS custom properties for the dashboard, e.g. {"--brand-accent" = "#e10600"}.
    branding: dict[str, str] = Field(default_factory=dict)


class NetworkConfig(BaseModel):
    udp_host: str = "0.0.0.0"
    udp_port: int = Field(20777, ge=1, le=65535)
    udp_receive_buffer_bytes: int = 4 * 1024 * 1024
    http_host: str = "0.0.0.0"
    http_port: int = Field(8000, ge=1, le=65535)


class RecorderConfig(BaseModel):
    enabled: bool = True
    max_file_mb: int = Field(256, ge=1)
    keep_files: int = Field(24, ge=0)  # 0 = never delete old recordings


class HealthConfig(BaseModel):
    summary_interval_s: float = 10.0
    no_motion_after_s: float = 2.0  # packets but no Motion for this long -> "in menu / paused"
    no_data_after_s: float = 5.0    # no packets at all for this long -> "no data"


class RigConfig(BaseModel):
    ip: str
    name: str | None = None
    colour: str | None = None


class AppConfig(BaseModel):
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
        return AppConfig.model_validate(tomllib.load(f))
