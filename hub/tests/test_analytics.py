"""Owner analytics: utilisation, heatmap, new vs returning, tracks, CSV; the /owner PIN."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.analytics import Analytics
from simtelemetry.core.drivers import Assignment
from simtelemetry.core.laps import LapRecord
from simtelemetry.core.store import LapStore

from test_drivers import make_hub

NOW = dt.datetime(2026, 10, 14, 21, 0)  # a Wednesday evening


def ms(d: dt.datetime) -> int:
    return round(d.timestamp() * 1000)


def session(store, rig, name, start, minutes, driver_id=None):
    store.start_driver_session(rig, Assignment(name, ms(start), driver_id))
    store.end_driver_session(rig, ms(start + dt.timedelta(minutes=minutes)))


def lap(store, rig, driver, when, lap_ms, track="F1:7", name="Silverstone"):
    store.add(LapRecord(rig_id=rig, rig_name=rig, driver=driver, track_key=track, track_name=name, session_id="s",
                        lap_number=2, lap_ms=lap_ms, sectors_ms=None, valid=True, out_lap=False, tyre=None,
                        personal_best=False, session_best=False, completed_at=ms(when)))


def seeded(tmp_path) -> LapStore:
    store = LapStore(tmp_path / "laps.db")
    session(store, "rig-1", "Maya", NOW - dt.timedelta(days=9, hours=2), 60)   # outside a 7-day window
    session(store, "rig-1", "Maya", dt.datetime(2026, 10, 13, 18, 30), 60)      # Tue 18:30-19:30: returning
    session(store, "rig-2", "Kofi", dt.datetime(2026, 10, 13, 19, 0), 30)       # Tue 19:00-19:30: new
    session(store, "rig-1", "kofi", dt.datetime(2026, 10, 14, 20, 0), 30)       # Wed: Kofi returns (name case)
    lap(store, "rig-1", "Maya", dt.datetime(2026, 10, 13, 18, 45), 90000)
    lap(store, "rig-2", "Kofi", dt.datetime(2026, 10, 13, 19, 10), 92000)
    lap(store, "rig-1", "Kofi", dt.datetime(2026, 10, 14, 20, 10), 91000, track="F1:10", name="Spa")
    return store


def test_report(tmp_path):
    a = Analytics(seeded(tmp_path), open_hour=10, close_hour=22, clock=lambda: NOW.timestamp())
    r = a.report(7)
    assert (r["from"], r["to"]) == ("2026-10-08", "2026-10-14")
    s = r["summary"]
    assert (s["sessions"], s["hours"], s["drivers"], s["new_drivers"], s["laps"]) == (3, 2.0, 2, 1, 3)
    tue = next(d for d in r["daily"] if d["date"] == "2026-10-13")
    assert (tue["sessions"], tue["hours"], tue["new"], tue["returning"], tue["laps"]) == (2, 1.5, 1, 1, 2)
    wed = next(d for d in r["daily"] if d["date"] == "2026-10-14")
    assert (wed["new"], wed["returning"]) == (0, 1)
    # Tuesday 18:00-19:00: 30 min on one rig; 19:00-20:00: 30 + 30 min. One Tuesday in the window.
    tue_row = r["heatmap"]["rigs_in_use"][1]
    assert (tue_row[18], tue_row[19]) == (0.5, 1.0)
    util = {u["rig_id"]: u["days"] for u in r["utilisation"]}
    assert util["rig-1"][-2] == round(100 * 60 / 720, 1)                       # 60 of 720 open minutes
    assert [(t["track_name"], t["laps"], t["drivers"]) for t in r["tracks"]] == [("Silverstone", 2, 2), ("Spa", 1, 1)]
    assert r["busiest_days"][0]["date"] == "2026-10-13"


def test_csv(tmp_path):
    a = Analytics(seeded(tmp_path), clock=lambda: NOW.timestamp())
    daily = a.csv("daily", 7).splitlines()
    assert daily[0].startswith("date,weekday,sessions,hours") and len(daily) == 8
    assert "Maya" in a.csv("sessions", 7) and "Spa" in a.csv("laps", 7)


def test_owner_page_needs_its_own_pin(tmp_path):
    client = TestClient(create_app(make_hub(tmp_path), dashboard_dir=tmp_path / "none"))
    assert client.get("/owner").status_code == 200
    r = client.get("/api/owner/report")
    assert r.status_code == 403 and "Finish setup first" in r.json()["detail"]   # locked until a PIN is set

    hub = make_hub(tmp_path / "b", owner={"pin": "9090"}, staff={"pin": "1111"})
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    assert client.get("/api/owner/report").status_code == 401
    assert client.get("/api/owner/report", headers={"X-Staff-Pin": "1111"}).status_code == 401  # staff PIN isn't enough
    ok = client.get("/api/owner/report?days=7", headers={"X-Owner-Pin": "9090"})
    assert ok.status_code == 200 and ok.json()["days"] == 7
    csv = client.get("/api/owner/export.csv?kind=sessions", headers={"X-Owner-Pin": "9090"})
    assert csv.headers["content-type"].startswith("text/csv") and "attachment" in csv.headers["content-disposition"]
    assert client.get("/api/owner/export.csv?kind=secrets", headers={"X-Owner-Pin": "9090"}).status_code == 400


def test_seed_demo_never_touches_real_data(tmp_path):
    import pytest
    from simtelemetry.tools.seed_demo import DemoTargetError, seed
    real = tmp_path / "data"
    real.mkdir()
    (real / "laps.db").write_text("real", encoding="utf-8")
    with pytest.raises(DemoTargetError, match="other files"):
        seed(real, days=3)
    assert (real / "laps.db").read_text(encoding="utf-8") == "real"

    demo = tmp_path / "data-demo"
    counts = seed(demo, days=10, now=NOW.timestamp())
    assert counts["sessions"] > 20 and counts["laps"] > 100 and counts["profiles"] > 5
    again = seed(demo, days=10, now=NOW.timestamp())                  # re-seeding its own folder is fine
    assert again == counts
    report = Analytics(LapStore(demo / "laps.db"), clock=lambda: NOW.timestamp()).report(7)
    assert report["summary"]["sessions"] > 0 and report["tracks"]


def test_rigs_are_shown_by_name_never_by_address(tmp_path):
    store = LapStore(tmp_path / "laps.db")
    session(store, "10.0.0.7", "Maya", dt.datetime(2026, 10, 13, 18, 0), 30)
    session(store, "10.0.0.8", "Kofi", dt.datetime(2026, 10, 13, 18, 0), 30)
    lap(store, "10.0.0.8", "Kofi", dt.datetime(2026, 10, 13, 18, 10), 90000)   # lap stored as rig "10.0.0.8"...
    store._db.execute("UPDATE laps SET rig_name = 'Rig 2'")                    # ...under its name at the time
    names = {"10.0.0.7": "Window rig"}                                          # the hub's registry (config name)
    a = Analytics(store, clock=lambda: NOW.timestamp(), rig_label=lambda ip: names.get(ip) or
                  store.rig_names().get(ip) or ip)
    r = a.report(7)
    assert r["rigs"] == ["Rig 2", "Window rig"]
    assert {u["rig_name"] for u in r["utilisation"]} == {"Rig 2", "Window rig"}
    sessions_csv = a.csv("sessions", 7)
    assert "Window rig" in sessions_csv and "Rig 2" in sessions_csv and "10.0.0." not in sessions_csv
    assert "10.0.0." not in a.csv("laps", 7)
    # Without a hub, the names stored with the laps are used.
    assert set(Analytics(store, clock=lambda: NOW.timestamp()).report(7)["rigs"]) == {"Rig 2", "10.0.0.7"}


def test_seeded_demo_covers_every_simulated_rig(tmp_path):
    from simtelemetry.tools.demo_sim import GAME_NAMES
    from simtelemetry.tools.seed_demo import seed
    seed(tmp_path / "demo", days=5, now=NOW.timestamp())
    report = Analytics(LapStore(tmp_path / "demo" / "laps.db"), clock=lambda: NOW.timestamp()).report(5)
    assert report["rigs"] == [f"Rig {n}" for n in range(1, len(GAME_NAMES) + 1)]
    assert all(sum(u["days"]) > 0 for u in report["utilisation"])           # every rig has history
