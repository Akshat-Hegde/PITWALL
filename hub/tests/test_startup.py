"""K1/K2/K13: the hub starts whatever state its files are in, and says what went wrong where the owner looks."""

from __future__ import annotations

import datetime as dt
import json
import socket
import sqlite3
import threading
import time
import urllib.request
import zipfile

import pytest
from fastapi.testclient import TestClient

from simtelemetry import __main__ as cli
from simtelemetry import startup
from simtelemetry.api.app import create_app
from simtelemetry.core.backup import make_backup
from simtelemetry.core.pins import verify_pin
from simtelemetry.core.settings import CafeSettings, SettingsStore, recover_damaged_settings
from simtelemetry.core.store import LapStore, open_lap_store
from simtelemetry.startup import START_ERROR_FILE

from f1_helpers import STAFF, staff_ready
from test_cli import free_port
from test_drivers import make_hub

NOW = dt.datetime(2026, 10, 15, 9, 30, 0)
OWNER_AS_STAFF = {"X-Staff-Pin": "2468"}


def wait_for_server(port, timeout=10.0):
    """Poll the hub's /api/health every 0.1 s until it answers (up to `timeout` s); False if it never did."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run_hub_briefly(argv, poll_paths=(), during=None, duration="15", headers=None):
    """main(["run", ...]) on free ports, fetching the given API paths (with headers) once it answers, then stopping
    it. The staff pages need a PIN: the hub gets owner PIN 2468 (no staff PIN set, so the owner PIN opens them).
    `headers` are sent too (a setup code, say: /api/setup shows its warnings only to the owner)."""
    results: dict[str, object] = {}
    if any(p.startswith("/api/staff") for p in poll_paths):
        argv = [*argv, "--owner-pin", "2468"]

    def poll():
        try:
            port = argv[argv.index("--http-port") + 1]
            assert wait_for_server(port), "the hub never answered"
            if during:
                during()
            for path in poll_paths:
                request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={**OWNER_AS_STAFF, **(headers or {})})
                with urllib.request.urlopen(request, timeout=5) as r:
                    results[path] = json.load(r)
        finally:
            cli.request_stop()
    poller = threading.Thread(target=poll)
    poller.start()
    code = cli.main([*argv, "--duration", duration])
    poller.join()
    return code, results


def ports():
    return ["--port", str(free_port()), "--http-port", str(free_port(socket.SOCK_STREAM))]


# --- hub.toml ---------------------------------------------------------------------------------------------

def test_bad_hub_toml_starts_with_defaults_and_warns_staff_and_setup(tmp_path):
    config = tmp_path / "hub.toml"
    config.write_text("[recorder]\nenabled_in_run = tru\n", encoding="utf-8")
    from simtelemetry.core.setup_code import SetupCode
    setup = {"X-Setup-Code": SetupCode(tmp_path / "data").new()}
    code, got = run_hub_briefly(["run", "--config", str(config), "--data-dir", str(tmp_path / "data"), *ports()],
                                ["/api/setup", "/api/staff/health"], headers=setup)
    assert code == 0
    setup_msgs = [w["message"] for w in got["/api/setup"]["warnings"]]
    assert setup_msgs == ["Your settings file (hub.toml) has a mistake on line 2: Invalid value. "
                          "The hub started with default settings."]
    staff = got["/api/staff/health"]["warnings"]
    assert {"code": "config", "rig_id": None, "message": setup_msgs[0]} in staff
    log_text = (tmp_path / "data" / "logs" / "hub.log").read_text(encoding="utf-8")
    assert "line 2, column 18: TOML syntax error" in log_text


def test_startup_warnings_never_reach_the_tv_feed(tmp_path):
    from simtelemetry.core.feed import FeedBuilder
    hub = make_hub(tmp_path)
    hub.add_startup_warning("config", "Your settings file (hub.toml) has a mistake on line 2")
    hub.udp_busy = "Another program is using port 20777 (often SimHub)."
    text = json.dumps(FeedBuilder(hub).status(time.monotonic()))
    assert "hub.toml" not in text and "SimHub" not in text
    assert len(hub.admin_warnings()) == 2


# --- logging and last-start-error.txt ------------------------------------------------------------------------

def test_logging_starts_before_the_config_in_the_fallback_folder(tmp_path, monkeypatch):
    from simtelemetry import brand
    monkeypatch.setenv(brand.HOME_ENV, str(tmp_path))
    config = tmp_path / "config" / "hub.toml"
    config.parent.mkdir()
    config.write_text("[network\n", encoding="utf-8")
    seen = {}

    def fake_run_command(args, cfg, problems=()):
        seen["problems"] = problems
        raise RuntimeError("boom")
    monkeypatch.setattr(cli, "run_command", fake_run_command)
    assert cli.main(["run"]) == 1
    log_text = (tmp_path / "data" / "logs" / "hub.log").read_text(encoding="utf-8")
    assert "TOML syntax error" in log_text                       # the config problem
    assert "The hub could not start" in log_text and "RuntimeError: boom" in log_text
    note = (tmp_path / "data" / START_ERROR_FILE).read_text(encoding="utf-8")
    first, rest = note.split("\n", 1)
    assert "stopped because of an unexpected error" in first and "Traceback" not in first
    assert "RuntimeError: boom" in rest
    assert len(seen["problems"]) == 1


def test_http_port_busy_writes_last_start_error_and_exits_nonzero(tmp_path, capsys):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("0.0.0.0", 0))
    blocker.listen()
    http_port = blocker.getsockname()[1]
    try:
        code = cli.main(["run", "--port", str(free_port()), "--http-port", str(http_port),
                         "--data-dir", str(tmp_path), "--duration", "1"])
    finally:
        blocker.close()
    assert code == 2
    first = (tmp_path / START_ERROR_FILE).read_text(encoding="utf-8").splitlines()[0]
    assert f"another program is already using port {http_port}" in first
    assert f"HTTP port {http_port} is already in use" in (tmp_path / "logs" / "hub.log").read_text(encoding="utf-8")


def test_clean_start_deletes_last_start_error(tmp_path):
    (tmp_path / START_ERROR_FILE).write_text("old problem\n", encoding="utf-8")
    code, _ = run_hub_briefly(["run", "--data-dir", str(tmp_path), *ports()])
    assert code == 0 and not (tmp_path / START_ERROR_FILE).exists()


def test_write_start_error_never_raises(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("x", encoding="utf-8")
    assert startup.write_start_error(blocked / "sub", "Headline") is None     # a file where the folder should be
    path = startup.write_start_error(tmp_path, "Headline", "details")
    assert path.read_text(encoding="utf-8").startswith("Headline\n\n")


# --- UDP port busy ------------------------------------------------------------------------------------------

def test_udp_port_busy_serves_pages_warns_and_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "UDP_RETRY_S", 0.3)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("0.0.0.0", 0))
    udp_port = blocker.getsockname()[1]
    http_port = free_port(socket.SOCK_STREAM)
    seen = {}

    def during():
        request = urllib.request.Request(f"http://127.0.0.1:{http_port}/api/staff/health", headers=OWNER_AS_STAFF)
        with urllib.request.urlopen(request, timeout=5) as r:
            seen["before"] = json.load(r)["warnings"]
        blocker.close()
        end = time.monotonic() + 5                      # the hub retries the port every 0.3 s here
        while time.monotonic() < end and "is free now" not in (tmp_path / "logs" / "hub.log").read_text("utf-8"):
            time.sleep(0.1)
    code, got = run_hub_briefly(["run", "--port", str(udp_port), "--http-port", str(http_port),
                                 "--data-dir", str(tmp_path)], ["/api/staff/health", "/api/setup"], during=during)
    assert code == 0
    (busy,) = [w for w in seen["before"] if w["code"] == "udp_port_busy"]
    assert busy["message"].startswith(f"Another program is using port {udp_port} (often SimHub). "
                                      "Close it or change its port.")
    assert not [w for w in got["/api/staff/health"]["warnings"] if w["code"] == "udp_port_busy"]
    assert got["/api/setup"]["warnings"] == []
    assert "is free now: listening for rigs" in (tmp_path / "logs" / "hub.log").read_text(encoding="utf-8")


# --- settings.json ------------------------------------------------------------------------------------------

def _settings(name="Lap Lab"):
    return CafeSettings(name=name, owner_pin="2468", staff_pin="1357", setup_done=True)


def test_damaged_settings_are_restored_from_the_newest_backup(tmp_path):
    data, backups = tmp_path / "data", tmp_path / "backups"
    store = SettingsStore(data)
    store.save(_settings("Older"))
    make_backup(data, None, backups, NOW - dt.timedelta(days=1))
    store.save(_settings("Newest"))
    make_backup(data, None, backups, NOW)
    store.path.write_text('{"name": "Lap', encoding="utf-8")          # a power cut mid-write
    message = recover_damaged_settings(store, backups, NOW)
    assert message.startswith("The cafe settings were damaged, so the hub put back the copy from the backup of")
    restored = store.read()
    assert restored.name == "Newest" and verify_pin("2468", restored.owner_pin) and restored.setup_done
    assert (data / "settings.json.broken-20261015-093000").read_text(encoding="utf-8") == '{"name": "Lap'


def test_damaged_settings_skip_a_backup_without_good_settings(tmp_path):
    data, backups = tmp_path / "data", tmp_path / "backups"
    SettingsStore(data).save(_settings("Good"))
    make_backup(data, None, backups, NOW - dt.timedelta(days=1))
    from simtelemetry import brand
    with zipfile.ZipFile(backups / f"{brand.SLUG}-20261015-0400.zip", "w") as z:   # newer, but no good settings
        z.writestr("settings.json", "garbage")
    SettingsStore(data).path.write_text("garbage", encoding="utf-8")
    assert recover_damaged_settings(SettingsStore(data), backups, NOW)
    assert SettingsStore(data).read().name == "Good"


def test_damaged_settings_without_backup_means_setup_mode(tmp_path):
    store = SettingsStore(tmp_path)
    store.path.write_text("nonsense", encoding="utf-8")
    message = recover_damaged_settings(store, tmp_path / "no-backups", NOW)
    assert "no backup" in message and "setup page" in message
    assert "use 'Show setup code' in the Start menu" in message
    assert store.read() is None and (tmp_path / "settings.json.broken-20261015-093000").exists()


def test_good_or_missing_settings_are_left_alone(tmp_path):
    store = SettingsStore(tmp_path)
    assert recover_damaged_settings(store, tmp_path, NOW) is None
    store.save(_settings())
    assert recover_damaged_settings(store, tmp_path, NOW) is None and store.read().name == "Lap Lab"


def test_run_with_damaged_settings_warns_on_setup_page(tmp_path):
    data = tmp_path / "data"
    (data).mkdir()
    (data / "settings.json").write_text("{", encoding="utf-8")
    from simtelemetry.core.setup_code import SetupCode
    setup = {"X-Setup-Code": SetupCode(data).new()}
    code, got = run_hub_briefly(["run", "--data-dir", str(data), *ports()], ["/api/setup"], headers=setup)
    assert code == 0
    state = got["/api/setup"]
    assert state["needs_code"] is True and state["authed"] is True
    assert [w["code"] for w in state["warnings"]] == ["settings_damaged"]
    # Setup isn't finished: the log points to the shortcut but never holds the code (data\logs is open to users)
    log_text = (data / "logs" / "hub.log").read_text(encoding="utf-8")
    assert "Setup isn't finished. Open http://" in log_text
    assert "Use the Start-menu shortcut 'Pitwall Show setup code' to see the code." in log_text
    assert setup["X-Setup-Code"] not in log_text


# --- laps.db ------------------------------------------------------------------------------------------------

def test_damaged_lap_database_is_moved_aside_and_an_empty_one_started(tmp_path):
    db = tmp_path / "laps.db"
    db.write_bytes(b"this is not a database" * 200)
    (tmp_path / "laps.db-wal").write_bytes(b"stale")
    store, message = open_lap_store(db, NOW)
    try:
        assert store.count() == 0 and store.quick_check()
    finally:
        store.close()
    assert "restore the latest backup" in message
    assert (tmp_path / "laps.db.broken-20261015-093000").read_bytes().startswith(b"this is not")


def test_corrupt_pages_fail_the_quick_check(tmp_path):
    db = tmp_path / "laps.db"
    LapStore(db).close()
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("CREATE TABLE filler (x TEXT)")
    con.executemany("INSERT INTO filler VALUES (?)", [("x" * 500,)] * 200)
    con.commit()
    con.close()
    raw = bytearray(db.read_bytes())
    page = 4096
    for i in range(page * 3, len(raw) - page, page):             # scribble over every page after the third
        raw[i + 8:i + 200] = b"\xff" * 192
    db.write_bytes(bytes(raw))
    store, message = open_lap_store(db, NOW)
    store.close()
    assert message is not None and list(tmp_path.glob("laps.db.broken-*"))


def test_healthy_lap_database_is_kept(tmp_path):
    LapStore(tmp_path / "laps.db").close()
    store, message = open_lap_store(tmp_path / "laps.db", NOW)
    store.close()
    assert message is None and not list(tmp_path.glob("*.broken-*"))


def test_run_with_damaged_lap_database_warns_staff(tmp_path):
    (tmp_path / "laps.db").write_bytes(b"garbage" * 100)
    code, got = run_hub_briefly(["run", "--data-dir", str(tmp_path), *ports()], ["/api/staff/health"])
    assert code == 0
    assert [w["code"] for w in got["/api/staff/health"]["warnings"] if w["code"] == "laps_damaged"] == ["laps_damaged"]


# --- keep awake ---------------------------------------------------------------------------------------------

def test_keep_awake_is_a_no_op_in_tests_and_off_windows(monkeypatch):
    assert startup.keep_awake() is False                        # PYTEST_CURRENT_TEST is set
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setattr(startup.sys, "platform", "linux")
    assert startup.keep_awake() is False


def test_keep_awake_asks_windows_to_stay_on(monkeypatch):
    import ctypes
    calls = []

    class Kernel32:
        @staticmethod
        def SetThreadExecutionState(flags):
            calls.append(flags)
            return 1
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setattr(startup.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": Kernel32}), raising=False)
    assert startup.keep_awake() is True
    startup.allow_sleep()
    assert calls == [0x80000001, 0x80000000]


# --- PINs through the API -----------------------------------------------------------------------------------

def test_hashed_pins_unlock_staff_and_owner_pages(tmp_path):
    SettingsStore(tmp_path).save(_settings())
    from simtelemetry.core.settings import apply_settings
    hub = make_hub(tmp_path)
    apply_settings(hub.config, SettingsStore(tmp_path).read())
    client = TestClient(create_app(staff_ready(hub), dashboard_dir=tmp_path / "none"), headers=STAFF)
    assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "1357"}).status_code == 200
    assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "2468"}).status_code == 401
    assert client.get("/api/owner/report", headers={"X-Owner-Pin": "2468"}).status_code == 200
    assert client.get("/api/owner/report", headers={"X-Owner-Pin": "1357"}).status_code == 401
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["owner_pin"].startswith("scrypt$") and raw["staff_pin"].startswith("scrypt$")


@pytest.mark.parametrize("given", ["", "0000"])
def test_wrong_or_missing_pin_is_refused(tmp_path, given):
    SettingsStore(tmp_path).save(_settings())
    from simtelemetry.core.settings import apply_settings
    hub = make_hub(tmp_path)
    apply_settings(hub.config, SettingsStore(tmp_path).read())
    client = TestClient(create_app(staff_ready(hub), dashboard_dir=tmp_path / "none"), headers=STAFF)
    assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": given}).status_code == 401


def test_saving_setup_again_clears_the_damaged_settings_warning(tmp_path):
    from simtelemetry.core.setup_code import SetupCode
    code = SetupCode(tmp_path).new()
    hub = make_hub(tmp_path)
    hub.add_startup_warning("settings_damaged", "The cafe settings were damaged ...")
    hub.add_startup_warning("laps_damaged", "The lap database was damaged ...")
    client = TestClient(create_app(staff_ready(hub), dashboard_dir=tmp_path / "none"), headers=STAFF)
    anon = client.get("/api/setup").json()                  # anyone on the network: only how many
    assert anon["warnings"] == [] and anon["hidden_warnings"] == 2
    assert len(client.get("/api/setup", headers={"X-Setup-Code": code}).json()["warnings"]) == 2
    body = {"name": "Lap Lab", "owner_pin": "2468", "staff_pin": "1357", "open_hour": 10, "close_hour": 22}
    r = client.post("/api/setup", json=body, headers={"X-Setup-Code": code})
    assert r.status_code == 200 and [w["code"] for w in r.json()["warnings"]] == ["laps_damaged"]


def test_hash_shaped_pins_from_the_setup_form_are_refused(tmp_path):
    from simtelemetry.core.pins import hash_pin
    from simtelemetry.core.setup_code import SetupCode
    code = SetupCode(tmp_path).new()
    client = TestClient(create_app(staff_ready(make_hub(tmp_path)), dashboard_dir=tmp_path / "none"), headers=STAFF)
    stolen = hash_pin("9999")
    for field in ("owner_pin", "staff_pin"):
        body = {"name": "Lap Lab", "owner_pin": "2468", "staff_pin": "1357", "open_hour": 10, "close_hour": 22,
                field: stolen}
        r = client.post("/api/setup", json=body, headers={"X-Setup-Code": code})
        assert r.status_code == 422 and r.json()["detail"] == "A PIN is 4 to 8 digits."
    assert SettingsStore(tmp_path).read() is None
    body = {"name": "Lap Lab", "owner_pin": "2468", "staff_pin": "1357", "open_hour": 10, "close_hour": 22}
    assert client.post("/api/setup", json=body, headers={"X-Setup-Code": code}).status_code == 200
    r = client.post("/api/setup", json={**body, "owner_pin": stolen}, headers={"X-Owner-Pin": "2468"})
    assert r.status_code == 422
    assert verify_pin("2468", SettingsStore(tmp_path).read().owner_pin)


# --- settings.json that can't be read (not damaged) ---------------------------------------------------------

def test_unreadable_settings_are_retried_and_never_moved_aside(tmp_path, monkeypatch):
    from simtelemetry.core import settings as settings_mod
    sleeps = []
    monkeypatch.setattr(settings_mod.time, "sleep", sleeps.append)
    store = SettingsStore(tmp_path)
    store.path.mkdir()                          # reading it fails with an OSError, like a file another program locks
    message = recover_damaged_settings(store, tmp_path / "backups", NOW)
    assert message.startswith("The cafe settings file couldn't be read just now")
    assert sleeps == [settings_mod.READ_RETRY_S] * (settings_mod.READ_TRIES - 1)
    assert store.path.is_dir() and not list(tmp_path.glob("settings.json.broken-*"))


def test_settings_read_succeeds_on_a_retry(tmp_path, monkeypatch):
    from pathlib import Path
    from simtelemetry.core import settings as settings_mod
    monkeypatch.setattr(settings_mod.time, "sleep", lambda s: None)
    store = SettingsStore(tmp_path)
    store.save(_settings())
    real, calls = Path.read_text, []

    def flaky(self, *a, **k):
        calls.append(self)
        if len(calls) == 1:
            raise PermissionError("in use")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", flaky)
    assert recover_damaged_settings(store, tmp_path, NOW) is None and len(calls) == 2


# --- laps.db: only real damage moves it -------------------------------------------------------------------

def test_locked_lap_database_is_not_moved_and_stops_with_a_plain_error(tmp_path, monkeypatch):
    from simtelemetry.core import store as store_mod
    LapStore(tmp_path / "laps.db").close()

    def locked(path):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(store_mod, "LapStore", locked)
    with pytest.raises(store_mod.LapStoreUnavailable, match="in use by another program or the disk is full"):
        open_lap_store(tmp_path / "laps.db", NOW)
    assert not list(tmp_path.glob("laps.db.broken-*"))
    code = cli.main(["run", "--data-dir", str(tmp_path), *ports(), "--duration", "0.5"])
    assert code == 1
    first = (tmp_path / START_ERROR_FILE).read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("The lap database is in use by another program or the disk is full: database is locked")
    assert not list(tmp_path.glob("laps.db.broken-*"))


def test_a_quick_check_that_cannot_run_is_not_damage(tmp_path, monkeypatch):
    from simtelemetry.core import store as store_mod
    LapStore(tmp_path / "laps.db").close()

    def busy(self):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(store_mod.LapStore, "quick_check", busy)
    with pytest.raises(store_mod.LapStoreUnavailable):
        open_lap_store(tmp_path / "laps.db", NOW)
    assert not list(tmp_path.glob("laps.db.broken-*"))


def test_damaged_lap_database_that_cannot_be_moved_gives_a_plain_error(tmp_path, monkeypatch):
    from simtelemetry.core import store as store_mod
    (tmp_path / "laps.db").write_bytes(b"garbage" * 100)

    def refuse(src, dst):
        raise PermissionError("in use")
    monkeypatch.setattr(store_mod.os, "replace", refuse)
    with pytest.raises(store_mod.LapStoreUnavailable, match="damaged and could not be moved aside"):
        open_lap_store(tmp_path / "laps.db", NOW)


def test_quick_check_runs_only_after_an_unclean_shutdown(tmp_path, monkeypatch):
    from simtelemetry.core import store as store_mod
    real, checks = store_mod.LapStore.quick_check, []

    def counting(self):
        checks.append(self.path)
        return real(self)
    monkeypatch.setattr(store_mod.LapStore, "quick_check", counting)
    seen = {}

    def during():
        seen["marker"] = (tmp_path / startup.RUNNING_MARKER).exists()
    code, _ = run_hub_briefly(["run", "--data-dir", str(tmp_path), *ports()], during=during)
    assert code == 0 and checks == [] and seen["marker"]
    assert not (tmp_path / startup.RUNNING_MARKER).exists()          # a clean stop removes it
    (tmp_path / startup.RUNNING_MARKER).write_text("1234\n", encoding="utf-8")     # as left by a power cut
    code, _ = run_hub_briefly(["run", "--data-dir", str(tmp_path), *ports()])
    assert code == 0 and checks == [tmp_path / "laps.db"]
    assert not (tmp_path / startup.RUNNING_MARKER).exists()


# --- HTTP port busy: checked before any data work -------------------------------------------------------------

def test_busy_http_port_is_found_before_any_data_is_touched(tmp_path):
    (tmp_path / "settings.json").write_text("{", encoding="utf-8")
    (tmp_path / "laps.db").write_bytes(b"garbage" * 100)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("0.0.0.0", 0))
    blocker.listen()
    try:
        code = cli.main(["run", "--port", str(free_port()), "--http-port", str(blocker.getsockname()[1]),
                         "--data-dir", str(tmp_path), "--duration", "1"])
    finally:
        blocker.close()
    assert code == 2
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == "{"
    assert not list(tmp_path.glob("*.broken-*")) and not (tmp_path / startup.RUNNING_MARKER).exists()


def test_second_copy_says_it_is_already_running(tmp_path, capsys):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from simtelemetry import brand

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"product": brand.PRODUCT_NAME, "rigs": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    class Exclusive(HTTPServer):
        allow_reuse_address = False         # SO_REUSEADDR on Windows would let the hub bind the port as well
    server = Exclusive(("0.0.0.0", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        code = cli.main(["run", "--port", str(free_port()), "--http-port", str(server.server_address[1]),
                         "--data-dir", str(tmp_path), "--duration", "1"])
    finally:
        server.shutdown()
        server.server_close()
    assert code == 0
    assert f"{brand.PRODUCT_NAME} is already running." in capsys.readouterr().err
    assert not (tmp_path / START_ERROR_FILE).exists()


def test_health_says_which_product_it_is(tmp_path):
    from simtelemetry import brand
    assert make_hub(tmp_path).health_snapshot()["product"] == brand.PRODUCT_NAME


# --- admin commands and a broken hub.toml -------------------------------------------------------------------

def test_admin_commands_refuse_when_hub_toml_is_unusable(tmp_path, capsys):
    config = tmp_path / "hub.toml"
    config.write_text("[network\n", encoding="utf-8")
    for argv in (["backup"], ["setup-code"], ["restore", str(tmp_path / "x.zip")]):
        assert cli.main([*argv, "--config", str(config)]) == 2
        assert "won't run on guessed settings" in capsys.readouterr().err
    config.write_text("data_dir = 5\n", encoding="utf-8")
    assert cli.main(["setup-code", "--config", str(config)]) == 2
    config.write_text(f'data_dir = "{(tmp_path / "data").as_posix()}"\n[sounds]\nvolum = 1\n', encoding="utf-8")
    assert cli.main(["setup-code", "--config", str(config)]) == 0        # an unrelated mistake doesn't matter
    assert (tmp_path / "data").is_dir()


def test_udp_retry_logs_the_traceback_once(tmp_path, caplog):
    import asyncio
    import logging
    hub = make_hub(tmp_path)
    hub.udp_busy = "busy"

    class Listener:
        port = free_port()
        tries = 0

        async def start(self):
            Listener.tries += 1
            if Listener.tries < 4:
                raise OSError("network is down")
    caplog.set_level(logging.DEBUG, logger="simtelemetry")
    asyncio.run(cli.retry_udp(hub, Listener(), every=0))
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and errors[0].exc_info is not None
    assert len([r for r in caplog.records if "Still can't open the telemetry port" in r.getMessage()]) == 2
    assert hub.udp_busy is None


# --- upgrade from 0.4: sessions now end at closing time, so the owner is asked to check the opening hours --------

OLD_04_SETTINGS = {"name": "Lap Lab", "tagline": "", "accent": "#E10600", "logo": None, "owner_pin": "2468",
                   "staff_pin": "", "open_hour": 10, "close_hour": 24, "setup_done": True,
                   "wifi_ssid": "", "wifi_password": "", "wifi_security": "WPA"}     # as 0.4.0 saved it
HOURS_TEXT = ("Check your opening hours on the setup page — if you close after midnight, choose the next-day time.")


def test_settings_from_0_4_are_marked_and_keep_the_mark_through_rewrites(tmp_path):
    from simtelemetry.core.settings import SETTINGS_VERSION
    (tmp_path / "settings.json").write_text(json.dumps(OLD_04_SETTINGS), encoding="utf-8")
    s = SettingsStore(tmp_path).read()                       # rewrites the file with hashed PINs...
    assert s.settings_version == 0 and s.from_older_version()
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["settings_version"] == 0                      # ...without dropping the reminder
    fresh = CafeSettings(name="Lap Lab", owner_pin="2468", setup_done=True, settings_version=SETTINGS_VERSION)
    assert not fresh.from_older_version()
    assert not CafeSettings(name="Lap Lab", owner_pin="2468").from_older_version()   # not set up yet: nothing to check


def test_upgraded_settings_warn_staff_and_setup_until_the_setup_page_is_saved(tmp_path):
    from simtelemetry.core.settings import SETTINGS_VERSION, apply_settings
    (tmp_path / "settings.json").write_text(json.dumps(OLD_04_SETTINGS), encoding="utf-8")
    hub = make_hub(tmp_path)
    apply_settings(hub.config, SettingsStore(tmp_path).read())
    hub.settings_from_older_version = True                  # what `run` sets from the file
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    owner = {"X-Owner-Pin": "2468"}
    (warning,) = [w for w in client.get("/api/setup", headers=owner).json()["warnings"] if w["code"] == "check_hours"]
    assert warning["message"] == "Sessions now end automatically at closing time (midnight). " + HOURS_TEXT
    staff = client.get("/api/staff/health", headers={"X-Staff-Pin": "2468"}).json()   # owner PIN: no staff PIN yet
    assert "check_hours" in [w["code"] for w in staff["warnings"]]
    assert "check_hours" not in json.dumps(client.get("/api/setup").json())          # not for just anyone

    body = {"name": "Lap Lab", "staff_pin": "1357", "open_hour": 10, "close_hour": 22}
    r = client.post("/api/setup", json=body, headers=owner)
    assert r.status_code == 200 and "check_hours" not in [w["code"] for w in r.json()["warnings"]]
    assert SettingsStore(tmp_path).read().settings_version == SETTINGS_VERSION
    assert not SettingsStore(tmp_path).read().from_older_version()


def test_hours_warning_names_the_closing_time():
    from simtelemetry.config import AppConfig
    config = AppConfig()
    config.owner.open_hour, config.owner.close_hour = 10, 22
    from simtelemetry.hub import Hub
    fake = type("H", (), {"config": config, "settings_from_older_version": True})()
    text = Hub.hours_check_warning(fake)
    assert text == "Sessions now end automatically at closing time (22:00). " + HOURS_TEXT
    config.owner.close_hour = 2
    assert "(02:00 (next day))" in Hub.hours_check_warning(fake)
    config.features.auto_end_sessions = False
    assert Hub.hours_check_warning(fake) is None              # sessions don't end by themselves: nothing to check
    fake.settings_from_older_version = False
    config.features.auto_end_sessions = True
    assert Hub.hours_check_warning(fake) is None


def test_run_with_0_4_settings_shows_the_hours_check(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps(OLD_04_SETTINGS), encoding="utf-8")
    code, got = run_hub_briefly(["run", "--data-dir", str(data), *ports()], ["/api/setup"],
                                headers={"X-Owner-Pin": "2468"})
    assert code == 0
    assert "check_hours" in [w["code"] for w in got["/api/setup"]["warnings"]]
