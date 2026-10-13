"""Where Pitwall keeps its app files and the cafe's files (source checkout vs installed exe)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simtelemetry import paths
from simtelemetry.config import AppConfig, load_config

REPO = Path(__file__).resolve().parents[2]


def test_source_checkout_uses_the_working_folder(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("PITWALL_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    assert not paths.is_frozen()
    assert paths.home() == tmp_path
    assert paths.config_path() == tmp_path / "config" / "hub.toml"
    assert paths.dashboard_dir() == REPO / "dashboard" / "dist"


def test_installed_exe_uses_program_data(monkeypatch, tmp_path):
    bundle = tmp_path / "Program Files" / "Pitwall" / "_internal"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    monkeypatch.delenv("PITWALL_HOME", raising=False)
    assert paths.app_dir() == bundle
    assert paths.dashboard_dir() == bundle / "dashboard"
    assert paths.home() == tmp_path / "ProgramData" / "Pitwall"


def test_pitwall_home_overrides_both(monkeypatch, tmp_path):
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path / "cafe"))
    assert paths.home() == tmp_path / "cafe"
    assert paths.config_path() == tmp_path / "cafe" / "config" / "hub.toml"


def test_relative_data_dir_lands_in_home(monkeypatch, tmp_path):
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "hub.toml").write_text('data_dir = "data"\n[cafe]\nname = "Lap Lab"\n', encoding="utf-8")
    config = load_config()
    assert config.cafe.name == "Lap Lab"
    assert config.data_dir == tmp_path / "data"


def test_no_config_file_still_puts_data_in_home(monkeypatch, tmp_path):
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path))
    assert load_config().data_dir == tmp_path / "data"


def test_demo_default_data_dir_lands_in_home(monkeypatch, tmp_path):
    from simtelemetry import __main__ as cli
    from simtelemetry.tools import seed_demo
    seen = []
    monkeypatch.setattr(seed_demo, "seed", lambda d, *a, **k: seen.append(d) or {"sessions": 0, "laps": 0})
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path))
    config = AppConfig()
    cli.prepare_demo(argparse.Namespace(data_dir=None), config)
    assert config.data_dir == tmp_path / "data-demo"
    assert seen == [tmp_path / "data-demo"]


def test_seed_demo_default_resolves_at_use_time(monkeypatch, tmp_path):
    from simtelemetry import __main__ as cli
    from simtelemetry.tools import seed_demo
    seen = []
    monkeypatch.setattr(seed_demo, "seed", lambda d, *a, **k: seen.append(d) or
                        {"sessions": 0, "laps": 0, "drivers": 0, "profiles": 0})
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path))
    assert cli.main(["seed-demo"]) == 0
    assert seen == [tmp_path / "data-demo"]
