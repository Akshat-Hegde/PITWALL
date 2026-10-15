"""The staff PIN is required (U3) and wrong PINs escalate to a 15-minute lock-out (K8)."""

import datetime as dt

from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.pins import LONG_LOCK_TEXT, SHORT_LOCK_TEXT, PinAttempts
from simtelemetry.core.settings import CafeSettings, SettingsStore, apply_settings

from test_drivers import make_hub
from test_setup_api import GOOD, _client


def test_setup_cannot_be_saved_without_a_staff_pin(tmp_path):
    hub, client, code = _client(tmp_path)
    r = client.post("/api/setup", json={**GOOD, "staff_pin": ""}, headers=code)
    assert r.status_code == 400 and "staff PIN" in r.json()["detail"] and "same as the owner PIN" in r.json()["detail"]
    assert client.get("/api/setup").json()["has_staff_pin"] is False
    ok = client.post("/api/setup", json={**GOOD, "staff_pin": "2468"}, headers=code)   # may equal the owner PIN
    assert ok.status_code == 200 and ok.json()["has_staff_pin"] is True
    assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "2468"}).status_code == 200


def test_an_install_without_a_staff_pin_opens_the_staff_page_with_the_owner_pin(tmp_path):
    store = SettingsStore(tmp_path)                       # saved by an older version: no staff PIN
    store.save(CafeSettings(name="Lap Lab", owner_pin="2468", staff_pin="", setup_done=True))
    hub = make_hub(tmp_path)
    apply_settings(hub.config, store.read())
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    assert client.get("/api/staff/rigs").status_code == 401
    assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "1111"}).status_code == 401
    r = client.get("/api/staff/rigs", headers={"X-Staff-Pin": "2468"})
    assert r.status_code == 200 and r.json()["staff_pin_missing"] is True      # the page shows the red banner
    # Saving the setup page asks for one; once set, the owner PIN no longer opens the staff page.
    assert client.post("/api/setup", json={**GOOD, "owner_pin": "", "staff_pin": ""},
                       headers={"X-Owner-Pin": "2468"}).status_code == 400
    assert client.post("/api/setup", json={**GOOD, "owner_pin": "", "staff_pin": "1357"},
                       headers={"X-Owner-Pin": "2468"}).status_code == 200
    assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "2468"}).status_code == 401
    r = client.get("/api/staff/rigs", headers={"X-Staff-Pin": "1357"})
    assert r.status_code == 200 and r.json()["staff_pin_missing"] is False


def test_a_hub_with_no_pin_at_all_never_serves_staff_data(tmp_path):
    # Settings damaged with no backup (setup mode) and no PIN in hub.toml: nothing is open.
    hub = make_hub(tmp_path)
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    for path in ("/api/staff/rigs", "/api/staff/health", "/api/staff/drivers?q=al", "/api/staff/tv"):
        r = client.get(path, headers={"X-Staff-Pin": ""})
        assert r.status_code == 403 and r.json()["detail"].startswith("Finish setup first"), path
    assert client.put("/api/staff/rigs/10.0.0.1/driver", json={"name": "Al"}).status_code == 403
    assert client.get("/api/owner/report").status_code == 403
    assert client.get("/staff").status_code == 200        # the page itself loads and says what to do


def test_three_lockouts_in_an_hour_lock_the_address_for_15_minutes():
    now = {"t": 1000.0}
    wall = dt.datetime(2026, 10, 15, 21, 40).timestamp()
    attempts = PinAttempts(clock=lambda: now["t"], wall=lambda: wall)
    for lockout in range(3):
        assert attempts.locked("10.0.0.5") is None
        for _ in range(5):
            attempts.failed("10.0.0.5")
            now["t"] += 1
        expected = LONG_LOCK_TEXT if lockout == 2 else SHORT_LOCK_TEXT
        assert attempts.locked("10.0.0.5") == expected
        assert attempts.locked("10.0.0.6") is None             # only that address
        now["t"] += 61                                         # a short lock-out is over after a minute
    assert attempts.locked("10.0.0.5") == LONG_LOCK_TEXT       # the long one isn't
    now["t"] += 15 * 60
    assert attempts.locked("10.0.0.5") is None
    (alert,) = attempts.alerts
    assert alert["text"] == "Someone tried wrong PINs 15 times at 21:40" and alert["wrong"] == 15


def test_lockouts_more_than_an_hour_apart_stay_short():
    now = {"t": 0.0}
    attempts = PinAttempts(clock=lambda: now["t"])
    for _ in range(3):
        for _ in range(5):
            attempts.failed("10.0.0.5")
        assert attempts.locked("10.0.0.5") == SHORT_LOCK_TEXT
        now["t"] += 1900                                       # 32 minutes later
    assert not attempts.alerts


def test_wrong_pins_across_pages_lock_out_and_reach_the_owner_page(tmp_path):
    hub, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers=code)
    now = {"t": 0.0}
    hub.pin_attempts._clock = lambda: now["t"]
    for _ in range(3):
        for _ in range(5):
            assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "0000"}).status_code == 401
        r = client.get("/api/owner/report", headers={"X-Owner-Pin": "2468"})   # same address, any page
        assert r.status_code == 429
        now["t"] += 61
    r = client.get("/api/staff/rigs", headers={"X-Staff-Pin": "1357"})
    assert r.status_code == 429 and "15 minutes" in r.json()["detail"]
    now["t"] += 15 * 60
    report = client.get("/api/owner/report", headers={"X-Owner-Pin": "2468"}).json()
    assert len(report["pin_alerts"]) == 1 and report["pin_alerts"][0].startswith("Someone tried wrong PINs 15 times at ")


# --- same name today (K8) ------------------------------------------------------------------------------

async def test_same_name_check_finds_a_driver_on_another_rig_or_todays_board(tmp_path):
    import time

    from test_drivers import RIG, client_with_rig
    hub, client = await client_with_rig(tmp_path)
    other = "192.168.1.22"
    hub.registry.see(other, time.monotonic(), "2025", None)

    def check(name, rig=RIG):
        r = client.get("/api/staff/names/check", params={"name": name, "rig_id": rig})
        assert r.status_code == 200, r.text
        return r.json()

    assert check("Alex") == {"name": "Alex", "in_use": False, "where": None}
    client.put(f"/api/staff/rigs/{other}/driver", json={"name": "Alex"})
    assert check("  alex ") == {"name": "alex", "in_use": True, "where": "driving on Rig 2"}
    assert check("Alex", rig=other)["in_use"] is False          # its own rig doesn't count
    client.delete(f"/api/staff/rigs/{other}/driver")
    assert check("Alex")["in_use"] is False
    # A lap today under the walk-in name: same line on the board.
    now_ms = round(time.time() * 1000)
    with hub.drivers.store._lock, hub.drivers.store._db as db:
        db.execute("INSERT INTO laps (rig_id, rig_name, driver, driver_key, track_key, lap_number, lap_ms, valid, "
                   "out_lap, completed_at) VALUES (?, 'Rig 2', 'Sam', 'driver:sam', 'F1:7', 2, 90000, 1, 0, ?)",
                   (other, now_ms))
    assert check("SAM") == {"name": "SAM", "in_use": True, "where": "on today's board"}
    assert client.get("/api/staff/names/check", params={"name": ""}).status_code == 400


async def test_wifi_qr_for_the_card_panel(tmp_path):
    from test_drivers import client_with_rig
    hub, client = await client_with_rig(tmp_path)
    assert client.get("/api/staff/wifi").json() == {"wifi": None}
    hub.config.cafe.wifi_ssid, hub.config.cafe.wifi_password = "Lap Lab Guests", "fastlaps1"
    wifi = client.get("/api/staff/wifi").json()["wifi"]
    assert wifi["ssid"] == "Lap Lab Guests" and wifi["svg"].startswith("<svg") and "fastlaps1" not in wifi["svg"]


def test_staff_and_owner_pages_ask_before_destructive_actions_and_speak_plainly():
    from pathlib import Path
    api = Path(__file__).parents[1] / "simtelemetry" / "api"
    staff = (api / "staff.html").read_text(encoding="utf-8")
    owner = (api / "owner.html").read_text(encoding="utf-8")
    assert "Their card will be made now." in staff and "rig__end-row" in staff        # confirm, apart from +time
    assert "from the queue?" in staff and "Remove ${m.name} from ${t.name}?" in staff
    assert "Same person" in staff and "Add a letter" in staff and "Their laps will be on one line." in staff
    assert "Set a staff PIN on the setup page" in staff and "Join the Wi-Fi first" in staff
    assert '["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)' in staff            # buttons don't block redraws
    for page in (staff, owner, (api / "setup.html").read_text(encoding="utf-8"),
                 (api / "checkin_print.html").read_text(encoding="utf-8")):
        assert "The hub answered" not in page and "Failed to fetch" not in page and "[features]" not in page
    assert "pin_alerts" in owner


def test_slow_guessing_locks_the_address_for_15_minutes(caplog):
    # One wrong PIN every 2 minutes never trips the one-minute limit, but 20 within an hour do.
    now = {"t": 0.0}
    wall = dt.datetime(2026, 10, 15, 22, 5).timestamp()
    attempts = PinAttempts(clock=lambda: now["t"], wall=lambda: wall)
    with caplog.at_level("WARNING"):
        for i in range(20):
            assert attempts.locked("10.0.0.5") is None, i
            attempts.failed("10.0.0.5")
            now["t"] += 120
    assert attempts.locked("10.0.0.5") == LONG_LOCK_TEXT
    (alert,) = attempts.alert_list()
    assert alert["wrong"] == 20 and alert["text"] == "Someone tried wrong PINs 20 times at 22:05"
    assert "locked out for 15 minutes" in caplog.text
    now["t"] += 15 * 60
    assert attempts.locked("10.0.0.5") is None
    attempts.failed("10.0.0.5")                     # counted afresh after the alert: not locked again at once
    assert attempts.locked("10.0.0.5") is None


def test_alert_list_is_a_copy():
    attempts = PinAttempts()
    attempts.alerts.append({"at": 0, "wrong": 15, "text": "x"})
    copy = attempts.alert_list()
    attempts.alerts.append({"at": 1, "wrong": 15, "text": "y"})
    assert [a["text"] for a in copy] == ["x"]


def test_pages_drop_stale_questions_and_never_offer_a_closing_time_the_hub_refuses():
    from pathlib import Path
    api = Path(__file__).parents[1] / "simtelemetry" / "api"
    staff = (api / "staff.html").read_text(encoding="utf-8")
    setup = (api / "setup.html").read_text(encoding="utf-8")
    assert "seenSession[rig.rig_id] !== sessionKey" in staff and "delete drafts[rig.rig_id];" in staff
    assert "Math.min(6, open - 1)" in setup                                    # next-day close stops before opening
    assert "(24 hours) isn't supported yet" in setup
