"""K4-K6: the hub's address (fallback, change warning, "OK, done"), the rig editor on the setup page (rename,
forget, "same rig as…"), registration on the first valid packet, wrong-format senders and silent-rig warnings."""

from __future__ import annotations

import datetime as dt
import json
import struct
import time

import pytest
from fastapi.testclient import TestClient

from simtelemetry import licence, rig_setup
from simtelemetry.api.app import create_app
from simtelemetry.config import NetworkConfig
from simtelemetry.core import feed as feed_mod
from simtelemetry.core.address import AddressWatch
from simtelemetry.core.health import SilentRigWatch, opened_at
from simtelemetry.core.setup_code import SetupCode

from test_drivers import make_hub
from test_feed import driving_rig, motion
from test_setup_api import GOOD

OLD, NEW = "192.168.1.31", "192.168.1.32"


async def feed_from(hub, packets):
    import asyncio
    consumer = asyncio.create_task(hub.consume())
    for ip, data in packets:
        hub.on_datagram(data, ip, 0.0)
    await hub.drain()
    consumer.cancel()


def set_up(tmp_path):
    """A hub after first-run setup, its client and the owner PIN header."""
    code = SetupCode(tmp_path).new()
    hub = make_hub(tmp_path)
    hub.hub_address = lambda: "192.168.1.10"
    hub.address_watch.current = lambda: "192.168.1.10"
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    assert client.post("/api/setup", json={**GOOD, "staff_pin": "1357"}, headers={"X-Setup-Code": code}).status_code == 200
    return hub, client, {"X-Owner-Pin": "2468"}


def silence(hub, ip):
    """Make the rig look silent (no data) without waiting."""
    h = hub.health.get(ip)
    h.last_seen -= 60
    h.last_accepted = h.last_seen


# --- K4: the hub's address ----------------------------------------------------------------------

def test_lan_address_uses_the_default_route(monkeypatch):
    monkeypatch.setattr(feed_mod, "_default_route_address", lambda: "192.168.1.10")
    monkeypatch.setattr(feed_mod, "_private_addresses", lambda: ["10.0.0.4"])
    assert feed_mod.lan_address(["10.0.0.20"]) == "192.168.1.10"


@pytest.mark.parametrize("route", [None, "127.0.0.1", "0.0.0.0"])
def test_lan_address_falls_back_to_the_rigs_network_then_the_first_private(monkeypatch, route):
    monkeypatch.setattr(feed_mod, "_default_route_address", lambda: route)
    monkeypatch.setattr(feed_mod, "_private_addresses", lambda: ["172.16.5.2", "192.168.50.7"])
    assert feed_mod.lan_address(["127.0.0.1", "192.168.50.21"]) == "192.168.50.7"   # where rig packets come from
    assert feed_mod.lan_address([]) == "172.16.5.2"
    monkeypatch.setattr(feed_mod, "_private_addresses", lambda: [])
    assert feed_mod.lan_address(["192.168.50.21"]) is None


def test_address_watch_warns_on_change_until_acknowledged(tmp_path):
    current = {"address": "192.168.1.10"}
    path = tmp_path / "hub-address.json"
    watch = AddressWatch(path, lambda: current["address"])
    assert watch.warning() is None                                   # first address: stored quietly
    assert json.loads(path.read_text())["address"] == "192.168.1.10"
    current["address"] = "192.168.1.44"
    w = AddressWatch(path, lambda: current["address"]).warning()     # also after a restart
    assert w["code"] == "address_changed"
    assert w["message"] == ("This PC's network address changed from 192.168.1.10 to 192.168.1.44. On every rig set "
                            "UDP IP Address to 192.168.1.44, and reprint the check-in stickers. To stop this "
                            "happening, reserve the address in your router (see the setup guide).")
    current["address"] = None
    assert watch.warning() is None                                   # no network: nothing to compare
    current["address"] = "192.168.1.44"
    assert watch.acknowledge() == "192.168.1.44"
    assert watch.warning() is None
    assert AddressWatch(path, lambda: "192.168.1.44").warning() is None


def test_address_change_shows_on_setup_and_staff_and_ok_done_clears_it(tmp_path):
    hub, client, owner = set_up(tmp_path)
    assert client.get("/api/setup", headers=owner).json()["warnings"] == []
    hub.address_watch.current = lambda: "192.168.1.44"
    codes = [w["code"] for w in client.get("/api/setup", headers=owner).json()["warnings"]]
    assert codes == ["address_changed"]
    anon = client.get("/api/setup").json()                   # without the owner PIN: only that there is one
    assert anon["warnings"] == [] and anon["hidden_warnings"] == 1 and "192.168.1.44" not in json.dumps(anon)
    staff = {"X-Staff-Pin": "1357"}
    health = client.get("/api/staff/health", headers=staff).json()
    assert [w["code"] for w in health["warnings"]].count("address_changed") == 1
    assert client.post("/api/setup/address/ok").status_code == 401          # owner PIN needed
    r = client.post("/api/setup/address/ok", headers=owner)
    assert r.status_code == 200 and r.json()["warnings"] == []
    hub.address_watch.current = lambda: "192.168.1.45"                       # and again, acknowledged by staff
    assert client.post("/api/staff/address/ok").status_code == 401
    assert client.post("/api/staff/address/ok", headers=staff).json() == {"address": "192.168.1.45"}
    assert "address_changed" not in [w["code"] for w in client.get("/api/staff/health", headers=staff).json()["warnings"]]


async def test_the_tv_feed_never_carries_the_address_warning(tmp_path):
    hub, client, _ = set_up(tmp_path)
    hub.address_watch.current = lambda: "192.168.1.44"
    status = feed_mod.FeedBuilder(hub).status(time.monotonic())
    assert all(w["code"] != "address_changed" for w in status["warnings"])


# --- K5: registration ---------------------------------------------------------------------------

async def test_only_a_valid_packet_makes_a_rig(tmp_path):
    hub = make_hub(tmp_path)
    wrong = bytearray(motion(2025, 0x11, 0, 0))
    struct.pack_into("<H", wrong, 0, 2023)
    await feed_from(hub, [(OLD, bytes(wrong)), (OLD, b"garbage"), ("192.168.1.77", bytes(motion(2025, 0x11, 0, 0))[:-2])])
    assert hub.registry.all() == []
    lines = hub.wrong_sender_warnings()
    assert [w["message"] for w in lines] == [
        "A PC at 192.168.1.31 is sending telemetry in the wrong format: set UDP Format to 2025.",
        "A PC at 192.168.1.77 is sending telemetry in the wrong format: set UDP Format to 2025."]
    assert hub.wrong_sender_warnings(time.monotonic() + 61) == []          # gone a minute after it stops
    await feed_from(hub, [(OLD, motion(2025, 0x11, 0, 0))])
    assert [r.ip for r in hub.registry.all()] == [OLD]
    assert [w["message"] for w in hub.wrong_sender_warnings()] == [
        "A PC at 192.168.1.77 is sending telemetry in the wrong format: set UDP Format to 2025."]
    assert not (tmp_path / "rigs.json").exists() or "192.168.1.77" not in (tmp_path / "rigs.json").read_text()


async def test_wrong_format_senders_are_on_staff_health_never_the_tv(tmp_path):
    hub, client, _ = set_up(tmp_path)
    hub.on_datagram(b"\x00" * 40, OLD, 0.0)
    health = client.get("/api/staff/health", headers={"X-Staff-Pin": "1357"}).json()
    assert [w["code"] for w in health["warnings"]] == ["wrong_format_sender"]
    assert health["rigs"] == []
    assert "wrong_format_sender" in [w["code"] for w in client.get("/api/setup").json()["warnings"]]
    snapshot = feed_mod.FeedConnection(feed_mod.FeedBuilder(hub)).start(time.monotonic())
    assert OLD not in json.dumps(snapshot)


async def test_a_known_rig_in_the_wrong_format_says_wrong_game_settings(tmp_path):
    hub, client, _ = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD))
    wrong = bytearray(motion(2025, 0x11, 0, 0))
    struct.pack_into("<H", wrong, 0, 2024)
    h = hub.health.get(OLD)
    h.last_seen = h.last_accepted = h.last_driving = time.monotonic() - 6     # its good packets are old
    hub.on_datagram(bytes(wrong), OLD, 0.0)
    assert hub.state_text(OLD, time.monotonic()) == "Wrong game settings"
    (row,) = client.get("/api/staff/rigs", headers={"X-Staff-Pin": "1357"}).json()["rigs"]
    assert row["state_text"] == "Wrong game settings"
    (rig,) = client.get("/api/staff/health", headers={"X-Staff-Pin": "1357"}).json()["rigs"]
    assert rig["state_text"] == "Wrong game settings"
    await feed_from(hub, driving_rig(OLD))
    assert hub.state_text(OLD, time.monotonic()) == "On track"


# --- K5: the rig editor -------------------------------------------------------------------------

async def test_rename_on_the_setup_page_needs_the_owner_pin_and_reaches_the_tv(tmp_path):
    hub, client, owner = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD))
    assert client.put(f"/api/setup/rigs/{OLD}", json={"name": "Window"}).status_code == 401
    r = client.put(f"/api/setup/rigs/{OLD}", json={"name": "Window"}, headers=owner)
    assert r.status_code == 200 and r.json()["rigs"][0]["name"] == "Window"
    bad = client.put(f"/api/setup/rigs/{OLD}", json={"name": "A much too long rig name"}, headers=owner)
    assert bad.status_code == 400 and bad.json()["detail"] == "A rig name can be at most 16 characters."
    info = feed_mod.FeedBuilder(hub).rig_infos()[0]
    assert info["name"] == "Window"


async def test_forget_removes_the_rig_and_its_checkin_code(tmp_path):
    hub, client, owner = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD) + driving_rig(NEW))
    assert set(hub.checkin.codes()) == {OLD, NEW}
    r = client.delete(f"/api/setup/rigs/{OLD}", headers=owner)
    assert r.status_code == 400 and "sending data right now" in r.json()["detail"]
    silence(hub, OLD)
    hub.drivers.assign(OLD, "Maya")
    r = client.delete(f"/api/setup/rigs/{OLD}", headers=owner)
    assert r.status_code == 400 and "session running" in r.json()["detail"]
    hub.drivers.end(OLD)
    hub.tv.set(pinned_rig=OLD)
    r = client.delete(f"/api/setup/rigs/{OLD}", headers=owner)
    assert r.status_code == 200 and [x["rig_id"] for x in r.json()["rigs"]] == [NEW]
    assert OLD not in json.loads((tmp_path / "checkin.json").read_text())
    assert OLD not in json.loads((tmp_path / "rigs.json").read_text())["auto_names"]
    assert hub.tv.pinned_rig is None


async def test_same_rig_as_moves_name_colour_number_code_and_session(tmp_path):
    hub, client, owner = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD))
    client.put(f"/api/setup/rigs/{OLD}", json={"name": "Window"}, headers=owner)
    old_code = hub.checkin.codes()[OLD]
    session = hub.drivers.assign(OLD, "Maya", minutes=30)
    secret = hub.checkin.register(OLD, session)
    hub.tv.set(pinned_rig=OLD)
    old_colour = feed_mod.rig_colour(hub.registry.get(OLD))
    # The window rig's PC comes back with a new address: a new rig appears.
    silence(hub, OLD)
    await feed_from(hub, driving_rig(NEW))
    assert hub.registry.get(NEW).name == "Rig 2"
    r = client.post(f"/api/setup/rigs/{NEW}/same-as", json={"old": OLD}, headers=owner)
    assert r.status_code == 200
    (row,) = r.json()["rigs"]
    assert (row["rig_id"], row["name"], row["number"], row["colour"]) == (NEW, "Window", "Rig 1", old_colour)
    assert hub.checkin.codes() == {NEW: old_code}                     # the sticker on the rig keeps working
    assert hub.checkin.rig_for(old_code) == NEW
    assert hub.drivers.get(OLD) is None and hub.drivers.get(NEW) == session
    assert hub.drivers.store.current_driver_sessions() == {NEW: session}
    assert hub.checkin.lookup(NEW, secret) is not None                 # the guest's phone still finds the session
    assert hub.tv.pinned_rig == NEW
    assert json.loads((tmp_path / "rigs.json").read_text())["auto_names"] == {NEW: "Rig 1"}
    assert json.loads((tmp_path / "checkin.json").read_text()) == {NEW: old_code}


def lap_on(hub, rig_id, n, lap_ms, driver):
    from simtelemetry.core.laps import LapCompleted, LapContext, LiveLap
    ctx = LapContext(rig_name="Rig 1", driver=driver, track_key="F1:7", track_name="Silverstone", session_id="s",
                     position=(0.0, 0.0), track_length_m=4800.0, driver_id=hub.drivers.driver_id(rig_id))
    hub.laps.update(rig_id, ctx, LiveLap(n + 1, 5.0, 100, True, 0, None, None, lap_ms), [
        LapCompleted(n, 0.0, lap_ms, (30000, 33000, lap_ms - 63000), True, False, "test")])


async def test_same_rig_as_mid_session_keeps_the_laps_before_and_after(tmp_path):
    hub, client, owner = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD))
    session = hub.drivers.assign(OLD, "Maya", minutes=30)
    secret = hub.checkin.register(OLD, session)
    lap_on(hub, OLD, 2, 96000, "Maya")
    silence(hub, OLD)
    await feed_from(hub, driving_rig(NEW))
    assert client.post(f"/api/setup/rigs/{NEW}/same-as", json={"old": OLD}, headers=owner).status_code == 200
    lap_on(hub, NEW, 3, 95000, "Maya")
    rec = hub.checkin.lookup(NEW, secret)
    assert [r.lap_number for r in hub.checkin.laps(rec)] == [2, 3]
    rows = hub.laps.store._db.execute("SELECT rig_id FROM laps ORDER BY id").fetchall()
    assert [r["rig_id"] for r in rows] == [NEW, NEW]
    card = hub.end_session(NEW)
    assert card["laps"] == 2 and card["best_ms"] == 95000


async def test_same_rig_as_moves_a_nameless_rigs_lap_key(tmp_path):
    hub, client, owner = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD))
    early = hub.laps.store._db.execute("SELECT COUNT(*) FROM laps").fetchone()[0]
    lap_on(hub, OLD, 1, 97000, None)                                  # before the session: stays on OLD
    hub.laps.laps[-1].completed_at -= 10_000
    hub.laps.store._db.execute("UPDATE laps SET completed_at = completed_at - 10000")
    session = hub.drivers.assign(OLD, "Maya")
    lap_on(hub, OLD, 2, 96000, None)
    silence(hub, OLD)
    await feed_from(hub, driving_rig(NEW))
    hub.merge_rig(OLD, NEW)
    assert [(r.rig_id, r.driver_key) for r in hub.laps.laps] == [(OLD, f"rig:{OLD}"), (NEW, f"rig:{NEW}")]
    rows = hub.laps.store._db.execute("SELECT rig_id, driver_key FROM laps ORDER BY id").fetchall()
    assert [tuple(r) for r in rows][early:] == [(OLD, f"rig:{OLD}"), (NEW, f"rig:{NEW}")]
    assert session.started_at <= hub.laps.laps[-1].completed_at


async def test_same_rig_as_is_refused_when_the_old_rig_still_sends_or_both_have_sessions(tmp_path):
    hub, client, owner = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD) + driving_rig(NEW))
    r = client.post(f"/api/setup/rigs/{NEW}/same-as", json={"old": OLD}, headers=owner)
    assert r.status_code == 400 and r.json()["detail"] == "Rig 1 is still sending data, so it is a different PC."
    silence(hub, OLD)
    hub.drivers.assign(OLD, "Maya")
    hub.drivers.assign(NEW, "Sam")
    r = client.post(f"/api/setup/rigs/{NEW}/same-as", json={"old": OLD}, headers=owner)
    assert r.status_code == 400 and "Both rigs have a session" in r.json()["detail"]
    assert {x.ip for x in hub.registry.all()} == {OLD, NEW}


async def test_identify_marks_the_rig_whose_car_is_moving(tmp_path):
    hub, client, owner = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD) + driving_rig(NEW))
    silence(hub, NEW)
    rigs = {r["rig_id"]: r for r in client.get("/api/setup/rigs", headers=owner).json()["rigs"]}
    assert rigs[OLD]["moving"] is True and rigs[NEW]["moving"] is False
    assert rigs[OLD]["state_text"] == "On track" and rigs[NEW]["state_text"] == "No data"


def test_setup_and_staff_pages_carry_the_game_settings_word_for_word(tmp_path):
    hub, client, _ = set_up(tmp_path)
    u1 = ("Game Options › Settings › UDP Telemetry Settings: UDP Telemetry On, UDP Broadcast Mode Off, "
          "UDP IP Address = ")
    for page in ("/setup", "/staff"):
        text = " ".join(client.get(page).text.split())
        assert "{{" not in text, page
        assert "On every rig, in F1 25: " + u1 in text, page
        assert "UDP Send Rate 20Hz, UDP Format 2025. Your Telemetry may stay Restricted." in text, page
        assert "not 127.0.0.1" in text, page
        # one source (rig_setup.py) for the pages and the factory's printed guide
        assert rig_setup.BEFORE_ADDRESS == u1 and rig_setup.BEFORE_ADDRESS in text, page
        assert '</strong>' + rig_setup.BEFORE_PORT + '<strong id=' in text, page
        assert '</strong>' + rig_setup.AFTER_PORT in text, page


def test_rig_setup_sentence_is_u1_word_for_word():
    assert rig_setup.sentence() == (
        "Game Options › Settings › UDP Telemetry Settings: UDP Telemetry On, UDP Broadcast Mode Off, "
        "UDP IP Address = the hub PC's address, UDP Port 20777, UDP Send Rate 20Hz, UDP Format 2025.")
    assert rig_setup.sentence("192.168.1.10", 20778).endswith("= 192.168.1.10, UDP Port 20778, UDP Send Rate 20Hz, "
                                                              "UDP Format 2025.")
    assert rig_setup.PORT == NetworkConfig.model_fields["udp_port"].default
    assert rig_setup.GAME == licence.game_name("f1_25")


# --- K6: silent rigs ----------------------------------------------------------------------------

def at(hour, minute=0, day=15):
    return dt.datetime(2026, 10, day, hour, minute)


def test_opening_hours_including_after_midnight():
    assert opened_at(at(9, 59), 10, 22) is None
    assert opened_at(at(10), 10, 22) == at(10)
    assert opened_at(at(22), 10, 22) is None
    assert opened_at(at(23), 18, 2) == at(18)
    assert opened_at(at(1, 30, day=16), 18, 2) == at(18)               # still the 15th's business day
    assert opened_at(at(3, day=16), 18, 2) is None


def test_silent_rig_warning_only_when_open_after_10_minutes_once_a_day():
    watch = SilentRigWatch()
    assert watch.check("r", 3600, at(9), 10, 22) is False               # closed
    assert watch.check("r", 3600, at(10, 5), 10, 22) is False           # silent all night, but open 5 minutes
    assert watch.check("r", 3600, at(10, 11), 10, 22) is True
    assert watch.check("r", 3700, at(10, 12), 10, 22) is True           # stays while still silent
    assert watch.check("r", None, at(10, 13), 10, 22) is False          # it sends again
    assert watch.check("r", 900, at(15), 10, 22) is False               # silent again the same day: no second warning
    assert watch.check("r", 900, at(15, day=16), 10, 22) is True        # the next day
    assert watch.check("other", 300, at(15, day=16), 10, 22) is False   # 5 minutes is not silent yet


async def test_silent_rig_checklist_on_staff_health_only_during_opening_hours(tmp_path):
    hub, client, _ = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD))
    h = hub.health.get(OLD)
    h.last_seen = h.last_accepted = h.last_driving = time.monotonic() - 700
    staff = {"X-Staff-Pin": "1357"}

    def no_data():
        return [w["message"] for w in client.get("/api/staff/health", headers=staff).json()["warnings"]
                if w["code"] == "no_data"]

    hub.wall_clock = lambda: at(23)
    assert no_data() == []
    hub.wall_clock = lambda: at(14)
    assert no_data() == ["On Rig 1 check: UDP Telemetry On · UDP IP Address = 192.168.1.10 · Port 20777 · "
                         "Format 2025, then drive out of the garage."] or \
        no_data()[0].startswith("On Rig 1 check: UDP Telemetry On · UDP IP Address = ")


# --- review fixes ---------------------------------------------------------------------------------

def wrong_format(packet):
    wrong = bytearray(packet)
    struct.pack_into("<H", wrong, 0, 2023)
    return bytes(wrong)


async def test_setup_reads_show_addresses_only_to_the_owner(tmp_path):
    hub, client, owner = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD) + [("192.168.1.77", wrong_format(motion(2025, 0x11, 0, 0)))])
    for url in ("/api/setup", "/api/setup/rigs"):
        anon = client.get(url)
        assert OLD not in anon.text and "192.168.1.77" not in anon.text
        (row,) = anon.json()["rigs"]
        assert (row["rig_id"], row["name"], row["number"], row["state_text"]) == (None, "Rig 1", "Rig 1", "On track")
        assert "address" not in row
        wrong = client.get(url, headers={"X-Owner-Pin": "0000"})          # a wrong PIN shows no more
        assert OLD not in wrong.text
        full = client.get(url, headers=owner)
        assert OLD in full.text and full.json()["rigs"][0]["address"] == OLD
    anon = client.get("/api/setup").json()
    assert anon["authed"] is False and client.get("/api/setup", headers=owner).json()["authed"] is True
    assert [w["message"] for w in anon["warnings"]] == [
        "A PC is sending telemetry in the wrong format: set UDP Format to 2025."]
    assert "192.168.1.77" in client.get("/api/setup", headers=owner).text


async def test_setup_reads_before_setup_need_the_setup_code(tmp_path):
    code = SetupCode(tmp_path).new()
    hub = make_hub(tmp_path)
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    await feed_from(hub, driving_rig(OLD))
    assert OLD not in client.get("/api/setup/rigs").text
    assert OLD in client.get("/api/setup/rigs", headers={"X-Setup-Code": code}).text


async def test_forget_a_rig_that_sends_only_the_wrong_format(tmp_path):
    hub, client, owner = set_up(tmp_path)
    await feed_from(hub, driving_rig(OLD))
    h = hub.health.get(OLD)
    h.last_seen = h.last_accepted = h.last_driving = time.monotonic() - 6     # its good packets are old
    hub.on_datagram(wrong_format(motion(2025, 0x11, 0, 0)), OLD, 0.0)
    r = client.delete(f"/api/setup/rigs/{OLD}", headers=owner)
    assert r.status_code == 200 and r.json()["rigs"] == []
    hub.on_datagram(wrong_format(motion(2025, 0x11, 0, 0)), OLD, 0.0)        # it stays forgotten
    assert hub.registry.get(OLD) is None


def test_garbage_senders_beyond_the_cap_get_no_health_record_or_log(tmp_path, caplog):
    import logging
    from simtelemetry import hub as hub_mod
    hub = make_hub(tmp_path)
    with caplog.at_level(logging.WARNING):
        for i in range(hub_mod.WRONG_SENDERS_MAX + 50):
            hub.on_datagram(b"garbage", f"10.9.{i // 250}.{i % 250 + 1}", 0.0)
    assert len(hub.wrong_senders) == hub_mod.WRONG_SENDERS_MAX
    assert hub.health.get("10.9.0.1") is not None
    assert hub.health.get(f"10.9.0.{hub_mod.WRONG_SENDERS_MAX + 10}") is None
    hub_lines = [r for r in caplog.records if r.name == "simtelemetry.hub"]
    gate_lines = [r for r in caplog.records if r.name.endswith("validate")]
    assert len(hub_lines) == hub_mod.WRONG_SENDER_LOGS_PER_MIN
    assert len(gate_lines) <= 10
    # Once the old senders stop, a new one takes a free place.
    later = time.monotonic() + 120
    hub.note_wrong_sender("10.8.0.1", None, later)
    assert "10.8.0.1" in hub.wrong_senders and hub.health.get("10.9.0.1") is None


def test_registry_save_survives_concurrent_saves(tmp_path):
    import threading
    hub = make_hub(tmp_path)
    for i in range(20):
        hub.registry.see(f"10.0.0.{i + 1}", 1.0, "2025", None)
    errors = []

    def saver():
        try:
            for _ in range(30):
                hub.registry.save()
        except Exception as exc:     # pragma: no cover - the failure being tested
            errors.append(exc)

    threads = [threading.Thread(target=saver) for _ in range(4)]
    for t in threads:
        t.start()
    for _ in range(30):
        hub.registry.see(f"10.0.1.{len(hub.registry.all())}", 1.0, "2025", None)
    for t in threads:
        t.join()
    assert errors == []
    assert len(json.loads((tmp_path / "rigs.json").read_text())["auto_names"]) >= 20
    assert not list(tmp_path.glob("*.tmp"))


def test_auto_names_skip_numbers_used_by_custom_names(tmp_path):
    hub = make_hub(tmp_path)
    hub.registry.see(OLD, 1.0, "2025", None)
    hub.registry.rename(OLD, "Rig 2")
    hub.registry.see(NEW, 1.0, "2025", None)
    assert hub.registry.get(NEW).auto_name == "Rig 3"
    hub.registry.rename(NEW, "rig 4")
    hub.registry.see("192.168.1.33", 1.0, "2025", None)
    assert hub.registry.get("192.168.1.33").auto_name == "Rig 5"


def test_pages_show_the_address_warning_once_and_keep_the_same_rig_choice():
    from pathlib import Path
    api = Path(__file__).resolve().parents[1] / "simtelemetry" / "api"
    staff = (api / "staff.html").read_text(encoding="utf-8")
    assert 'h.warnings.filter((w) => w !== moved)' in staff          # banner OR list, not both
    setup = (api / "setup.html").read_text(encoding="utf-8")
    assert "select[data-same]" in setup and "same.dataset.same = r.rig_id" in setup
