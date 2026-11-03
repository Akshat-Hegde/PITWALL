"""First-run setup page and API; branding upload; owner PIN once set up."""

from __future__ import annotations

from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.setup_code import SetupCode
from simtelemetry.core.pins import verify_pin

from test_drivers import make_hub

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82")
GOOD = {"name": "Lap Lab", "tagline": "Beat the board", "accent": "#FF2A6D", "owner_pin": "2468",
        "staff_pin": "1357", "open_hour": 10, "close_hour": 22}


def _client(tmp_path):
    code = SetupCode(tmp_path).new()                      # what the installer does
    hub = make_hub(tmp_path)
    return hub, TestClient(create_app(hub, dashboard_dir=tmp_path / "none")), {"X-Setup-Code": code}


def test_first_run_needs_the_setup_code_then_the_pin(tmp_path):
    hub, client, code = _client(tmp_path)
    assert "Set up" in client.get("/setup").text
    state = client.get("/api/setup").json()
    assert state["setup_done"] is False and state["needs_code"] is True and "hub_address" in state
    r = client.post("/api/setup", json=GOOD)                          # someone else on the LAN, no code
    assert r.status_code == 401 and "setup code" in r.json()["detail"]
    assert client.post("/api/setup", json=GOOD, headers={"X-Setup-Code": "AAAA-AAAA"}).status_code == 401
    r = client.post("/api/setup", json=GOOD, headers=code)
    assert r.status_code == 200
    assert hub.config.cafe.name == "Lap Lab" and verify_pin("2468", hub.config.owner.pin)
    assert SetupCode(tmp_path).current() is None                     # used up
    assert client.post("/api/setup", json={**GOOD, "name": "Other"}, headers=code).status_code == 401
    ok = client.post("/api/setup", json={**GOOD, "name": "Lap Lab 2"}, headers={"X-Owner-Pin": "2468"})
    assert ok.status_code == 200 and hub.config.cafe.name == "Lap Lab 2"


def test_setup_code_never_in_api_responses(tmp_path):
    _, client, code = _client(tmp_path)
    secret = code["X-Setup-Code"]
    assert secret not in client.get("/api/setup").text and secret not in client.get("/setup").text


def test_too_many_wrong_codes_locks(tmp_path):
    _, client, _ = _client(tmp_path)
    for _ in range(10):
        client.post("/api/setup", json=GOOD, headers={"X-Setup-Code": "AAAA-AAAA"})
    assert client.post("/api/setup", json=GOOD, headers={"X-Setup-Code": "AAAA-AAAA"}).status_code == 429


def test_owner_pin_after_setup_is_rate_limited(tmp_path):
    _, client, code = _client(tmp_path)
    assert client.post("/api/setup", json=GOOD, headers=code).status_code == 200
    for _ in range(5):
        assert client.post("/api/setup", json=GOOD, headers={"X-Owner-Pin": "0000"}).status_code == 401
    assert client.post("/api/setup", json=GOOD, headers={"X-Owner-Pin": "0000"}).status_code == 429
    assert client.post("/api/setup", json=GOOD, headers={"X-Owner-Pin": "2468"}).status_code == 429


def test_bad_values_are_400(tmp_path):
    _, client, code = _client(tmp_path)
    r = client.post("/api/setup", json={**GOOD, "accent": "pink"}, headers=code)
    assert r.status_code == 400 and "accent" in r.json()["detail"]


def test_pins_set_in_setup_apply_without_restart(tmp_path):
    hub, client, code = _client(tmp_path)
    assert client.get("/api/staff/rigs").status_code == 403             # no PIN at all: never served open
    assert client.get("/api/owner/report").status_code == 403           # owner page locked until a PIN is set
    r = client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code)
    assert r.status_code == 200
    assert client.get("/api/staff/rigs").status_code == 401
    assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "1357"}).status_code == 200
    assert client.get("/api/owner/report").status_code == 401
    assert client.get("/api/owner/report", headers={"X-Owner-Pin": "2468"}).status_code == 200


def test_logo_upload_and_serve(tmp_path):
    hub, client, code = _client(tmp_path)
    assert client.post("/api/setup/logo", files={"file": ("logo.png", PNG, "image/png")}).status_code == 401
    r = client.post("/api/setup/logo", files={"file": ("logo.png", PNG, "image/png")}, headers=code)
    assert r.status_code == 200 and hub.config.cafe.logo == r.json()["logo"]
    got = client.get("/api/cafe/logo")
    assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
    bad = client.post("/api/setup/logo", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=code)
    assert bad.status_code == 400
    big = PNG + b"\0" * (1024 * 1024)
    assert client.post("/api/setup/logo", files={"file": ("big.png", big, "image/png")}, headers=code).status_code == 400


def test_second_logo_changes_name_and_sends_cafe_message(tmp_path):
    from simtelemetry.core.feed import FeedBuilder, FeedConnection
    hub, client, code = _client(tmp_path)
    conn = FeedConnection(FeedBuilder(hub))
    conn.start(0.0)
    client.post("/api/setup/logo", files={"file": ("a.png", PNG, "image/png")}, headers=code)
    (first,) = [m for m in conn.tick(0.0) if m["type"] == "cafe"]
    PNG2 = PNG + b"-second"
    r = client.post("/api/setup/logo", files={"file": ("b.png", PNG2, "image/png")}, headers=code)
    assert r.json()["logo"] == hub.config.cafe.logo and hub.config.cafe.logo != first["cafe"]["logo"].split("v=")[1]
    (second,) = [m for m in conn.tick(0.0) if m["type"] == "cafe"]
    assert second["cafe"]["logo"] != first["cafe"]["logo"]
    assert client.get("/api/cafe/logo").content == PNG2
    assert len(list((tmp_path / "branding").glob("logo*"))) == 1


def test_setup_code_command_and_settings_layering(tmp_path, capsys):
    from simtelemetry.__main__ import apply_saved_settings, build_parser, main
    from simtelemetry.config import AppConfig
    from simtelemetry.core.settings import CafeSettings, SettingsStore
    assert main(["setup-code", "--new", "--data-dir", str(tmp_path)]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == SetupCode(tmp_path).current()
    assert main(["setup-code", "--data-dir", str(tmp_path)]) == 0 and capsys.readouterr().out.strip() == printed
    SettingsStore(tmp_path).save(CafeSettings(name="Lap Lab", owner_pin="2468", setup_done=True))
    assert main(["setup-code", "--data-dir", str(tmp_path)]) == 0
    assert "Setup is done" in capsys.readouterr().out
    # a --owner-pin flag still wins over settings.json
    args = build_parser().parse_args(["run", "--owner-pin", "9999", "--data-dir", str(tmp_path)])
    config = AppConfig(data_dir=tmp_path)
    assert apply_saved_settings(config, args) is True
    assert config.cafe.name == "Lap Lab" and config.owner.pin == "9999"


def test_opening_hours_from_setup_reach_the_owner_report(tmp_path):
    _, client, code = _client(tmp_path)
    assert client.post("/api/setup", json=GOOD, headers=code).status_code == 200
    pin = {"X-Owner-Pin": "2468"}
    assert client.get("/api/owner/report", headers=pin).json()["open_hours"] == [10, 22]
    r = client.post("/api/setup", json={**GOOD, "open_hour": 12, "close_hour": 20}, headers=pin)
    assert r.status_code == 200
    assert client.get("/api/owner/report", headers=pin).json()["open_hours"] == [12, 20]


def test_blank_pins_keep_old_ones_after_setup_code_reset(tmp_path):
    import argparse
    from simtelemetry.__main__ import setup_code_command
    hub, client, code = _client(tmp_path)
    assert client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code).status_code == 200
    # what `<exe> setup-code --reset` does
    assert setup_code_command(argparse.Namespace(reset=True, new=False), hub.config) == 0
    new_code = SetupCode(tmp_path).current()
    state = client.get("/api/setup").json()
    assert state["setup_done"] is False and state["has_settings"] is True
    assert "1357" not in client.get("/api/setup").text and "2468" not in client.get("/api/setup").text
    r = client.post("/api/setup", json={**GOOD, "owner_pin": "", "staff_pin": ""}, headers={"X-Setup-Code": new_code})
    assert r.status_code == 200
    assert client.get("/api/staff/rigs").status_code == 401                     # staff PIN kept
    assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "1357"}).status_code == 200
    assert client.get("/api/owner/report", headers={"X-Owner-Pin": "2468"}).status_code == 200


def test_fresh_first_setup_still_requires_owner_pin(tmp_path):
    _, client, code = _client(tmp_path)
    assert client.post("/api/setup", json={**GOOD, "owner_pin": ""}, headers=code).status_code == 400
    assert client.get("/api/setup").json()["has_settings"] is False


def test_accent_swatches_match_the_setup_page():
    """The factory offers settings.ACCENT_SWATCHES; they must be the swatches setup.html shows."""
    import json
    import re
    from simtelemetry.api.setup import SETUP_PAGE
    from simtelemetry.core.settings import ACCENT_SWATCHES
    m = re.search(r"const SWATCHES = (\[[^\]]*\]);", SETUP_PAGE.read_text(encoding="utf-8"))
    assert m and tuple(json.loads(m.group(1))) == ACCENT_SWATCHES
