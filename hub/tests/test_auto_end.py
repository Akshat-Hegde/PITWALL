"""Sessions end automatically: at closing time, and timed sessions once over time and idle (U2)."""

import asyncio
import datetime as dt
import time

from simtelemetry.hub import AUTO_END_IDLE_S, NO_CARD_TEXT

from test_drivers import RIG, make_hub


def wall(hub, when: dt.datetime) -> None:
    hub.wall_clock = lambda: when


def started(hub, minutes=None, name="Alex"):
    session = hub.drivers.assign(RIG, name, minutes=minutes)
    return session, dt.datetime.fromtimestamp(session.started_at / 1000)


def closing_of(start: dt.datetime, hour: int) -> dt.datetime:
    at = start.replace(hour=hour, minute=0, second=0, microsecond=0)
    return at if at > start else at + dt.timedelta(days=1)


def test_session_ends_at_closing_time_and_staff_see_why(tmp_path):
    hub = make_hub(tmp_path, owner={"open_hour": 0, "close_hour": 24})
    _, start = started(hub)
    close = closing_of(start, 0)                       # closes at midnight
    wall(hub, close - dt.timedelta(minutes=1))
    assert hub.auto_end_sessions() == [] and hub.drivers.get(RIG) is not None
    wall(hub, close)
    (notice,) = hub.auto_end_sessions()
    assert hub.drivers.get(RIG) is None
    assert notice["reason"] == "closing" and notice["text"] == "Ended automatically at closing time"
    assert notice["driver"] == "Alex" and notice["card"] is None and notice["card_note"] == NO_CARD_TEXT
    assert hub.drivers.store.current_driver_sessions() == {}         # ended in the database too
    assert hub.auto_ended[RIG] is notice
    hub.drivers.assign(RIG, "Sam")
    hub.session_started(RIG)                                          # the next session clears the notice
    assert RIG not in hub.auto_ended


def test_timed_session_ends_only_when_over_time_and_idle(tmp_path, monkeypatch):
    hub = make_hub(tmp_path, owner={"open_hour": 0, "close_hour": 24})
    session, start = started(hub, minutes=10)
    over = start + dt.timedelta(minutes=10, seconds=1)
    if over >= closing_of(start, 0):
        return                                          # the test ran at 23:50: closing time would end it first
    driving = {"since": 5.0}
    monkeypatch.setattr(hub.health, "seconds_since_driving", lambda ip, now: driving["since"])
    wall(hub, start + dt.timedelta(minutes=9))
    assert hub.auto_end_sessions() == []                # time not up yet
    wall(hub, over)
    assert hub.auto_end_sessions() == []                # time up, but still driving
    driving["since"] = AUTO_END_IDLE_S - 1
    assert hub.auto_end_sessions() == []
    driving["since"] = AUTO_END_IDLE_S
    (notice,) = hub.auto_end_sessions()
    assert notice["reason"] == "overrun" and notice["text"] == "Ended automatically: time was up"


def test_session_without_a_timer_runs_until_closing(tmp_path):
    hub = make_hub(tmp_path, owner={"open_hour": 0, "close_hour": 24})
    _, start = started(hub)                              # check-in and "No timer" sessions have no time
    wall(hub, min(start + dt.timedelta(hours=3), closing_of(start, 0) - dt.timedelta(seconds=1)))
    assert hub.auto_end_sessions() == []


def test_session_left_open_from_a_previous_day_ends_on_start_up(tmp_path):
    hub = make_hub(tmp_path)
    _, start = started(hub)
    hub.drivers.store.close()
    # The hub restarts the next day: the session is still open in the database.
    hub = make_hub(tmp_path)
    assert hub.drivers.get(RIG) is not None
    wall(hub, start + dt.timedelta(days=1))

    async def first_tick():
        task = asyncio.create_task(hub.tick_auto_end(every=3600))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(first_tick())
    assert hub.drivers.get(RIG) is None and hub.auto_ended[RIG]["reason"] == "closing"


def test_auto_end_can_be_switched_off(tmp_path):
    hub = make_hub(tmp_path, features={"auto_end_sessions": False})
    _, start = started(hub)
    wall(hub, start + dt.timedelta(days=2))
    assert hub.auto_end_sessions() == [] and hub.drivers.get(RIG) is not None


def test_closing_after_midnight_keeps_the_evening_session(tmp_path):
    # Opens 16:00, closes 02:00 (next day): a session from 23:00 is still on at 01:00 and ends at 02:00.
    hub = make_hub(tmp_path, owner={"open_hour": 16, "close_hour": 2})
    session, _ = started(hub)
    evening = dt.datetime(2026, 10, 15, 23, 0)
    hub.drivers._current[RIG] = type(session)(session.name, round(evening.timestamp() * 1000))
    wall(hub, dt.datetime(2026, 10, 16, 1, 0))
    assert hub.auto_end_sessions() == []
    wall(hub, dt.datetime(2026, 10, 16, 2, 0))
    assert [n["reason"] for n in hub.auto_end_sessions()] == ["closing"]


def test_staff_page_shows_the_automatic_end(tmp_path):
    from fastapi.testclient import TestClient
    from simtelemetry.api.app import create_app
    from f1_helpers import STAFF, staff_ready
    hub = make_hub(tmp_path)
    staff_ready(hub)
    hub.registry.see(RIG, time.monotonic(), "2025", None)
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"), headers=STAFF)
    _, start = started(hub)
    wall(hub, start + dt.timedelta(days=1))
    hub.auto_end_sessions()
    (row,) = client.get("/api/staff/rigs").json()["rigs"]
    assert row["session"] is None and row["auto_ended"]["text"] == "Ended automatically at closing time"
    # Staff ending a session with no clean lap get told why there's no card.
    client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Sam"})
    r = client.delete(f"/api/staff/rigs/{RIG}/driver").json()
    assert r["card"] is None and r["card_note"] == NO_CARD_TEXT and r["auto_ended"] is None


# --- review fixes: restart, one rig failing, double end ------------------------------------------

def _old_timed_session(hub, rig=RIG, name="Alex"):
    """A 10-minute session that started at 14:00; the wall clock says 15:00 (well over time, before closing)."""
    session = hub.drivers.assign(rig, name, minutes=10)
    start = dt.datetime(2026, 10, 15, 14, 0)
    ms = round(start.timestamp() * 1000)
    hub.drivers._current[rig] = type(session)(session.name, ms, None, ms + 10 * 60_000)
    wall(hub, dt.datetime(2026, 10, 15, 15, 0))
    return hub.drivers._current[rig]


def test_hub_restart_does_not_cut_off_a_guest_over_time(tmp_path):
    # Just after a restart the hub has heard nothing from the rig yet: idle counts from the hub's start,
    # not from the session's start, so a guest still lapping isn't ended the moment the hub comes back.
    hub = make_hub(tmp_path, owner={"open_hour": 0, "close_hour": 24})
    _old_timed_session(hub)
    assert hub.health.seconds_since_driving(RIG, time.monotonic()) is None
    assert hub.auto_end_sessions() == [] and hub.drivers.get(RIG) is not None
    hub.started_at -= AUTO_END_IDLE_S + 1             # 5 minutes after the restart and still nothing: idle
    assert [n["reason"] for n in hub.auto_end_sessions()] == ["overrun"]


def test_one_rig_failing_does_not_stop_the_others(tmp_path, monkeypatch):
    hub = make_hub(tmp_path, owner={"open_hour": 0, "close_hour": 24})
    other = "10.0.0.99"
    _old_timed_session(hub, RIG, "Alex")
    _old_timed_session(hub, other, "Sam")
    hub.started_at -= AUTO_END_IDLE_S + 1

    def broken_card(ip, session):
        if ip == RIG:
            raise RuntimeError("card renderer broke")
        return None
    monkeypatch.setattr(hub, "_make_card", broken_card)
    notices = hub.auto_end_sessions()
    assert sorted(n["driver"] for n in notices) == ["Alex", "Sam"]   # the failing card still ends Alex's session
    assert hub.drivers.get(RIG) is None and hub.drivers.get(other) is None
    assert hub.auto_ended[RIG]["card"] is None


def test_a_rig_whose_check_fails_is_skipped_and_the_rest_still_end(tmp_path, monkeypatch):
    hub = make_hub(tmp_path, owner={"open_hour": 0, "close_hour": 24})
    other = "10.0.0.99"
    _old_timed_session(hub, RIG, "Alex")
    _old_timed_session(hub, other, "Sam")
    hub.started_at -= AUTO_END_IDLE_S + 1
    real = hub.auto_end_reason

    def reason(ip, session, now):
        if ip == RIG:
            raise RuntimeError("boom")
        return real(ip, session, now)
    monkeypatch.setattr(hub, "auto_end_reason", reason)
    assert [n["driver"] for n in hub.auto_end_sessions()] == ["Sam"]
    assert hub.drivers.get(RIG) is not None             # tried again on the next check


def test_ending_the_same_session_twice_makes_one_card(tmp_path, monkeypatch):
    hub = make_hub(tmp_path)
    made = []

    def fake_card(ip, session):
        made.append(session.name)
        return {"token": "t", "url": "u", "driver": session.name}
    monkeypatch.setattr(hub, "_make_card", fake_card)
    session = hub.drivers.assign(RIG, "Alex")
    first = hub.end_session(RIG, session)
    again = hub.end_session(RIG, session)              # staff End arriving after the automatic end
    assert first is again and made == ["Alex"]
    assert hub.end_session(RIG) is None                 # nothing open: no error, no card
    assert hub.session_card(RIG, session) is first      # the "next driver" path doesn't make a second one


def test_staff_end_after_auto_end_gets_the_same_card(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from simtelemetry.api.app import create_app
    from f1_helpers import STAFF, staff_ready
    hub = make_hub(tmp_path)
    staff_ready(hub)
    hub.registry.see(RIG, time.monotonic(), "2025", None)
    made = []

    def fake_card(ip, session):
        made.append(session.name)
        return {"token": "tok", "url": "http://x/card/tok", "driver": session.name}
    monkeypatch.setattr(hub, "_make_card", fake_card)
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"), headers=STAFF)
    session, start = started(hub)
    real_get = hub.drivers.get
    calls = {"n": 0}

    def get_then_auto_end(ip):                          # the staff request reads the session, then auto-end wins
        got = real_get(ip)
        calls["n"] += 1
        if calls["n"] == 1:
            wall(hub, start + dt.timedelta(days=1))
            hub.auto_end_sessions()
        return got
    monkeypatch.setattr(hub.drivers, "get", get_then_auto_end)
    r = client.delete(f"/api/staff/rigs/{RIG}/driver").json()
    assert made == ["Alex"] and r["card"]["token"] == "tok" and r["card_note"] is None
