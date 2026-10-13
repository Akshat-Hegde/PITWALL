"""Final-review fixes: PINs kept on re-save, setup-code --reset, backup catch-up, restore warning, demo backups."""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess

from simtelemetry import __main__ as cli
from simtelemetry.config import AppConfig, load_config
from simtelemetry.core.settings import SettingsStore
from simtelemetry.core.setup_code import SetupCode
from simtelemetry.hub import catch_up_due

from test_drivers import make_hub
from test_setup_api import GOOD, _client


def _ms(t: dt.datetime) -> int:
    return round(t.timestamp() * 1000)


# --- finding 2: blank PIN fields keep the PINs ------------------------------------------------------------

def test_resave_with_blank_pins_keeps_both(tmp_path):
    hub, client, code = _client(tmp_path)
    assert client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code).status_code == 200
    r = client.post("/api/setup", json={**GOOD, "name": "Renamed", "owner_pin": "", "staff_pin": ""},
                    headers={"X-Owner-Pin": "2468"})
    assert r.status_code == 200
    assert hub.config.cafe.name == "Renamed"
    assert hub.config.owner.pin == "2468" and hub.config.staff.pin == "1357"
    saved = SettingsStore(tmp_path).load()
    assert saved.owner_pin == "2468" and saved.staff_pin == "1357"
    assert client.get("/api/staff/rigs").status_code == 401           # /staff is still locked


def test_remove_staff_pin_is_explicit(tmp_path):
    hub, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code)
    r = client.post("/api/setup", json={**GOOD, "owner_pin": "", "staff_pin": "", "remove_staff_pin": True},
                    headers={"X-Owner-Pin": "2468"})
    assert r.status_code == 200 and hub.config.staff.pin == "" and hub.config.owner.pin == "2468"
    assert client.get("/api/staff/rigs").status_code == 200           # /staff follows: open now


def test_new_pins_replace_old_ones_and_owner_pin_is_required_before_setup(tmp_path):
    hub, client, code = _client(tmp_path)
    r = client.post("/api/setup", json={**GOOD, "owner_pin": ""}, headers=code)
    assert r.status_code == 400                                       # first run: owner PIN required
    client.post("/api/setup", json=GOOD, headers=code)
    r = client.post("/api/setup", json={**GOOD, "owner_pin": "9999", "staff_pin": "4321"},
                    headers={"X-Owner-Pin": "2468"})
    assert r.status_code == 200 and hub.config.owner.pin == "9999" and hub.config.staff.pin == "4321"


# --- finding 5: setup-code --reset --------------------------------------------------------------------------

def test_setup_code_reset_reopens_setup_without_restart(tmp_path, capsys):
    hub, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code)
    assert client.get("/api/setup").json()["setup_done"] is True
    assert cli.main(["setup-code", "--reset", "--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    new_code = SetupCode(tmp_path).current()
    assert new_code and new_code in out and "/setup" in out
    saved = SettingsStore(tmp_path).load()
    assert saved.setup_done is False and saved.name == "Lap Lab" and saved.staff_pin == "1357"   # the rest is kept
    state = client.get("/api/setup").json()                           # same running hub: no restart
    assert state["setup_done"] is False and state["needs_code"] is True
    assert client.post("/api/setup", json={**GOOD, "owner_pin": "8642"},
                       headers={"X-Owner-Pin": "2468"}).status_code == 401      # the old PIN no longer opens it
    r = client.post("/api/setup", json={**GOOD, "owner_pin": "8642"}, headers={"X-Setup-Code": new_code})
    assert r.status_code == 200 and hub.config.owner.pin == "8642"
    assert SetupCode(tmp_path).current() is None
    assert client.post("/api/setup", json={**GOOD, "owner_pin": ""}, headers={"X-Owner-Pin": "8642"}).status_code == 200


def test_setup_code_reset_before_any_setup_just_makes_a_code(tmp_path, capsys):
    assert cli.main(["setup-code", "--reset", "--data-dir", str(tmp_path)]) == 0
    assert SetupCode(tmp_path).current() in capsys.readouterr().out
    assert SettingsStore(tmp_path).load() is None


# --- finding 3: backup catch-up -----------------------------------------------------------------------------

def test_catch_up_due():
    now = dt.datetime(2026, 10, 13, 12, 0)
    assert catch_up_due(None, now) is True
    assert catch_up_due(_ms(now - dt.timedelta(hours=25)), now) is True
    assert catch_up_due(_ms(now - dt.timedelta(hours=23)), now) is False
    assert catch_up_due(_ms(now - dt.timedelta(minutes=5)), now) is False


async def test_backup_loop_catches_up_and_survives_any_exception(tmp_path, monkeypatch):
    import asyncio
    from simtelemetry import hub as hub_mod
    hub = make_hub(tmp_path)
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("not an OSError")

    monkeypatch.setattr(hub, "run_backup", boom)
    monkeypatch.setattr(hub_mod, "CATCH_UP_DELAY_S", 0.0)
    task = asyncio.create_task(hub.backup_loop())
    await asyncio.sleep(0.3)
    assert calls == [1]                                               # no backup yet: one catch-up attempt
    assert not task.done()                                            # ...and the loop is still alive
    task.cancel()


# --- finding 1: warning when the start-up task is enabled -------------------------------------------------------

def _fake_run(stdout="", returncode=0):
    return lambda *a, **k: subprocess.CompletedProcess(a[0], returncode, stdout=stdout, stderr="")


def test_task_enabled_parses_schtasks_csv(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run('"\\Pitwall Hub","N/A","Ready"\n'))
    assert cli.task_enabled("Pitwall Hub") is True
    monkeypatch.setattr(subprocess, "run", _fake_run('"\\Pitwall Hub","N/A","Disabled"\n'))
    assert cli.task_enabled("Pitwall Hub") is False
    monkeypatch.setattr(subprocess, "run", _fake_run("", returncode=1))
    assert cli.task_enabled("Pitwall Hub") is None
    monkeypatch.setattr(subprocess, "run", _fake_run("garbage"))
    assert cli.task_enabled("Pitwall Hub") is None

    def missing(*a, **k):
        raise FileNotFoundError("schtasks")
    monkeypatch.setattr(subprocess, "run", missing)
    assert cli.task_enabled("Pitwall Hub") is None


def test_restore_warning_only_when_frozen_on_windows_with_enabled_task(monkeypatch):
    monkeypatch.setattr(cli.paths, "is_frozen", lambda: False)
    monkeypatch.setattr(cli, "task_enabled", lambda name: True)
    assert cli.restore_task_warning() is None                        # from source: never asks Windows
    monkeypatch.setattr(cli.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    assert "Disable" in cli.restore_task_warning()
    monkeypatch.setattr(cli, "task_enabled", lambda name: False)
    assert cli.restore_task_warning() is None
    monkeypatch.setattr(cli, "task_enabled", lambda name: None)
    assert cli.restore_task_warning() is None


# --- finding 8: demo backups go to their own folder -------------------------------------------------------------

def test_demo_backups_use_a_demo_folder(monkeypatch, tmp_path):
    from simtelemetry.tools import seed_demo
    monkeypatch.setattr(seed_demo, "seed", lambda d, *a, **k: {"sessions": 0, "laps": 0})
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path))
    config = AppConfig()
    cli.prepare_demo(argparse.Namespace(data_dir=None), config)
    assert config.backups_dir == tmp_path / "backups-demo"
    config = AppConfig()
    config.backup.directory = tmp_path / "mine"
    cli.prepare_demo(argparse.Namespace(data_dir=None), config)
    assert config.backups_dir == tmp_path / "mine"                   # an explicit choice is respected


# --- finding 4: the starter config changes nothing ----------------------------------------------------------------

def test_starter_config_equals_the_defaults():
    from simtelemetry import paths
    example = paths.REPO_ROOT / "config" / "hub.example.toml"
    text = example.read_text(encoding="utf-8")
    assert "[backup]" in text and "directory" in text
    cfg = load_config(example)
    default = AppConfig()
    default.data_dir = cfg.data_dir                                   # both anchored to the home folder
    assert cfg.model_dump() == default.model_dump()
