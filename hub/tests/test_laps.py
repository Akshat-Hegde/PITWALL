"""Lap tracking: F1 tracker scenarios (one per docs/LAP_ASSUMPTIONS.md rule) and the LapBook."""

from __future__ import annotations

import logging

import pytest

from simtelemetry.adapters.f1.header import PacketHeader
from simtelemetry.adapters.f1.laps import FLASHBACK_WINDOW_PACKETS, HISTORY_WAIT_S, F1LapTracker
from simtelemetry.adapters.f1.packets import Event, FlashbackDetails, LapData, LapHistory, SessionHistory
from simtelemetry.adapters.f1.tyres import visual_compound
from simtelemetry.core.laps import (
    HistoryUpdate,
    LapBook,
    LapCompleted,
    LapContext,
    LapInvalidated,
    LapReset,
    LapRetracted,
    LapStarted,
    LiveLap,
)

UID = 0xABC


def header(t: float, uid: int = UID, pid: int = 2) -> PacketHeader:
    return PacketHeader(2025, 25, 1, 0, 1, pid, uid, t, int(t * 60), int(t * 60), 0, 255)


class Game:
    """Feeds a tracker with hand-built packets, like one rig's game would."""

    def __init__(self) -> None:
        self.tracker = F1LapTracker()
        self.t = 100.0
        self.events: list = []

    def feed(self, packet):
        new = self.tracker.on_packet(packet, packet.header.session_uid)
        self.events += new
        return new

    def lap_data(self, lap, dist=500.0, cur_ms=30000, last_ms=0, sector=0, s1=0, s2=0, invalid=False,
                 status=1, pit=0, dt=0.05, uid=UID):
        self.t += dt
        return self.feed(LapData(header(self.t, uid), last_ms, cur_ms, s1, s2, 0, 0, dist, dist, 1, lap, pit,
                                 sector, invalid, status, 2, 255, 255))

    def history(self, laps, dt=0.05, uid=UID):
        """laps: list of (lap_ms, s1, s2, s3, valid); the last entry is the lap in progress."""
        self.t += dt
        slots = tuple(LapHistory(ms, a, b, c, v, v, v, v) for ms, a, b, c, v in laps)
        slots += tuple(LapHistory(0, 0, 0, 0, False, False, False, False) for _ in range(100 - len(slots)))
        return self.feed(SessionHistory(header(self.t, uid, 11), 0, len(laps), 0, 0, 0, 0, slots, ()))

    def flashback(self, dt=0.05):
        self.t += dt
        return self.feed(Event(header(self.t, pid=3), "FLBK", FlashbackDetails(1234, self.t - 5)))

    def wait(self, seconds, lap, **kw):
        """LapData packets at 20 Hz for this long."""
        for _ in range(int(seconds * 20)):
            self.lap_data(lap, **kw)


LAP2 = (88123, 28011, 33456, 26656, True)
OPEN = (0, 0, 0, 0, True)


def completed(events):
    return [e for e in events if isinstance(e, LapCompleted)]


def drive_lap_two(g: Game) -> None:
    """Out lap 1, flying lap 2 completed; LapData now on lap 3."""
    g.lap_data(1, dist=-50, status=3)
    g.lap_data(1, dist=4000, sector=2, s1=30000, s2=35000, status=3)
    g.lap_data(2, dist=1, cur_ms=10, last_ms=95000)
    g.history([(95000, 30000, 35000, 30000, True), OPEN])
    g.lap_data(2, dist=5000, cur_ms=87000, sector=2, s1=28011, s2=33456)
    g.lap_data(3, dist=2, cur_ms=20, last_ms=88123)


# --- F1 tracker ---------------------------------------------------------------------------------

def test_completed_laps_come_from_session_history():
    g = Game()
    drive_lap_two(g)
    assert [e.lap for e in completed(g.events)] == [1]  # lap 2 waits for its history entry [A2]
    new = g.history([(95000, 30000, 35000, 30000, True), LAP2, OPEN])
    (lap2,) = completed(new)
    assert (lap2.lap, lap2.lap_ms, lap2.sectors_ms, lap2.valid, lap2.source) == \
        (2, 88123, (28011, 33456, 26656), True, "session_history")
    assert lap2.out_lap is False
    out_lap = completed(g.events)[0]
    assert (out_lap.lap, out_lap.out_lap) == (1, True)  # status 3 when lap 1 started [A8]
    assert [e.lap for e in g.events if isinstance(e, LapStarted)] == [2, 3]
    # Repeats of the same history change nothing.
    assert g.history([(95000, 30000, 35000, 30000, True), LAP2, OPEN]) == []


def test_history_must_match_lap_data_last_lap_time():
    g = Game()
    drive_lap_two(g)
    # Entry for lap 2 still holds another time (stale or not updated yet): not used [A3].
    assert completed(g.history([(95000, 30000, 35000, 30000, True), (91000, 1, 2, 3, True), OPEN])) == []
    assert completed(g.history([(95000, 30000, 35000, 30000, True), LAP2, OPEN]))[0].lap_ms == 88123


def test_last_lap_time_settling_after_rollover_is_followed():
    g = Game()
    g.lap_data(1, status=1)
    g.lap_data(2, dist=1, last_ms=0)          # first packet of lap 2 hasn't updated last lap yet
    g.lap_data(2, dist=5, last_ms=88123)
    (lap1,) = completed(g.history([LAP2, OPEN]))
    assert lap1.lap_ms == 88123


def test_falls_back_to_lap_data_when_history_is_late_then_corrects():
    g = Game()
    drive_lap_two(g)
    g.wait(HISTORY_WAIT_S + 0.2, 3, last_ms=88123)
    fallback = [e for e in completed(g.events) if e.lap == 2]
    assert len(fallback) == 1
    assert (fallback[0].source, fallback[0].lap_ms, fallback[0].sectors_ms) == \
        ("lap_data_fallback", 88123, (28011, 33456, 26656))  # S3 = lap - S1 - S2 [A4]
    # History arrives with a different S3 split (rounding): retract and replace [A5].
    new = g.history([(95000, 30000, 35000, 30000, True), (88123, 28011, 33455, 26657, True), OPEN])
    assert [type(e) for e in new if not isinstance(e, HistoryUpdate)] == [LapRetracted, LapCompleted]
    assert completed(new)[0].sectors_ms == (28011, 33455, 26657)


def test_invalidation_is_reported_and_history_validity_wins():
    g = Game()
    g.lap_data(1, status=1)
    new = g.lap_data(1, invalid=True)
    assert [type(e) for e in new] == [LapInvalidated]
    assert g.lap_data(1, invalid=True) == []
    g.lap_data(2, last_ms=88123)
    (lap1,) = completed(g.history([(88123, 28011, 33456, 26656, False), OPEN]))
    assert lap1.valid is False


def test_flashback_within_a_lap_resets_without_changing_laps():
    g = Game()
    g.lap_data(2, dist=2000, cur_ms=30000)
    new = g.flashback()
    assert [(type(e), e.reason, e.lap) for e in new] == [(LapReset, "flashback", 2)]
    assert g.lap_data(2, dist=1500, cur_ms=25000) == []


def test_flashback_back_across_the_line_retracts_the_lap():
    g = Game()
    drive_lap_two(g)
    g.history([(95000, 30000, 35000, 30000, True), LAP2, OPEN])
    g.flashback()
    new = g.lap_data(2, dist=5800, cur_ms=87900)   # lap 2 in progress again [A6]
    assert [(type(e), e.reason) for e in new] == [(LapReset, "flashback")]
    new = g.history([(95000, 30000, 35000, 30000, True), OPEN])
    assert [(type(e), e.lap) for e in new if isinstance(e, LapRetracted)] == [(LapRetracted, 2)]
    # Lap 2 completed again, with a new time.
    g.lap_data(3, last_ms=88500)
    (again,) = completed(g.history([(95000, 30000, 35000, 30000, True), (88500, 28011, 33456, 27033, True), OPEN]))
    assert (again.lap, again.lap_ms) == (2, 88500)


def test_lap_decrease_long_after_a_flashback_is_a_restart():
    g = Game()
    g.lap_data(3)
    g.flashback()
    g.wait(FLASHBACK_WINDOW_PACKETS / 20 + 0.5, 3)
    new = g.lap_data(1)
    assert [(type(e), e.reason) for e in new] == [(LapReset, "lap_number_decreased")]


def test_time_trial_restart_starts_a_new_run():
    g = Game()
    drive_lap_two(g)
    g.history([(95000, 30000, 35000, 30000, True), LAP2, OPEN])
    new = g.lap_data(1, dist=-100, status=3)     # "restart lap": back to lap 1 [A7]
    assert [(type(e), e.reason) for e in new] == [(LapReset, "lap_number_decreased")]
    g.lap_data(2, last_ms=97000)
    # History still shows the previous run until the game updates it: lap 1's entry doesn't match.
    assert completed(g.history([(95000, 30000, 35000, 30000, True), LAP2, OPEN])) == []
    (lap1,) = completed(g.history([(97000, 31000, 35000, 31000, True), OPEN]))
    assert (lap1.lap, lap1.lap_ms, lap1.out_lap) == (1, 97000, True)


def test_new_session_resets_everything():
    g = Game()
    drive_lap_two(g)
    new = g.lap_data(1, uid=0xDEF)
    assert [(type(e), e.reason) for e in new] == [(LapReset, "session_changed")]
    assert g.tracker.emitted == {} and g.tracker.pending == {}


def test_laps_from_before_the_hub_started_are_not_reported():
    g = Game()
    g.lap_data(5, dist=1200)                       # hub starts mid-session [A9]
    old = [(90000 + i, 30000, 30000, 30000 + i, True) for i in range(4)]
    assert completed(g.history(old + [OPEN])) == []
    g.lap_data(6, last_ms=88123)
    (lap5,) = completed(g.history(old + [LAP2, OPEN]))
    assert lap5.lap == 5


def test_history_updates_are_reported_for_debugging():
    g = Game()
    g.lap_data(1)
    (update,) = g.history([OPEN])
    assert isinstance(update, HistoryUpdate) and update.num_laps == 1 and update.changed == (1,)
    assert g.history([OPEN]) == []


def test_live_lap():
    g = Game()
    g.lap_data(2, dist=3000, cur_ms=50000, last_ms=88123, sector=2, s1=28011, s2=33456, invalid=True)
    live = g.tracker.live()
    assert live == LiveLap(2, 3000.0, 50000, False, 2, 28011, 33456, 88123, False)
    g.lap_data(3, dist=10, cur_ms=100, last_ms=88000, sector=0, s1=28011, s2=33456)
    assert (g.tracker.live().sector1_ms, g.tracker.live().sector2_ms) == (None, None)  # stale values hidden


# --- LapBook ------------------------------------------------------------------------------------

def ctx(driver="Akshat", rig="Rig 1", track="F1:7", session="s1"):
    return LapContext(rig_name=rig, driver=driver, track_key=track, track_name="Silverstone", session_id=session)


def lap(n, ms, sectors=None, valid=True, out_lap=False):
    return LapCompleted(n, 0.0, ms, sectors, valid, out_lap, "test")


def test_ratings_and_bests():
    book = LapBook(clock=lambda: 1_791_302_400.0)
    (first,) = book.update("A", ctx(), None, [lap(2, 90000, (30000, 30000, 30000))])
    assert first.sector_ratings == ("session_best",) * 3
    assert first.personal_best and first.session_best
    (b,) = book.update("B", ctx("Guest", "Rig 2"), None, [lap(2, 91000, (29000, 31000, 31000))])
    assert b.sector_ratings == ("session_best", "personal_best", "personal_best")
    assert b.personal_best and not b.session_best
    (b2,) = book.update("B", ctx("Guest", "Rig 2"), None, [lap(3, 92000, (29500, 30500, 32000))])
    assert b2.sector_ratings == ("normal", "personal_best", "normal")  # S1 slower than Guest's 29.000
    assert book.session_best("F1:7").lap_ms == 90000
    assert book.rig_best("B", "F1:7").lap_ms == 91000
    assert [r.driver for r in book.leaderboard("F1:7")] == ["Akshat", "Guest"]
    assert first.completed_at == 1_791_302_400_000


def test_invalid_and_out_laps_dont_count():
    book = LapBook()
    (invalid,) = book.update("A", ctx(), None, [lap(2, 80000, (1, 2, 3), valid=False)])
    (out,) = book.update("A", ctx(), None, [lap(1, 79000, (1, 2, 3), out_lap=True)])
    assert invalid.sector_ratings == (None, None, None) and not invalid.personal_best
    assert not out.counted
    assert book.session_best("F1:7") is None and book.leaderboard("F1:7") == []
    assert len(book.recent) == 2


def test_personal_bests_follow_the_driver_across_rigs():
    book = LapBook()
    book.update("A", ctx("Akshat"), None, [lap(2, 90000)])
    (moved,) = book.update("B", ctx("akshat", "Rig 2"), None, [lap(2, 91000)])
    assert not moved.personal_best           # same driver (case-insensitive) on another rig
    assert book.rig_best("B", "F1:7").lap_ms == 91000
    assert len(book.leaderboard("F1:7")) == 1


def test_retracted_lap_is_removed_and_bests_recomputed():
    book = LapBook()
    book.update("A", ctx(), None, [lap(2, 90000)])
    book.update("A", ctx(), None, [lap(3, 88000)])
    assert book.session_best("F1:7").lap_ms == 88000
    book.update("A", ctx(), None, [LapRetracted(3, 0.0, "test")])
    assert book.session_best("F1:7").lap_ms == 90000
    assert [r.lap_number for r in book.recent] == [2]


def test_live_view_rates_sectors_without_changing_bests():
    book = LapBook()
    book.update("A", ctx(), None, [lap(2, 90000, (30000, 30000, 30000))])
    live = LiveLap(3, 4000.0, 62000, True, 2, 29000, 31000, 90000)
    book.update("A", ctx(), live, [])
    view = book.live_view("A")
    assert view["sectors"] == [{"ms": 29000, "rating": "session_best"}, {"ms": 31000, "rating": "normal"}, None]
    assert view["last_sectors"][0] == {"ms": 30000, "rating": "session_best"}
    assert book.session_best("F1:7").sectors_ms == (30000, 30000, 30000)  # unchanged
    book.update("A", ctx(), LiveLap(3, 4100.0, 62100, False, 2, 29000, 31000, 90000), [])
    assert book.live_view("A")["sectors"][0] == {"ms": 29000, "rating": None}  # invalid: unrated


def test_lap_without_known_track_is_not_recorded(caplog):
    book = LapBook()
    assert book.update("A", ctx(track=None), None, [lap(2, 90000)]) == []
    assert "before its track was known" in caplog.text


def test_lap_debug_lines(caplog):
    book = LapBook()
    with caplog.at_level(logging.INFO, logger="simtelemetry.lapdebug"):
        book.update("192.168.1.21", ctx(), None, [LapReset("flashback", 12.5, 3, "to frame 99"),
                                                  lap(2, 88123, (28011, 33456, 26656))])
    lines = [r.getMessage() for r in caplog.records if r.name == "simtelemetry.lapdebug"]
    assert lines[0] == "rig=192.168.1.21 event=reset game_t=12.500 reason=flashback lap=3 detail=to frame 99"
    assert "event=lap_completed" in lines[1] and "lap_ms=88123 (1:28.123)" in lines[1]
    assert lines[2].startswith("rig=192.168.1.21 recorded lap=2 time=1:28.123 valid=True")


def test_tyre_compound_helper_still_used():
    assert visual_compound(16).label == "soft"


# --- end to end: packet bytes -> recording -> replay --lap-debug -------------------------------

def lap_data_bytes(fmt, uid, t, lap, dist, cur_ms, last_ms=0, sector=0, s1=0, s2=0, status=1):
    from simtelemetry.adapters.f1.formats import FORMATS
    from simtelemetry.adapters.f1.sizes import PacketId
    from test_feed import car_packet
    pkt = bytearray(car_packet(fmt, PacketId.LAP_DATA, "m_lapData", FORMATS[fmt].lap_data, uid,
                               m_lastLapTimeInMS=last_ms, m_currentLapTimeInMS=cur_ms, m_lapDistance=dist,
                               m_currentLapNum=lap, m_sector=sector, m_driverStatus=status,
                               m_sector1TimeMSPart=s1 % 60000, m_sector1TimeMinutesPart=s1 // 60000,
                               m_sector2TimeMSPart=s2 % 60000, m_sector2TimeMinutesPart=s2 // 60000))
    import struct
    struct.pack_into("<f", pkt, 15, t)  # header m_sessionTime
    return bytes(pkt)


def history_bytes(fmt, uid, t, laps):
    import struct
    from simtelemetry.adapters.f1.formats import FORMATS
    from simtelemetry.adapters.f1.sizes import PacketId
    from f1_helpers import blank_packet
    from test_feed import PLAYER, set_fields
    layout = FORMATS[fmt].packets[PacketId.SESSION_HISTORY]
    entry = FORMATS[fmt].lap_history
    pkt = blank_packet(fmt, PacketId.SESSION_HISTORY, player=PLAYER, session_uid=uid)
    struct.pack_into("<f", pkt, 15, t)
    set_fields(pkt, layout, 0, m_carIdx=PLAYER, m_numLaps=len(laps))
    for i, (ms, s1, s2, s3, valid) in enumerate(laps):
        set_fields(pkt, entry, layout.offset_of("m_lapHistoryData") + i * entry.size,
                   m_lapTimeInMS=ms, m_sector1TimeMSPart=s1, m_sector2TimeMSPart=s2, m_sector3TimeMSPart=s3,
                   m_lapValidBitFlags=0x0F if valid else 0x00)
    return bytes(pkt)


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_replay_with_lap_debug(tmp_path, fmt):
    from simtelemetry.__main__ import main
    from simtelemetry.tools.recorder import Recorder
    from test_feed import participants, session

    uid, ip = 0x77, "192.168.1.21"
    packets = [session(fmt, uid), participants(fmt, uid, b"Akshat"),
               lap_data_bytes(fmt, uid, 10.0, 1, 5000, 88000, sector=2, s1=28011, s2=33456),
               lap_data_bytes(fmt, uid, 10.1, 2, 3, 30, last_ms=88123),
               history_bytes(fmt, uid, 10.2, [(88123, 28011, 33456, 26656, True), (0, 0, 0, 0, True)])]
    rec = Recorder(tmp_path / "rec")
    rec.start()
    for i, p in enumerate(packets):
        rec.write(1000.0 + i * 0.01, ip, p)
    rec.close()

    code = main(["replay", str(rec.current_path), "--speed", "0", "--no-api", "--quiet", "--lap-debug",
                 "--data-dir", str(tmp_path)])
    assert code == 0
    (log_file,) = (tmp_path / "logs").glob("lap-debug-*.log")
    text = log_file.read_text(encoding="utf-8")
    assert "event=lap_started game_t=10.100 lap=2" in text
    assert "event=session_history_update" in text
    assert "event=lap_completed game_t=10.200 lap=1 lap_ms=88123 (1:28.123) sectors_ms=(28011, 33456, 26656) " \
           "valid=True out_lap=False source=session_history" in text
    assert "recorded lap=1 time=1:28.123 valid=True" in text


def test_no_lap_debug_file_without_the_flag(tmp_path):
    from simtelemetry.logging_setup import setup_logging, teardown_logging
    assert setup_logging(tmp_path, lap_debug=False) is None
    teardown_logging()
    assert not list(tmp_path.glob("lap-debug-*.log"))
