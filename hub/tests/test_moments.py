"""Broadcast moments: Pro / Open laps, record broken, now driving, podium; feature switches."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.adapter import LiveSummary
from simtelemetry.core.laps import LapBook, LapContext, LiveLap
from simtelemetry.core.store import LapStore

from test_drivers import RIG, client_with_rig, make_hub
from test_laps import lap

PRO = {"traction_control": 0, "anti_lock_brakes": 0, "steering": 0, "braking": 0, "gearbox": 1, "racing_line": 0}


def ctx(driver="Maya", pro=None):
    return LapContext(rig_name="Rig 1", driver=driver, track_key="F1:7", track_name="Silverstone", session_id="s1",
                      pro=pro)


def drive(book, rig, driver, n, ms, pro):
    """The lap in progress is seen (with its assists), then completes."""
    book.update(rig, ctx(driver, pro), LiveLap(n, 2000.0, 40000, True, 1, 30000, None, None), [])
    return book.update(rig, ctx(driver, pro), None, [lap(n, ms)])[0]


def moments(book):
    return [body["moment"] for _, type_, body in book.messages if type_ == "moment"]


def test_pro_needs_every_assist_off_and_known():
    s = LiveSummary()
    assert s.pro is None
    s.assists = dict(PRO)
    assert s.pro is True
    s.assists = {**PRO, "gearbox": 3}
    assert s.pro is False
    s.assists = {k: v for k, v in PRO.items() if k != "racing_line"}
    assert s.pro is None  # not all reported yet


def test_lap_class_follows_assists_through_the_whole_lap():
    book = LapBook()
    assert drive(book, "A", "Maya", 2, 90000, pro=True).lap_class == "pro"
    assert drive(book, "A", "Maya", 3, 90000, pro=False).lap_class == "open"
    # assists switched off only at the end of the lap: still Open
    book.update("A", ctx(pro=False), LiveLap(4, 100.0, 1000, True, 0, None, None, None), [])
    assert drive(book, "A", "Maya", 4, 89000, pro=True).lap_class == "open"
    assert drive(book, "A", "Maya", 5, 90000, pro=None).lap_class == "open"  # unknown counts as Open
    assert [r.lap_class for r in book.leaderboard("F1:7", "pro")] == ["pro"]
    assert book.recent[0].to_schema()["lap_class"] == "open"


def test_record_moment_lists_what_was_beaten(tmp_path):
    book = LapBook(store=LapStore(tmp_path / "laps.db"))
    drive(book, "A", "Maya", 2, 90000, pro=False)
    assert moments(book) == []                                        # first lap: no record to break
    drive(book, "B", "Kofi", 2, 89500, pro=True)
    (m,) = moments(book)
    assert m["kind"] == "record" and m["driver"] == "Kofi" and m["lap_ms"] == 89500 and m["lap_class"] == "pro"
    assert [(r["period"], r["lap_class"], r["previous_driver"], r["gap_ms"]) for r in m["records"]] == [
        ("all_time", "open", "Maya", -500), ("today", "open", "Maya", -500)]  # no Pro lap before: no Pro record
    drive(book, "B", "Kofi", 3, 89000, pro=True)
    assert [(r["period"], r["lap_class"]) for r in moments(book)[-1]["records"]] == [
        ("all_time", "pro"), ("all_time", "open"), ("today", "pro"), ("today", "open")]
    drive(book, "A", "Maya", 3, 89200, pro=False)                     # beats nothing
    assert len(moments(book)) == 2


def test_old_databases_get_the_lap_class_column(tmp_path):
    path = tmp_path / "laps.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE laps (id INTEGER PRIMARY KEY, rig_id TEXT NOT NULL, rig_name TEXT NOT NULL,"
               " driver TEXT, driver_key TEXT NOT NULL, track_key TEXT NOT NULL, track_name TEXT, session_id TEXT,"
               " lap_number INTEGER NOT NULL, lap_ms INTEGER NOT NULL, s1_ms INTEGER, s2_ms INTEGER, s3_ms INTEGER,"
               " valid INTEGER NOT NULL, out_lap INTEGER NOT NULL, tyre TEXT, completed_at INTEGER NOT NULL)")
    db.execute("INSERT INTO laps VALUES (1,'A','Rig 1','Maya','driver:maya','F1:7','Silverstone','s',2,90000,"
               "NULL,NULL,NULL,1,0,NULL,1)")
    db.commit()
    db.close()
    store = LapStore(path)
    assert [r["driver"] for r in store.board("F1:7", None)] == ["Maya"]  # old laps count as Open
    assert store.board("F1:7", None, lap_class="pro") == []


async def test_now_driving_and_podium_from_the_staff_page(tmp_path):
    hub, client = await client_with_rig(tmp_path)
    client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Maya"})
    (m,) = moments(hub.laps)
    assert m["kind"] == "now_driving" and m["driver"] == "Maya" and m["rig_id"] == RIG
    assert m["track_name"] == "Silverstone"
    assert client.post("/api/staff/podium").status_code == 409        # no laps today yet
    drive(hub.laps, RIG, "Maya", 2, 90000, pro=False)
    assert client.post("/api/staff/podium").json() == {"shown": True, "entries": 1}
    podium = moments(hub.laps)[-1]
    assert podium["kind"] == "podium" and podium["reason"] == "staff" and podium["entries"][0]["driver"] == "Maya"


async def test_features_can_be_switched_off(tmp_path):
    hub, client = await client_with_rig(tmp_path, features={"moments": False, "podium": False},
                                        sounds={"enabled": True, "volume": 0.3})
    client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Maya"})
    drive(hub.laps, RIG, "Maya", 2, 90000, pro=False)
    assert client.post("/api/staff/podium").status_code == 409
    assert moments(hub.laps) == []
    with TestClient(create_app(hub, dashboard_dir=tmp_path / "none")).websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
    assert snapshot["hub"]["features"]["moments"] is False
    assert snapshot["hub"]["sounds"] == {"enabled": True, "volume": 0.3}
    assert snapshot["hub"]["moments"] == {"battle_margin_ms": 300}


def test_make_hub_still_works(tmp_path):
    assert make_hub(tmp_path).config.moments.podium_every_min == 60


def test_portrait_serves_the_dashboard(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>TV</title>", encoding="utf-8")
    client = TestClient(create_app(make_hub(tmp_path), dashboard_dir=dist))
    assert client.get("/portrait").text == client.get("/").text
