"""Track outline: from any complete lap path (valid or not, no flashback), refined by later laps; bundled files."""

from __future__ import annotations

import json
import math

from simtelemetry.__main__ import main
from simtelemetry.core.laps import OUTLINE_MAX_LAPS, LapBook, LapContext, LapRecord, Trace
from simtelemetry.core.store import LapStore
from simtelemetry.core.tracks import file_name, load_bundled, save_bundled

LENGTH = 3000.0
CTX = LapContext(rig_name="Rig 1", driver="Maya", track_key="F1:7", track_name="Silverstone", session_id="s",
                 track_length_m=LENGTH, sector_starts_m=(0.0, 1000.0, 2000.0))


def circle_trace(lap: int, radius_offset: float = 0.0, start: float = 5.0, end: float = LENGTH - 10) -> Trace:
    trace = Trace(lap)
    radius = LENGTH / (2 * math.pi)
    for i in range(301):
        d = start + (end - start) * i / 300
        a = 2 * math.pi * d / LENGTH
        trace.add(d, round(d * 30), (radius + radius_offset) * math.cos(a), (radius + radius_offset) * math.sin(a))
    return trace


def lap(trace: Trace, valid: bool = True, number: int = 1) -> LapRecord:
    return LapRecord(rig_id="10.0.0.1", rig_name="Rig 1", driver="Maya", track_key="F1:7", track_name="Silverstone",
                     session_id="s", lap_number=number, lap_ms=90000, sectors_ms=None, valid=valid, out_lap=False,
                     tyre=None, personal_best=False, session_best=False, completed_at=1, trace=trace)


def test_an_invalid_lap_still_draws_the_outline():
    book = LapBook()
    book._learn_outline(lap(circle_trace(1), valid=False), CTX)
    outline = book.outlines["F1:7"]
    assert (outline["source"], outline["laps"]) == ("laps", 1)
    assert len(outline["points"]) == LENGTH / 6 and outline["sector_starts"] == [0, 167, 333]
    assert book.messages[-1][1] == "track_outline"


def test_incomplete_or_flashback_laps_are_not_used():
    book = LapBook()
    book._learn_outline(lap(circle_trace(1, end=LENGTH / 2)), CTX)   # half a lap
    book._learn_outline(lap(circle_trace(1, start=300)), CTX)        # joined late
    flashback = circle_trace(1)
    flashback.cut_to(LENGTH)                                         # a flashback anywhere in the lap
    book._learn_outline(lap(flashback), CTX)
    assert "F1:7" not in book.outlines


def test_later_laps_refine_the_outline_then_stop():
    book = LapBook()
    book._learn_outline(lap(circle_trace(1, radius_offset=+4)), CTX)
    book._learn_outline(lap(circle_trace(2, radius_offset=-4), number=2), CTX)
    outline = book.outlines["F1:7"]
    radius = LENGTH / (2 * math.pi)
    assert outline["laps"] == 2
    assert all(abs(math.hypot(x, z) - radius) < 0.5 for x, z in outline["points"])   # averaged to the middle
    book._learn_outline(lap(circle_trace(3, radius_offset=200), number=3), CTX)       # wrong way / big cut: ignored
    assert book.outlines["F1:7"]["laps"] == 2
    for n in range(4, 4 + OUTLINE_MAX_LAPS):
        book._learn_outline(lap(circle_trace(n), number=n), CTX)
    assert book.outlines["F1:7"]["laps"] == OUTLINE_MAX_LAPS


def test_bundled_outline_wins_and_is_never_replaced(tmp_path):
    bundled = {"F1:7": {"track_key": "F1:7", "track_name": "Silverstone", "points": [[0, 0], [5, 5], [9, 0]],
                        "source": "bundled"}}
    book = LapBook(bundled_outlines=bundled, outline_display={"flip_x": True, "flip_z": False, "rotate_deg": 0})
    book._learn_outline(lap(circle_trace(1)), CTX)
    assert book.outlines["F1:7"]["points"] == [[0, 0], [5, 5], [9, 0]]
    assert book.outlines["F1:7"]["display"]["flip_x"] is True


def test_save_outline_command_writes_a_bundled_track_file(tmp_path, capsys):
    store = LapStore(tmp_path / "data" / "laps.db")
    book = LapBook(store=store)
    book._learn_outline(lap(circle_trace(1)), CTX)
    store.close()
    out = tmp_path / "tracks"
    assert main(["save-outline", "--data-dir", str(tmp_path / "data")]) == 0
    assert "F1:7" in capsys.readouterr().out
    assert main(["save-outline", "silverstone", "--data-dir", str(tmp_path / "data"), "--out", str(out)]) == 0
    saved = json.loads((out / file_name("F1:7")).read_text(encoding="utf-8"))
    assert saved["track_key"] == "F1:7" and len(saved["points"]) == 500 and "display" not in saved
    assert load_bundled(out)["F1:7"]["source"] == "bundled"
    assert main(["save-outline", "Monza", "--data-dir", str(tmp_path / "data"), "--out", str(out)]) == 2


def test_broken_bundled_files_are_skipped(tmp_path):
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    save_bundled({"track_key": "F1:10", "track_name": "Spa", "points": [[0, 0], [1, 1], [2, 0]]}, tmp_path)
    assert list(load_bundled(tmp_path)) == ["F1:10"]
