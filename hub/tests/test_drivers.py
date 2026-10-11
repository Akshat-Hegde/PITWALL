"""Driver names: staff assignment, fallback order, lap attribution, /staff page and API."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from simtelemetry.adapters.f1.adapter import F1Adapter
from simtelemetry.api.app import create_app
from simtelemetry.config import AppConfig
from simtelemetry.core.drivers import DriverError, DriverRegistry
from simtelemetry.core.feed import FeedBuilder
from simtelemetry.core.rigs import RigRegistry
from simtelemetry.core.store import LapStore
from simtelemetry.hub import Hub

from test_feed import last_seen, participants, session
from test_laps import history_bytes, lap_data_bytes

RIG = "192.168.1.21"
UID = 0x51


def make_hub(tmp_path, store=True, **cfg) -> Hub:
    config = AppConfig(data_dir=tmp_path, **cfg)
    return Hub(config, F1Adapter(config.track_names), RigRegistry(config, tmp_path / "rigs.json"),
               store=LapStore(tmp_path / "laps.db") if store else None)


async def feed(hub, packets):
    consumer = asyncio.create_task(hub.consume())
    for data in packets:
        hub.on_datagram(data, RIG, 0.0)
    await hub.drain()
    consumer.cancel()


# --- registry -----------------------------------------------------------------------------------

def test_fallback_order():
    drivers = DriverRegistry()
    assert drivers.lap_name(RIG, None, "Rig 1") == "Rig 1"           # nothing known: rig name
    assert drivers.lap_name(RIG, "Akshat", "Rig 1") == "Akshat"       # the game's player name
    assert drivers.display_name(RIG, None) is None
    drivers.assign(RIG, "  Maya   R ")
    assert drivers.lap_name(RIG, "Akshat", "Rig 1") == "Maya R"       # assigned name wins, tidied
    assert drivers.display_name(RIG, "Akshat") == "Maya R"
    assert drivers.end(RIG) is True and drivers.end(RIG) is False
    assert drivers.lap_name(RIG, "Akshat", "Rig 1") == "Akshat"


@pytest.mark.parametrize("name, minutes, message", [
    ("", None, "Enter the driver's name."),
    ("x" * 33, None, "at most 32"),
    ("Maya", "abc", "number of minutes"),
    ("Maya", 0.5, "1 to 720 minutes"),
])
def test_validation(name, minutes, message):
    with pytest.raises(DriverError, match=message):
        DriverRegistry().assign(RIG, name, minutes=minutes)


def test_sessions_are_stored_and_restored(tmp_path):
    store = LapStore(tmp_path / "laps.db")
    drivers = DriverRegistry(store, clock=lambda: 1000.0)
    drivers.assign(RIG, "Maya", minutes=20)
    drivers.assign("192.168.1.22", "Guest")
    drivers.assign(RIG, "Kofi")                                       # replaces Maya, closes her session
    drivers.end("192.168.1.22")
    store.close()

    store = LapStore(tmp_path / "laps.db")                            # hub restarted
    restored = DriverRegistry(store)
    assert restored.get(RIG).name == "Kofi" and restored.get("192.168.1.22") is None
    rows = [(r["rig_id"], r["name"], r["ends_at"], r["ended_at"]) for r in store.driver_sessions()]
    assert rows == [(RIG, "Maya", 1_000_000 + 20 * 60_000, 1_000_000),
                    ("192.168.1.22", "Guest", None, 1_000_000),
                    (RIG, "Kofi", None, None)]
    store.close()


# --- laps follow the name ----------------------------------------------------------------------

def lap_packets(lap, lap_ms, history, t):
    """Lap `lap` driven to the line, the rollover to lap+1 and history with `history` completed laps."""
    return [lap_data_bytes(2025, UID, t, lap, 5000, lap_ms - 500, sector=2, s1=28000, s2=33000),
            lap_data_bytes(2025, UID, t + 0.5, lap + 1, 2, 20, last_ms=lap_ms),
            history_bytes(2025, UID, t + 0.6, history + [(0, 0, 0, 0, True)])]


async def test_laps_keep_the_name_they_were_driven_under(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [session(2025, UID), participants(2025, UID, b"Akshat")])
    lap1 = (89000, 28000, 33000, 28000, True)
    lap2 = (88000, 28000, 33000, 27000, True)
    lap3 = (87500, 28000, 33000, 26500, True)
    await feed(hub, lap_packets(1, 89000, [lap1], 10.0))               # no name assigned: game name
    hub.drivers.assign(RIG, "Maya")                                    # staff set the name mid-session
    await feed(hub, lap_packets(2, 88000, [lap1, lap2], 100.0))
    hub.drivers.end(RIG)                                               # Maya leaves; game name again
    await feed(hub, lap_packets(3, 87500, [lap1, lap2, lap3], 190.0))

    assert [(r.lap_number, r.driver) for r in hub.laps.laps] == [(1, "Akshat"), (2, "Maya"), (3, "Akshat")]
    board = hub.laps.board("F1:7", "all_time", None)
    assert [(e["driver"], e["lap_ms"]) for e in board["entries"]] == [("Akshat", 87500), ("Maya", 88000)]

    # The TV shows the current name and that driver's personal best on this track.
    hub.drivers.assign(RIG, "Maya")
    rig = FeedBuilder(hub).rig_frame(hub.registry.get(RIG), last_seen(hub))
    assert rig["driver"] == "Maya" and rig["personal_best"]["lap_ms"] == 88000
    hub.drivers.end(RIG)
    rig = FeedBuilder(hub).rig_frame(hub.registry.get(RIG), last_seen(hub))
    assert rig["driver"] == "Akshat" and rig["personal_best"]["lap_ms"] == 87500
    hub.laps.store.close()


async def test_rig_name_when_nothing_else_is_known(tmp_path):
    hub = make_hub(tmp_path, store=False)
    await feed(hub, [session(2025, UID)])                              # no Participants packet
    await feed(hub, lap_packets(1, 89000, [(89000, 28000, 33000, 28000, True)], 10.0))
    assert [r.driver for r in hub.laps.laps] == ["Rig 1"]
    rig = FeedBuilder(hub).rig_frame(hub.registry.get(RIG), last_seen(hub))
    assert rig["driver"] is None and rig["personal_best"]["lap_ms"] == 89000


# --- /staff page and API ------------------------------------------------------------------------

async def client_with_rig(tmp_path, **cfg):
    hub = make_hub(tmp_path, store=False, **cfg)
    await feed(hub, [session(2025, UID), participants(2025, UID, b"Akshat")])
    return hub, TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))


async def test_staff_page_and_api(tmp_path):
    hub, client = await client_with_rig(tmp_path)
    page = client.get("/staff")
    assert page.status_code == 200 and "Start session" in page.text

    (rig,) = client.get("/api/staff/rigs").json()["rigs"]
    assert (rig["rig_id"], rig["rig_name"], rig["game_driver"], rig["session"], rig["laps_stored_as"]) == \
        (RIG, "Rig 1", "Akshat", None, "Akshat")

    r = client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Maya", "minutes": 20})
    assert r.status_code == 200
    assert r.json()["session"]["name"] == "Maya" and r.json()["laps_stored_as"] == "Maya"
    assert 19 * 60_000 < r.json()["time_left_ms"] <= 20 * 60_000 and r.json()["extend_prompt"] is False

    bad = client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": ""})
    assert bad.status_code == 400 and bad.json()["detail"] == "Enter the driver's name."
    assert client.put("/api/staff/rigs/10.0.0.9/driver", json={"name": "X"}).status_code == 404

    r = client.delete(f"/api/staff/rigs/{RIG}/driver")
    assert r.status_code == 200 and r.json()["session"] is None and r.json()["laps_stored_as"] == "Akshat"


async def test_staff_pin(tmp_path):
    _, client = await client_with_rig(tmp_path, staff={"pin": "4821"})
    assert client.get("/staff").status_code == 200                     # the page itself loads
    r = client.get("/api/staff/rigs")
    assert r.status_code == 401 and r.json()["detail"] == "Enter the staff PIN."
    assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "4821"}).status_code == 200
    assert client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Maya"}).status_code == 401
    for _ in range(5):
        assert client.get("/api/staff/rigs", headers={"X-Staff-Pin": "0000"}).json()["detail"] == "Wrong PIN."
    locked = client.get("/api/staff/rigs", headers={"X-Staff-Pin": "4821"})
    assert locked.status_code == 429 and "Wait a minute" in locked.json()["detail"]
