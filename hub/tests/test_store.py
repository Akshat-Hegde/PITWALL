"""SQLite lap store: persistence across hub restarts, period boards, retractions, outlines."""

from __future__ import annotations

import datetime as dt

import pytest

from simtelemetry.config import AppConfig
from simtelemetry.core.laps import LapBook, LapCompleted, LapContext, LapRetracted
from simtelemetry.core.store import LapStore, period_start

# Wednesday 2026-10-07 21:30 local time
NOW = dt.datetime(2026, 10, 7, 21, 30)


def ctx(driver="Akshat", rig="Rig 1", track="F1:7", session="s1"):
    return LapContext(rig_name=rig, driver=driver, track_key=track, track_name="Silverstone", session_id=session,
                      tyre={"compound": "soft", "label": "C3", "age_laps": 2})


def lap(n, ms, valid=True, out_lap=False):
    return LapCompleted(n, 0.0, ms, (28000, 33000, ms - 61000), valid, out_lap, "test")


def at(when: dt.datetime):
    return lambda: when.timestamp()


def test_period_starts():
    assert period_start("today", NOW) == dt.datetime(2026, 10, 7)
    assert period_start("week", NOW) == dt.datetime(2026, 10, 5)            # Monday
    assert period_start("all_time", NOW) is None
    # Day starting at 05:00: 02:00 on Thursday still belongs to Wednesday.
    late = dt.datetime(2026, 10, 8, 2, 0)
    assert period_start("today", late, day_start_hour=5) == dt.datetime(2026, 10, 7, 5)
    assert period_start("week", dt.datetime(2026, 10, 5, 3, 0), day_start_hour=5) == dt.datetime(2026, 9, 28, 5)
    with pytest.raises(ValueError):
        period_start("month", NOW)


def test_boards_survive_a_restart_and_split_by_period(tmp_path):
    db = tmp_path / "laps.db"
    last_week = NOW - dt.timedelta(days=7)
    yesterday = NOW - dt.timedelta(days=1)
    book = LapBook(clock=at(last_week), store=LapStore(db))
    book.update("A", ctx("Old Fast"), None, [lap(2, 86000)])
    book.store.close()
    book = LapBook(clock=at(yesterday), store=LapStore(db))
    book.update("A", ctx("Monday Guy"), None, [lap(2, 87000)])
    book.update("A", ctx("Akshat"), None, [lap(2, 90000)])
    book.store.close()

    book = LapBook(clock=at(NOW), store=LapStore(db))                     # hub restarted today
    book.update("B", ctx("Akshat", "Rig 2"), None, [lap(3, 89000), lap(4, 88500, valid=False),
                                                    lap(1, 80000, out_lap=True)])
    boards = {b["period"]: b for b in book.boards("F1:7")}
    assert [(e["driver"], e["lap_ms"]) for e in boards["today"]["entries"]] == [("Akshat", 89000)]
    assert [(e["driver"], e["lap_ms"]) for e in boards["week"]["entries"]] == \
        [("Monday Guy", 87000), ("Akshat", 89000)]   # Akshat's best this week; invalid/out laps ignored
    assert [(e["rank"], e["driver"], e["gap_ms"]) for e in boards["all_time"]["entries"]] == \
        [(1, "Old Fast", 0), (2, "Monday Guy", 1000), (3, "Akshat", 3000)]
    entry = boards["today"]["entries"][0]
    assert entry["rig_name"] == "Rig 2" and entry["sectors_ms"] == [28000, 33000, 28000]
    assert entry["tyre"] == {"compound": "soft", "label": "C3", "age_laps": 2}
    assert boards["today"]["since"] == round(dt.datetime(2026, 10, 7).timestamp() * 1000)
    assert boards["all_time"]["since"] is None and boards["all_time"]["track_name"] == "Silverstone"
    assert book.store.count() == 6
    book.store.close()


def test_retracted_lap_is_deleted_from_the_database(tmp_path):
    store = LapStore(tmp_path / "laps.db")
    book = LapBook(clock=at(NOW), store=store)
    book.update("A", ctx(), None, [lap(2, 90000), lap(3, 88000)])
    book.update("A", ctx(), None, [LapRetracted(3, 0.0, "flashback")])
    assert store.count() == 1
    assert [e["lap_ms"] for e in book.board("F1:7", "all_time", None)["entries"]] == [90000]
    store.close()


def test_outlines_are_stored_and_use_the_current_map_config(tmp_path):
    store = LapStore(tmp_path / "laps.db")
    outline = {"track_key": "F1:7", "track_name": "Silverstone", "points": [[0, 0], [1, 1], [2, 0]],
               "source": "first_valid_lap", "sector_starts": None,
               "display": {"flip_x": False, "flip_z": False, "rotate_deg": 0}}
    store.save_outline(outline, 1)
    store.close()
    book = LapBook(store=LapStore(tmp_path / "laps.db"),
                   outline_display={"flip_x": False, "flip_z": True, "rotate_deg": 90})
    assert book.outlines["F1:7"]["points"] == [[0, 0], [1, 1], [2, 0]]
    assert book.outlines["F1:7"]["display"] == {"flip_x": False, "flip_z": True, "rotate_deg": 90}
    book.store.close()


def test_hub_cli_creates_the_database(tmp_path):
    from simtelemetry.__main__ import main
    assert main(["listen", "--data-dir", str(tmp_path), "--duration", "0.2", "--port", "0", "--no-record"]) == 0
    assert (tmp_path / "laps.db").is_file()


def test_day_start_hour_config():
    assert AppConfig(leaderboard={"day_start_hour": 5}).leaderboard.day_start_hour == 5
    with pytest.raises(Exception):
        AppConfig(leaderboard={"day_start_hour": 24})


def test_replay_keeps_laps_out_of_the_database_unless_asked(tmp_path):
    from simtelemetry.__main__ import main
    from simtelemetry.tools.recorder import Recorder
    from test_feed import drive_full_lap

    rec = Recorder(tmp_path / "rec")
    rec.start()
    for i, (ip, p) in enumerate(drive_full_lap("192.168.1.21", 0x11, 88123, b"Akshat", steps=80)):
        rec.write(1000.0 + i * 0.001, ip, p)
    rec.close()
    args = ["replay", str(rec.current_path), "--speed", "0", "--no-api", "--quiet", "--data-dir", str(tmp_path)]
    assert main(args) == 0
    assert not (tmp_path / "laps.db").exists()
    assert main(args + ["--save-laps"]) == 0
    store = LapStore(tmp_path / "laps.db")
    assert store.count() == 1 and store.board("F1:7", None)[0]["lap_ms"] == 88123
    store.close()
