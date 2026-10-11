"""Driver profiles (phone + consent), booking timers, the queue, deleting a profile, the TV feed."""

from __future__ import annotations

import datetime as dt

import pytest

from simtelemetry.core.drivers import DriverError, DriverRegistry
from simtelemetry.core.feed import FeedBuilder, FeedConnection
from simtelemetry.core.laps import LapBook, LapCompleted, LapContext
from simtelemetry.core.store import LapStore

from test_drivers import RIG, client_with_rig
from test_feed import last_seen

DAY1 = dt.datetime(2026, 10, 3, 18).timestamp()
DAY2 = dt.datetime(2026, 10, 10, 18).timestamp()


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_a_phone_number_is_only_stored_with_consent():
    drivers = DriverRegistry()
    with pytest.raises(DriverError, match="consent"):
        drivers.create_profile("Maya", "+44 7700 900123", consent=False)
    with pytest.raises(DriverError, match="6 to 15 digits"):
        drivers.create_profile("Maya", "12-34", consent=True)
    maya = drivers.create_profile("Maya", "+44 7700-900 123", consent=True)
    assert maya["phone"] == "+447700900123" and maya["consent_at"] > 0
    with pytest.raises(DriverError, match="already exists"):
        drivers.create_profile("Maya again", "+447700900123", consent=True)
    assert [d["name"] for d in drivers.search("0123")] == ["Maya"]   # the last digits are enough
    with pytest.raises(DriverError, match="4 or more digits"):
        drivers.search("12")


def test_booking_timer_and_extend():
    clock = Clock(1000.0)
    drivers = DriverRegistry(clock=clock)
    drivers.assign(RIG, "Maya", minutes=20)
    assert drivers.time_left_ms(RIG) == 20 * 60_000
    clock.t += 17 * 60
    assert drivers.time_left_ms(RIG) == 3 * 60_000
    drivers.extend(RIG, 10)
    assert drivers.time_left_ms(RIG) == 13 * 60_000
    clock.t += 20 * 60                                                 # ran over: extending starts from now
    drivers.extend(RIG, 5)
    assert drivers.time_left_ms(RIG) == 5 * 60_000
    with pytest.raises(DriverError, match="No session"):
        drivers.extend("10.0.0.9", 5)


def test_queue_and_starting_from_it():
    drivers = DriverRegistry()
    maya = drivers.create_profile("Maya", "07700900123", consent=True)
    drivers.queue_add("Guest 1")
    entry = drivers.queue_add(driver_id=maya["id"])
    assert [e["name"] for e in drivers.queue()] == ["Guest 1", "Maya"]
    session = drivers.start_from_queue(entry["id"], RIG, minutes=15)
    assert session.name == "Maya" and session.driver_id == maya["id"]
    assert [e["name"] for e in drivers.queue()] == ["Guest 1"]


def lap(n, ms):
    return LapCompleted(n, 0.0, ms, (30000, 30000, ms - 60000), True, False, "test")


def test_profile_visits_bests_improvement_and_delete(tmp_path):
    clock = Clock(DAY1)
    store = LapStore(tmp_path / "laps.db")
    drivers = DriverRegistry(store, clock=clock)
    book = LapBook(clock=clock, store=store)
    maya = drivers.create_profile("Maya", "07700900123", consent=True)
    ctx = LapContext(rig_name="Rig 1", driver="Maya", track_key="F1:7", track_name="Silverstone", session_id="s",
                     driver_id=maya["id"])

    drivers.assign(RIG, driver_id=maya["id"])
    book.update(RIG, ctx, None, [lap(2, 91000), lap(3, 90500)])
    clock.t += 30 * 60
    drivers.end(RIG)
    clock.t = DAY2                                                     # a week later
    drivers.assign(RIG, driver_id=maya["id"])
    book.update(RIG, ctx, None, [lap(2, 89800)])

    details = drivers.profile_details(maya["id"])
    assert [(v["date"], v["sessions"], v["laps"]) for v in details["visits"]] == [
        ("2026-10-10", 1, 1), ("2026-10-03", 1, 2)]
    assert details["visits"][1]["minutes"] == 30
    assert [(b["track_name"], b["lap_ms"], b["laps"]) for b in details["bests"]] == [("Silverstone", 89800, 3)]
    (imp,) = details["improvement"]
    assert (imp["best_ms"], imp["previous_best_ms"], imp["delta_ms"]) == (89800, 90500, -700)

    # A profile's laps follow the profile, not the name: same name, other driver, separate board entries.
    other = LapContext(rig_name="Rig 2", driver="Maya", track_key="F1:7", track_name="Silverstone", session_id="t")
    book.update("B", other, None, [lap(2, 92000)])
    assert len(book.board("F1:7", "all_time", None)["entries"]) == 2

    removed = drivers.delete_profile(maya["id"])
    book.forget_driver(maya["id"])
    assert removed == {"laps": 3, "sessions": 2}
    assert drivers.profile(maya["id"]) is None and drivers.get(RIG) is None
    assert [e["lap_ms"] for e in book.board("F1:7", "all_time", None)["entries"]] == [92000]
    assert all(r.driver_id != maya["id"] for r in book.laps)


async def test_staff_api_profiles_queue_extend_delete(tmp_path):
    hub, client = await client_with_rig(tmp_path)
    r = client.post("/api/staff/drivers", json={"name": "Maya", "phone": "07700 900123", "consent": False})
    assert r.status_code == 400 and "consent" in r.json()["detail"]
    maya = client.post("/api/staff/drivers", json={"name": "Maya", "phone": "07700 900123", "consent": True}).json()
    assert client.get("/api/staff/drivers", params={"phone": "0123"}).json()["drivers"][0]["id"] == maya["id"]

    client.post("/api/staff/queue", json={"driver_id": maya["id"]})
    client.post("/api/staff/queue", json={"name": "Guest"})
    queue = client.get("/api/staff/rigs").json()["queue"]
    assert [e["name"] for e in queue] == ["Maya", "Guest"]
    r = client.put(f"/api/staff/rigs/{RIG}/driver", json={"queue_id": queue[0]["id"], "minutes": 4})
    assert r.json()["session"]["driver_id"] == maya["id"] and r.json()["extend_prompt"] is True  # 4 min < 5
    r = client.post(f"/api/staff/rigs/{RIG}/extend", json={"minutes": 10})
    assert r.json()["extend_prompt"] is False
    assert [e["name"] for e in client.get("/api/staff/rigs").json()["queue"]] == ["Guest"]

    # The TV gets the booking and the queue (names only, never phone numbers).
    builder = FeedBuilder(hub)
    frame = builder.rig_frame(hub.registry.get(RIG), last_seen(hub))
    assert frame["booking"]["driver"] == "Maya" and frame["booking"]["ends_at"] > frame["booking"]["started_at"]
    conn = FeedConnection(builder)
    snapshot = conn.start(last_seen(hub))
    assert snapshot["queue"] == [{"id": queue[1]["id"], "name": "Guest"}]
    client.delete(f"/api/staff/queue/{queue[1]['id']}")
    assert [m["queue"] for m in conn.tick(last_seen(hub)) if m["type"] == "queue"] == [[]]

    profile = client.get(f"/api/staff/drivers/{maya['id']}").json()
    assert profile["name"] == "Maya" and profile["visits"][0]["sessions"] == 1
    assert client.delete(f"/api/staff/drivers/{maya['id']}").json()["deleted"] is True
    assert client.get(f"/api/staff/drivers/{maya['id']}").status_code == 404
    assert hub.drivers.get(RIG) is None                               # her session ended with the profile
