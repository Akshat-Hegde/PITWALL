"""Head to head in the hub: traced laps -> speed trace, lap share, mini-sectors; persisted per track and day."""

from __future__ import annotations

from simtelemetry.core.feed import FeedBuilder, FeedConnection
from simtelemetry.core.laps import MINI_SECTORS, SPEED_BINS, LapBook, LapCompleted, LapContext, LiveLap, Trace, lap_analysis
from simtelemetry.core.store import LapStore

from test_drivers import RIG, client_with_rig
from test_feed import last_seen

LENGTH = 4800.0


def trace(lap: int, lap_ms: int, slow_from: float | None = None) -> Trace:
    """A lap at constant speed (slower after slow_from), with inputs: throttle flat out on half the lap."""
    tr = Trace(lap)
    weights = [1.1 if slow_from is not None and i * 10.0 >= slow_from else 1.0 for i in range(480)]
    unit = lap_ms / sum(weights)  # the steps add up to the lap time
    t = 0.0
    for i in range(0, 481):
        d = i * 10.0
        tr.add(d, round(t), d, 0.0, thr=1.0 if i % 2 else 0.5, brk=0.8 if i % 10 == 0 else 0.0, glat=2.0 if i % 4 == 0 else 0.3)
        t += unit * weights[i] if i < 480 else 0
    return tr


def drive(book: LapBook, rig: str, driver: str, n: int, lap_ms: int, **kw):
    ctx = LapContext(rig_name=rig, driver=driver, track_key="F1:7", track_name="Silverstone", session_id="s",
                     position=(0.0, 0.0), track_length_m=LENGTH)
    book.rig(rig).traces[n] = trace(n, lap_ms, **kw)
    book.update(rig, ctx, LiveLap(n + 1, 5.0, 100, True, 0, None, None, lap_ms),
                [LapCompleted(n, 0.0, lap_ms, (30000, 33000, lap_ms - 63000), True, False, "test")])


def test_lap_analysis_from_a_trace():
    a = lap_analysis(trace(2, 96000), LENGTH)
    assert len(a["speed"]) == SPEED_BINS and 175 < a["speed"][50] < 185   # 4.8 km in 96 s = 180 km/h
    assert a["share"] == {"full_throttle": 49.9, "heavy_braking": 10.2, "cornering": 25.2}
    assert lap_analysis(Trace(2), LENGTH) is None


def test_closest_pair_today_survives_a_restart(tmp_path):
    clock = lambda: 1_791_302_400.0
    book = LapBook(clock=clock, store=LapStore(tmp_path / "laps.db"))
    assert book.head_to_head("F1:7") is None
    drive(book, "A", "Maya", 2, 90000)
    assert book.head_to_head("F1:7") is None                          # one driver: nothing to compare
    drive(book, "B", "Kofi", 2, 96000)
    drive(book, "C", "Rosa", 2, 90500, slow_from=2400)
    drive(book, "A", "Maya", 3, 91000)                                # slower than her best: not kept
    h2h = book.head_to_head("F1:7")
    assert (h2h["a"]["driver"], h2h["b"]["driver"]) == ("Maya", "Rosa")
    assert h2h["a"]["lap_ms"] == 90000 and len(h2h["a"]["minis"]) == MINI_SECTORS
    assert h2h["a"]["share"]["full_throttle"] == 49.9

    restarted = LapBook(clock=clock, store=LapStore(tmp_path / "laps.db"))
    assert restarted.head_to_head("F1:7") == h2h                      # straight from the database


async def test_head_to_head_in_the_feed(tmp_path):
    hub, _ = await client_with_rig(tmp_path)
    conn = FeedConnection(FeedBuilder(hub))
    assert conn.start(last_seen(hub))["head_to_head"] is None
    drive(hub.laps, RIG, "Maya", 2, 90000)
    drive(hub.laps, "10.0.0.2", "Kofi", 2, 91000)
    (msg,) = [m for m in conn.tick(last_seen(hub)) if m["type"] == "head_to_head"]
    assert msg["head_to_head"]["a"]["driver"] == "Maya" and msg["head_to_head"]["track_key"] == "F1:7"
    assert not [m for m in conn.tick(last_seen(hub)) if m["type"] == "head_to_head"]   # sent once per change
