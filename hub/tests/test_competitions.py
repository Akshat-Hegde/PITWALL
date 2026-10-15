"""Competitions: weekly challenges (board, winner announcement), corporate events (teams, logos, scores)."""

from __future__ import annotations

import base64
import datetime as dt

import pytest

from simtelemetry.core.competitions import Competitions
from simtelemetry.core.drivers import DriverError, DriverRegistry
from simtelemetry.core.feed import FeedBuilder, FeedConnection
from simtelemetry.core.laps import LapBook, LapCompleted, LapContext, LiveLap
from simtelemetry.core.store import LapStore

from f1_helpers import STAFF, staff_ready
from test_drivers import RIG, feed, make_hub
from test_feed import last_seen, participants, session

MON = dt.datetime(2026, 10, 12, 18).timestamp()
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def lap(book, rig, driver, n, ms, pro=False, driver_id=None):
    ctx = LapContext(rig_name=rig, driver=driver, track_key="F1:7", track_name="Silverstone", session_id="s",
                     pro=pro, driver_id=driver_id)
    book.update(rig, ctx, LiveLap(n, 1000.0, 20000, True, 0, None, None, None), [])
    book.update(rig, ctx, None, [LapCompleted(n, 0.0, ms, (30000, 30000, ms - 60000), True, False, "t")])


@pytest.fixture
def world(tmp_path):
    clock = Clock(MON)
    store = LapStore(tmp_path / "laps.db")
    book = LapBook(clock=clock, store=store)
    comp = Competitions(store, tmp_path, clock=clock)
    return clock, store, book, comp


def test_challenge_board_counts_only_its_window_and_class(world):
    clock, store, book, comp = world
    lap(book, "A", "Maya", 2, 89000)                                  # before the challenge: Silverstone exists
    with pytest.raises(DriverError, match="driven at least once"):
        comp.create_challenge({"track_key": "F1:99", "starts": "2026-10-13", "ends": "2026-10-19"})
    with pytest.raises(DriverError, match="on or after"):
        comp.create_challenge({"track_key": "F1:7", "starts": "2026-10-19", "ends": "2026-10-13"})
    c = comp.create_challenge({"track_key": "F1:7", "lap_class": "pro", "starts": "2026-10-13", "ends": "2026-10-19",
                               "prize": "Free hour"})
    assert c["title"] == "Silverstone challenge" and comp.current_challenge()["state"] == "upcoming"
    clock.t = dt.datetime(2026, 10, 14, 19).timestamp()
    lap(book, "A", "Maya", 3, 88500, pro=False)                       # Open lap: not on a Pro challenge
    lap(book, "B", "Kofi", 2, 88900, pro=True)
    lap(book, "B", "Kofi", 3, 88700, pro=True)
    current = comp.current_challenge()
    assert current["state"] == "running"
    assert [(e["driver"], e["lap_ms"]) for e in current["entries"]] == [("Kofi", 88700)]
    assert comp.due_winners() == []                                   # still running
    clock.t = dt.datetime(2026, 10, 20, 12).timestamp()
    lap(book, "C", "Late", 2, 80000, pro=True)                        # after the end: doesn't count
    (won,) = comp.due_winners()
    assert won["entries"][0]["driver"] == "Kofi" and won["prize"] == "Free hour"
    assert comp.due_winners() == []                                   # announced once


def test_event_teams_score_on_their_best_n_drivers(world):
    clock, store, book, comp = world
    lap(book, "A", "warmup", 1, 99000)
    drivers = DriverRegistry(store, clock=clock)
    ana = drivers.create_profile("Ana", "07700900001", consent=True)
    event = comp.create_event({"name": "Quarter end", "company": "Acme", "accent": "#0a7cff", "track_key": "F1:7",
                               "best_n": 2})
    with pytest.raises(DriverError, match="already running"):
        comp.create_event({"name": "Other", "company": "X"})
    red = comp.add_team(event["id"], "Red team")
    blue = comp.add_team(event["id"], "Blue team")
    walk_ins = {name: drivers.create_quick_profile(name) for name in ("Rob", "Rae", "Rik", "Bo")}
    assert walk_ins["Rob"]["phone"] is None and walk_ins["Rob"]["consent_at"] is None
    for name in ("Rob", "Rae", "Rik"):
        comp.add_member(red["id"], walk_ins[name]["id"])
    comp.add_member(blue["id"], ana["id"])
    comp.add_member(blue["id"], walk_ins["Bo"]["id"])
    with pytest.raises(DriverError, match="already in this team"):
        comp.add_member(blue["id"], ana["id"])
    with pytest.raises(DriverError, match="Choose a driver profile"):
        comp.add_member(blue["id"], None)
    clock.t += 60
    for rig, name, ms in (("A", "Rob", 90000), ("B", "Rae", 92000), ("C", "Rik", 95000), ("E", "Bo", 89000)):
        lap(book, rig, name, 2, ms, driver_id=walk_ins[name]["id"])
    lap(book, "F", "Rob", 2, 80000)                                    # another "Rob" without the profile: not counted
    lap(book, "D", "Ana", 2, 91000, driver_id=ana["id"])
    active = comp.active_event()
    assert [(t["name"], t["counted"], t["average_ms"]) for t in active["teams"]] == [
        ("Blue team", 2, 90000), ("Red team", 2, 91000)]                # best 2 of each team
    assert active["company"] == "Acme" and active["accent"] == "#0a7cff"
    comp.save_logo("team", red["id"], PNG)
    assert comp.active_event()["teams"][1]["logo"].startswith("/api/logos/team-")
    with pytest.raises(DriverError, match="PNG, JPEG or WebP"):
        comp.save_logo("event", event["id"], "data:image/svg+xml;base64,PHN2Zy8+")
    comp.end_event(event["id"])
    assert comp.active_event() is None


async def test_competitions_through_the_api_and_the_tv_feed(tmp_path):
    from fastapi.testclient import TestClient
    from simtelemetry.api.app import create_app
    hub = make_hub(tmp_path)
    await feed(hub, [session(2025, 0x51), participants(2025, 0x51, b"Akshat")])
    lap(hub.laps, RIG, "Akshat", 2, 90000)
    client = TestClient(create_app(staff_ready(hub), dashboard_dir=tmp_path / "none"), headers=STAFF)
    assert client.get("/api/staff/competitions").json()["tracks"] == [{"track_key": "F1:7", "track_name": "Silverstone"}]
    today = dt.date.today().isoformat()
    r = client.post("/api/staff/challenges", json={"track_key": "F1:7", "starts": today, "ends": today, "prize": "Mug"})
    assert r.status_code == 200
    event = client.post("/api/staff/events", json={"name": "Away day", "company": "Acme", "best_n": 1}).json()
    team = client.post(f"/api/staff/events/{event['id']}/teams", json={"name": "Pit crew"}).json()
    assert client.post(f"/api/staff/teams/{team['id']}/members", json={"name": "Akshat"}).status_code == 400
    akshat = client.post("/api/staff/drivers/quick", json={"name": "Akshat"}).json()
    assert client.get("/api/staff/drivers", params={"q": "aksh"}).json()["drivers"][0]["id"] == akshat["id"]
    assert client.post(f"/api/staff/teams/{team['id']}/members", json={"driver_id": akshat["id"]}).status_code == 200
    logo = client.post(f"/api/staff/events/{event['id']}/logo", json={"data_url": PNG}).json()["logo"]
    assert client.get(f"/api/logos/{logo}").headers["content-type"] == "image/png"
    assert client.get("/api/logos/..%2Fsecrets.txt").status_code == 404

    conn = FeedConnection(FeedBuilder(hub))
    snap = conn.start(last_seen(hub))
    comp = snap["competition"]
    assert comp["challenge"]["prize"] == "Mug" and comp["challenge"]["state"] == "running"
    assert comp["event"]["company"] == "Acme" and comp["event"]["teams"][0]["name"] == "Pit crew"
    client.post(f"/api/staff/events/{event['id']}/end")
    changed = [m for m in conn.tick(last_seen(hub)) if m["type"] == "competition"]
    assert changed and changed[0]["competition"]["event"] is None
    hub.laps.store.close()


def test_old_drivers_table_allows_quick_profiles_after_migration(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "laps.db")
    db.execute("CREATE TABLE drivers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE,"
               " consent_at INTEGER NOT NULL, created_at INTEGER NOT NULL)")
    db.execute("INSERT INTO drivers VALUES (1, 'Maya', '+447700900123', 5, 5)")
    db.commit()
    db.close()
    drivers = DriverRegistry(LapStore(tmp_path / "laps.db"))
    assert drivers.profile(1)["phone"] == "+447700900123"              # kept
    quick = drivers.create_quick_profile("Guest")
    assert drivers.profile(quick["id"])["phone"] is None
    assert [d["name"] for d in drivers.search("may")] == ["Maya"] and [d["name"] for d in drivers.search("0123")] == ["Maya"]
    with pytest.raises(DriverError, match="2 or more letters"):
        drivers.search("m")
