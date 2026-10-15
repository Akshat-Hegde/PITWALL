"""Opening hours that close after midnight, and the business day (K9)."""

import datetime as dt

import pytest
from pydantic import ValidationError

from simtelemetry.config import AppConfig
from simtelemetry.core.analytics import Analytics
from simtelemetry.core.hours import (auto_end_at, business_day, derived_day_start, hour_label, hours_problem,
                                     open_minutes)
from simtelemetry.core.settings import CafeSettings
from simtelemetry.core.store import LapStore, period_start


def at(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute)


def test_closing_after_midnight_is_the_next_day():
    assert hours_problem(10, 22) is None
    assert hours_problem(16, 2) is None          # closes at 02:00 the next day
    assert hours_problem(16, 0) is None          # midnight
    assert hours_problem(10, 24) is None
    assert hours_problem(16, 7) is not None      # 07:00 is too late to mean the next day
    assert hours_problem(10, 10) is not None
    assert hour_label(2, open_hour=16) == "02:00 (next day)" and hour_label(22, open_hour=10) == "22:00"


def test_day_start_is_derived_from_the_closing_hour():
    assert derived_day_start(10, 22) == 0
    assert derived_day_start(16, 2) == 2
    assert derived_day_start(16, 0) == 0
    assert AppConfig(owner={"open_hour": 16, "close_hour": 2}).day_start_hour == 2
    assert AppConfig().day_start_hour == 0
    # Set explicitly in hub.toml: that wins. 0 (the old starter file's value) still means automatic.
    assert AppConfig(owner={"open_hour": 16, "close_hour": 2}, leaderboard={"day_start_hour": 5}).day_start_hour == 5
    assert AppConfig(owner={"open_hour": 16, "close_hour": 2}, leaderboard={"day_start_hour": 0}).day_start_hour == 2


def test_hub_toml_and_settings_accept_closing_after_midnight():
    assert AppConfig(owner={"open_hour": 18, "close_hour": 3}).owner.close_hour == 3
    with pytest.raises(ValidationError):
        AppConfig(owner={"open_hour": 18, "close_hour": 9})
    s = CafeSettings(name="Late Laps", owner_pin="2468", staff_pin="1357", open_hour=18, close_hour=2)
    assert s.close_hour == 2
    with pytest.raises(ValidationError, match="after midnight"):
        CafeSettings(name="Late Laps", owner_pin="2468", open_hour=18, close_hour=9)


def test_open_minutes_wraps_past_midnight():
    assert open_minutes(10, 22) == 12 * 60
    assert open_minutes(16, 2) == 10 * 60
    assert open_minutes(16, 0) == 8 * 60


def test_today_board_keeps_a_late_lap_on_the_evening_before():
    # Opens 16:00, closes 02:00: a lap at 01:30 belongs to the day that started at 02:00 the day before.
    assert period_start("today", at(16, 1, 30), 2) == at(15, 2)
    assert business_day(at(16, 1, 30), 2) == dt.date(2026, 10, 15)
    assert business_day(at(16, 2, 30), 2) == dt.date(2026, 10, 16)


def test_auto_end_time():
    # Closes 22:00: a session that started in the afternoon ends at 22:00.
    assert auto_end_at(at(15, 14), 22, 0) == at(15, 22)
    # Started after closing time: ends when the next business day starts (midnight), not 22:00 tomorrow.
    assert auto_end_at(at(15, 22, 30), 22, 0) == at(16, 0)
    # Closes 02:00 (next day).
    assert auto_end_at(at(15, 20), 2, 2) == at(16, 2)
    assert auto_end_at(at(16, 1), 2, 2) == at(16, 2)


def test_analytics_utilisation_with_hours_past_midnight(tmp_path):
    store = LapStore(tmp_path / "laps.db")
    a = Analytics(store, day_start_hour=2, open_hour=16, close_hour=2,
                  clock=lambda: at(16, 1).timestamp())
    report = a.report(1)
    assert report["open_hours"] == [16, 2] and report["daily"][0]["date"] == "2026-10-15"
    store.close()


def test_setup_saves_hours_past_midnight_and_the_boards_follow(tmp_path):
    from test_setup_api import GOOD, _client as client_for
    hub, client, code = client_for(tmp_path)
    r = client.post("/api/setup", json={**GOOD, "staff_pin": "1357", "open_hour": 16, "close_hour": 2}, headers=code)
    assert r.status_code == 200, r.text
    assert (hub.config.owner.open_hour, hub.config.owner.close_hour) == (16, 2)
    assert hub.laps.day_start_hour == 2 and hub.competitions.day_start_hour == 2
    bad = client.post("/api/setup", json={**GOOD, "owner_pin": "2468", "open_hour": 16, "close_hour": 9},
                      headers={"X-Owner-Pin": "2468"})
    assert bad.status_code == 400 and "after midnight" in bad.json()["detail"]
