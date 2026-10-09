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


# --- sector colours: purple = fastest today (database), green = own best this session -----------

def sectors_lap(n, s1, s2, s3, valid=True):
    return LapCompleted(n, 0.0, s1 + s2 + s3, (s1, s2, s3), valid, False, "test")


def test_purple_is_fastest_today_from_the_database(tmp_path):
    db = tmp_path / "laps.db"
    yesterday = LapBook(clock=at(NOW - dt.timedelta(days=1)), store=LapStore(db))
    yesterday.update("A", ctx("Legend"), None, [sectors_lap(2, 25000, 30000, 25000)])  # faster, but yesterday
    yesterday.store.close()
    morning = LapBook(clock=at(NOW - dt.timedelta(hours=3)), store=LapStore(db))
    morning.update("A", ctx("Early Bird", session="m"), None, [sectors_lap(2, 28000, 33000, 27000)])
    morning.store.close()

    book = LapBook(clock=at(NOW), store=LapStore(db))                  # hub restarted since the morning
    (lap,) = book.update("B", ctx("Akshat", "Rig 2", session="e"), None, [sectors_lap(3, 27900, 33500, 26000)])
    # S1 beats this morning's 28.000 -> purple; S2 slower than 33.000 but Akshat's first lap -> green;
    # S3 beats 27.000 -> purple. Yesterday's faster sectors don't count.
    assert lap.sector_ratings == ("session_best", "personal_best", "session_best")
    assert book.today_sector_bests("F1:7") == [27900, 33000, 26000]
    book.store.close()


def test_green_is_own_best_in_the_current_session(tmp_path):
    book = LapBook(clock=at(NOW), store=LapStore(tmp_path / "laps.db"))
    book.update("A", ctx("Fast Friend", session="s1"), None, [sectors_lap(2, 28000, 33000, 27000)])
    # Akshat's earlier game session on the same rig had quicker sectors than tonight's laps below.
    book.update("A", ctx("Akshat", session="s0"), None, [sectors_lap(2, 28500, 33500, 27500)])
    (first,) = book.update("A", ctx("Akshat", session="s2"), None, [sectors_lap(2, 29000, 34000, 28000)])
    assert first.sector_ratings == ("personal_best",) * 3        # first lap of the new session: own best
    (second,) = book.update("A", ctx("Akshat", session="s2"), None, [sectors_lap(3, 28900, 34100, 28000)])
    assert second.sector_ratings == ("personal_best", "normal", "personal_best")  # S2 slower, S3 equal
    # Another driver on the same rig in the same game session has their own bests.
    (guest,) = book.update("A", ctx("Guest", session="s2"), None, [sectors_lap(4, 30000, 35000, 29000)])
    assert guest.sector_ratings == ("personal_best",) * 3
    # Invalid laps are unrated and don't set bests.
    (cut,) = book.update("A", ctx("Akshat", session="s2"), None, [sectors_lap(5, 20000, 20000, 20000, valid=False)])
    assert cut.sector_ratings == (None, None, None)
    assert book.own_sector_bests("A", "s2", "driver:akshat", "F1:7") == [28900, 34000, 28000]
    book.store.close()


def test_live_sectors_and_retraction_use_the_same_bests(tmp_path):
    from simtelemetry.core.laps import LiveLap
    book = LapBook(clock=at(NOW), store=LapStore(tmp_path / "laps.db"))
    book.update("A", ctx("Fast Friend", session="s1"), None, [sectors_lap(2, 28000, 33000, 27000)])
    book.update("B", ctx("Akshat", "Rig 2", session="s2"), None, [sectors_lap(2, 29000, 34000, 28000)])
    live = LiveLap(3, 4000.0, 62000, True, 2, 28500, 34500, 91000)
    book.update("B", ctx("Akshat", "Rig 2", session="s2"), live, [])
    ratings = [s["rating"] for s in book.live_view("B")["sectors"][:2]]
    assert ratings == ["personal_best", "normal"]                 # 28.5 < own 29.0; 34.5 > own 34.0
    # The friend's lap is withdrawn (flashback): Akshat's 28.5 is now the fastest S1 today.
    book.update("A", ctx("Fast Friend", session="s1"), None, [LapRetracted(2, 0.0, "flashback")])
    assert book.live_view("B")["sectors"][0]["rating"] == "session_best"
    book.store.close()


def test_new_day_resets_purple(tmp_path):
    clock = {"t": NOW}
    book = LapBook(clock=lambda: clock["t"].timestamp(), store=LapStore(tmp_path / "laps.db"))
    book.update("A", ctx(session="s1"), None, [sectors_lap(2, 28000, 33000, 27000)])
    assert book.today_sector_bests("F1:7") == [28000, 33000, 27000]
    clock["t"] = NOW + dt.timedelta(days=1)
    assert book.today_sector_bests("F1:7") == [None, None, None]
    book.store.close()
