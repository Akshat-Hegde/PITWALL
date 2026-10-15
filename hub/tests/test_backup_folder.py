"""K11 and K3 backups: what goes in a backup, the backup folder chosen on the owner page, plain-English errors
and the "Last backup: 5 days ago" warning (owner page and staff Health, never the TV)."""

from __future__ import annotations

import datetime as dt
import errno
import json
import logging
import os
import sqlite3
import string
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from simtelemetry.__main__ import main
from simtelemetry.api.app import create_app
from simtelemetry.core import backup as backup_mod
from simtelemetry.core.backup import (DISK_FULL, GENERIC_FAILURE, NO_PERMISSION, NOT_A_FOLDER, STATUS_FILE, WHOLE_PATH,
                                      BackupFailed, BackupStatus, check_folder, make_backup, plain_backup_error,
                                      restore)
from simtelemetry.core.feed import FeedBuilder
from simtelemetry.core.settings import CafeSettings, SettingsStore, apply_settings, recover_damaged_settings

from f1_helpers import STAFF, staff_ready
from test_drivers import make_hub
from test_setup_api import GOOD, _client

OWNER = {"X-Owner-Pin": "2468"}
DAY = 86400.0
NOW = dt.datetime(2026, 10, 15, 12, 0).timestamp()


def missing_drive() -> str:
    """A drive letter that isn't there on this PC (like an unplugged USB stick)."""
    for letter in reversed(string.ascii_uppercase[3:]):
        if not os.path.exists(f"{letter}:\\"):
            return f"{letter}:"
    pytest.skip("every drive letter is in use")


def never_exists(path):
    return False


# --- what a backup holds --------------------------------------------------------------------------------------

def test_backup_includes_checkin_codes_and_logos_and_restore_puts_them_back(tmp_path):
    data = tmp_path / "data"
    (data / "logos").mkdir(parents=True)
    (data / "logos" / "acme.png").write_bytes(b"png")
    (data / "checkin.json").write_text('{"192.168.1.21": "K7Q2"}', encoding="utf-8")
    z = make_backup(data, None, tmp_path / "bk", dt.datetime(2026, 10, 15, 4, 0))
    assert {"checkin.json", "logos/acme.png"} <= set(zipfile.ZipFile(z).namelist())
    (data / "checkin.json").unlink()
    (data / "logos" / "acme.png").unlink()
    restore(z, data, None)
    assert (data / "checkin.json").read_text(encoding="utf-8") == '{"192.168.1.21": "K7Q2"}'
    assert (data / "logos" / "acme.png").read_bytes() == b"png"


# --- plain-English errors -------------------------------------------------------------------------------------

def test_backup_errors_in_plain_english():
    folder = Path("E:\\Backups")
    assert plain_backup_error(FileNotFoundError(2, "x"), folder, never_exists) == \
        "The USB stick isn't plugged in (drive E: not found)."
    present = (lambda p: True)
    assert plain_backup_error(PermissionError(13, "Access is denied"), folder, present) == NO_PERMISSION
    assert NO_PERMISSION == "Windows won't let the hub write to that folder. Choose another folder."
    assert plain_backup_error(OSError(errno.ENOSPC, "No space left"), folder, present) == DISK_FULL == \
        "The backup drive is full."
    assert plain_backup_error(sqlite3.OperationalError("database or disk is full"), folder, present) == DISK_FULL
    assert plain_backup_error(NotADirectoryError(20, "x"), folder, present) == NOT_A_FOLDER
    assert plain_backup_error(RuntimeError("boom"), folder, present) == GENERIC_FAILURE
    assert plain_backup_error(OSError(5, "odd"), Path("\\\\nas\\share"), never_exists) == GENERIC_FAILURE


@pytest.mark.skipif(os.name != "nt", reason="Windows error codes")
def test_windows_error_codes():
    folder = Path("E:\\Backups")
    present = (lambda p: True)
    assert plain_backup_error(OSError(None, "disk full", None, 112), folder, present) == DISK_FULL
    assert plain_backup_error(OSError(None, "denied", None, 5), folder, present) == NO_PERMISSION
    assert plain_backup_error(OSError(None, "not ready", None, 21), folder, present).startswith(
        "The USB stick isn't plugged in (drive E:")


# --- choosing the folder ----------------------------------------------------------------------------------------

def test_check_folder_accepts_backslash_paths_and_creates_the_folder(tmp_path):
    wanted = str(tmp_path / "USB" / "Backups")             # backslashes on Windows
    assert check_folder(wanted) == Path(wanted) and Path(wanted).is_dir()
    assert check_folder(f'  "{wanted}"  ') == Path(wanted)  # pasted with Explorer's "Copy as path" quotes
    assert not list(Path(wanted).iterdir())                 # the test file is gone again
    assert check_folder("") is None and check_folder("   ") is None


def test_check_folder_says_what_is_wrong(tmp_path):
    with pytest.raises(BackupFailed) as e:
        check_folder("Backups")
    assert e.value.text == WHOLE_PATH
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(BackupFailed) as e:
        check_folder(str(tmp_path / "file.txt"))
    assert e.value.text == NOT_A_FOLDER
    drive = missing_drive()
    with pytest.raises(BackupFailed) as e:
        check_folder(f"{drive}\\Backups")
    assert e.value.text == f"Drive {drive} isn't available to the hub. Use a USB stick or a folder on this PC."


def test_check_folder_permission_problem(tmp_path, monkeypatch):
    def denied(self, *a, **k):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(Path, "write_bytes", denied)
    with pytest.raises(BackupFailed) as e:
        check_folder(str(tmp_path / "locked"))
    assert e.value.text == NO_PERMISSION


def test_owner_chooses_the_backup_folder_and_it_survives_setup_and_restart(tmp_path, tmp_path_factory):
    hub, client, code = _client(tmp_path)
    assert client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code).status_code == 200
    usb = tmp_path_factory.mktemp("E") / "Backups"           # outside the data folder (tmp_path here)
    before = client.get("/api/owner/backup", headers=OWNER).json()
    assert before["chosen"] == "" and before["directory"] == before["default_directory"]
    r = client.post("/api/owner/backup/folder", json={"folder": str(usb)}, headers=OWNER)
    assert r.status_code == 200, r.text
    assert r.json()["chosen"] == str(usb) and r.json()["directory"] == str(usb)
    assert hub.config.backups_dir == usb
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["backup_dir"] == str(usb)
    done = client.post("/api/owner/backup", headers=OWNER)
    assert done.status_code == 200 and len(list(usb.glob("*.zip"))) == 1
    assert done.json()["last_ok_at"] is not None and done.json()["last_error"] is None
    # Re-saving the setup page keeps the folder, and a restart reads it back.
    assert client.post("/api/setup", json={**GOOD, "owner_pin": "", "staff_pin": ""},
                       headers=OWNER).status_code == 200
    saved = SettingsStore(tmp_path).load()
    assert saved.backup_dir == str(usb)
    fresh = make_hub(tmp_path / "other")
    apply_settings(fresh.config, saved)
    assert fresh.config.backups_dir == usb
    # Empty goes back to the default folder (hub.toml's, or the standard one).
    back = client.post("/api/owner/backup/folder", json={"folder": ""}, headers=OWNER).json()
    assert back["chosen"] == "" and back["directory"] == back["default_directory"]
    assert SettingsStore(tmp_path).load().backup_dir == ""


def test_hub_toml_folder_is_the_fallback(tmp_path):
    toml_dir = tmp_path / "toml-backups"
    hub = make_hub(tmp_path, backup={"directory": toml_dir})
    assert hub.config.backups_dir == toml_dir
    hub.config.set_owner_backup_dir(tmp_path / "usb")
    assert hub.config.backups_dir == tmp_path / "usb" and hub.config.default_backups_dir == toml_dir


def test_owner_folder_errors_are_plain(tmp_path):
    hub, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code)
    drive = missing_drive()
    r = client.post("/api/owner/backup/folder", json={"folder": f"{drive}\\Backups"}, headers=OWNER)
    assert r.status_code == 400 and r.json()["detail"] == f"Drive {drive} isn't available to the hub. Use a USB stick or a folder on this PC."
    assert SettingsStore(tmp_path).load().backup_dir == ""
    assert client.post("/api/owner/backup/folder", json={"folder": "x"}).status_code == 401


def test_choosing_a_folder_before_setup_says_finish_setup(tmp_path, tmp_path_factory):
    hub = make_hub(tmp_path, owner={"pin": "2468"})
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    r = client.post("/api/owner/backup/folder", json={"folder": str(tmp_path_factory.mktemp("usb"))}, headers=OWNER)
    assert r.status_code == 409 and r.json()["detail"].startswith("Finish setup first")


def test_back_up_now_failure_is_plain_and_the_raw_error_is_logged(tmp_path, caplog):
    hub = make_hub(tmp_path, owner={"pin": "2468"})
    drive = missing_drive()
    hub.config.set_owner_backup_dir(Path(f"{drive}\\Backups"))
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    with caplog.at_level(logging.ERROR):
        r = client.post("/api/owner/backup", headers=OWNER)
    assert r.status_code == 503
    assert r.json()["detail"] == f"The USB stick isn't plugged in (drive {drive} not found)."
    assert "Errno" not in r.text and "WinError" not in r.text
    assert any(rec.exc_info for rec in caplog.records)                 # the raw error is in the log
    status = client.get("/api/owner/backup", headers=OWNER).json()
    assert status["last_error"] == r.json()["detail"]


async def test_nightly_backup_failure_is_recorded_in_plain_english(tmp_path, monkeypatch):
    hub = make_hub(tmp_path)

    def full(*a, **k):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(backup_mod, "make_backup", full)
    await hub._backup_once("Backup")
    assert hub.backup_status.last_error == DISK_FULL
    saved = json.loads((tmp_path / STATUS_FILE).read_text(encoding="utf-8"))
    assert saved["last_error"] == DISK_FULL


# --- the warning ---------------------------------------------------------------------------------------------------

def test_warning_after_two_days_without_a_backup(tmp_path):
    now = [NOW]
    s = BackupStatus(tmp_path / STATUS_FILE, first_use=NOW - 1 * DAY, clock=lambda: now[0])
    assert s.warning() is None                                          # new hub: give it two days
    now[0] = NOW + 1.5 * DAY
    assert s.warning() == "No backup has been made yet. Check the backup folder or USB stick."
    s.ok(tmp_path / "bk")
    assert s.warning() is None
    now[0] += 5 * DAY + 3600
    assert s.warning() == "Last backup: 5 days ago. Check the backup folder or USB stick."
    again = BackupStatus(tmp_path / STATUS_FILE, clock=lambda: now[0])  # remembered across restarts
    assert again.warning() == "Last backup: 5 days ago. Check the backup folder or USB stick."
    assert again.last_ok_folder == str(tmp_path / "bk")


def test_two_days_exactly_is_not_yet_a_warning(tmp_path):
    s = BackupStatus(None, first_use=NOW - 10 * DAY, seed_last_ok=NOW - 2 * DAY, clock=lambda: NOW)
    assert s.warning() is None
    s = BackupStatus(None, first_use=NOW - 10 * DAY, seed_last_ok=NOW - 2 * DAY - 60, clock=lambda: NOW)
    assert s.warning() == "Last backup: 2 days ago. Check the backup folder or USB stick."


def test_staff_health_and_owner_page_show_the_warning_but_not_the_tv(tmp_path):
    hub = staff_ready(make_hub(tmp_path, owner={"pin": "2468"}))
    hub.backup_status.last_ok = time.time() - 5 * DAY - 60
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    health = client.get("/api/staff/health", headers=STAFF).json()
    (w,) = [w for w in health["warnings"] if w["code"] == "backup_old"]
    assert w["message"] == "Last backup: 5 days ago. Check the backup folder or USB stick."
    assert client.get("/api/owner/backup", headers=OWNER).json()["warning"] == w["message"]
    snapshot = json.dumps(FeedBuilder(hub).snapshot_body(time.monotonic()), default=str)
    assert "Last backup" not in snapshot and "backup_warning" not in snapshot
    hub.config.features.backup_warning = False                        # switched off in [features]
    assert not [w for w in client.get("/api/staff/health", headers=STAFF).json()["warnings"]
                if w["code"] == "backup_old"]


def test_no_warning_right_after_a_backup(tmp_path):
    hub = staff_ready(make_hub(tmp_path, owner={"pin": "2468"}, backup={"directory": tmp_path / "bk"}))
    hub.backup_status.first_use = time.time() - 30 * DAY
    assert hub.backup_warning() == "No backup has been made yet. Check the backup folder or USB stick."
    hub.run_backup()
    assert hub.backup_warning() is None


def test_existing_backups_count_on_first_start(tmp_path):
    bk = tmp_path / "bk"
    bk.mkdir()
    (bk / "pitwall-20261015-0400.zip").write_bytes(b"x")
    hub = make_hub(tmp_path, backup={"directory": bk})
    assert hub.backup_status.last_ok is not None


# --- the backup command and settings recovery -----------------------------------------------------------------------

def test_backup_command_uses_the_owner_folder_and_records_it(tmp_path, capsys):
    data = tmp_path / "data"
    usb = tmp_path / "usb"
    SettingsStore(data).save(CafeSettings(name="Lap Lab", owner_pin="2468", staff_pin="1357", setup_done=True,
                                          backup_dir=str(usb)))
    toml = tmp_path / "hub.toml"
    toml.write_text(f'data_dir = "{data.as_posix()}"\n', encoding="utf-8")
    assert main(["backup", "--config", str(toml)]) == 0
    assert len(list(usb.glob("*.zip"))) == 1
    assert json.loads((data / STATUS_FILE).read_text(encoding="utf-8"))["last_ok_folder"] == str(usb)


def test_damaged_settings_are_found_in_the_last_backup_folder(tmp_path):
    data = tmp_path / "data"
    usb = tmp_path / "usb"
    store = SettingsStore(data)
    store.save(CafeSettings(name="Lap Lab", owner_pin="2468", staff_pin="1357", setup_done=True,
                            backup_dir=str(usb)))
    make_backup(data, None, usb, dt.datetime(2026, 10, 14, 4, 0))
    backup_mod.record_backup(data, usb)
    store.path.write_text("{not json", encoding="utf-8")
    warning = recover_damaged_settings(store, tmp_path / "default-backups", dt.datetime(2026, 10, 15, 9, 0),
                                       more_dirs=backup_mod.last_backup_folder(data))
    assert warning.startswith("The cafe settings were damaged, so the hub put back the copy from the backup")
    assert store.load().name == "Lap Lab"


# --- Task 5 review fixes ----------------------------------------------------------------------------------------

def test_check_folder_refuses_the_data_folder_and_anything_inside_it(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    for inside in (data, data / "backups", data / "logs" / "deep"):
        with pytest.raises(BackupFailed) as e:
            check_folder(str(inside), data_dir=data)
        assert e.value.text == "Choose a folder outside the hub's data folder."
    assert not (data / "backups").exists() and not (data / "logs").exists()     # nothing was made
    assert check_folder(str(tmp_path / "data-backups"), data_dir=data) == tmp_path / "data-backups"   # a sibling is fine


def test_check_folder_refuses_long_and_network_paths(tmp_path):
    with pytest.raises(BackupFailed) as e:
        check_folder(str(tmp_path / ("x" * 210)))
    assert "too long" in e.value.text
    for unc in (r"\\nas\share\Backups", "//nas/share"):
        with pytest.raises(BackupFailed) as e:
            check_folder(unc)
        assert e.value.text.startswith("Network folders aren't supported")


def test_a_failed_check_leaves_no_test_file_or_new_folders_behind(tmp_path, monkeypatch):
    def denied(self, *a, **k):
        Path.touch(self)                                      # the file got made, then writing failed
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(Path, "write_bytes", denied)
    with pytest.raises(BackupFailed):
        check_folder(str(tmp_path / "new" / "deeper" / "Backups"))
    assert list(tmp_path.iterdir()) == []                     # no folders it made, no test file
    (tmp_path / "kept").mkdir()
    with pytest.raises(BackupFailed):
        check_folder(str(tmp_path / "kept"))
    assert (tmp_path / "kept").is_dir() and list((tmp_path / "kept").iterdir()) == []   # an existing folder stays


def test_owner_page_refuses_the_data_folder_and_says_why_network_drives_fail(tmp_path):
    hub, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code)
    r = client.post("/api/owner/backup/folder", json={"folder": str(tmp_path / "backups")}, headers=OWNER)
    assert r.status_code == 400 and r.json()["detail"] == "Choose a folder outside the hub's data folder."
    assert SettingsStore(tmp_path).load().backup_dir == ""
    page = client.get("/owner").text
    assert "Network folders and mapped drives (like Z:)" in page and 'maxlength="200"' in page


def test_a_bad_backup_folder_value_never_reaches_settings_json(tmp_path, monkeypatch, tmp_path_factory):
    """Even if a value got past check_folder, the whole settings are validated before saving."""
    from simtelemetry.api import owner as owner_api
    hub, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code)
    monkeypatch.setattr(owner_api, "check_folder", lambda *a, **k: Path("E:\\" + "x" * 300))
    r = client.post("/api/owner/backup/folder", json={"folder": "anything"}, headers=OWNER)
    assert r.status_code == 400 and "too long" in r.json()["detail"]
    assert SettingsStore(tmp_path).read().backup_dir == ""                      # still readable, unchanged
