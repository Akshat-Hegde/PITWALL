"""Final Classification (packet 8): decoded for the player car; RaceFinished only for race sessions."""

import pytest

from simtelemetry.adapters.f1.adapter import F1Adapter
from simtelemetry.adapters.f1.packets import FinalClassification
from simtelemetry.core.adapter import RaceFinished
from simtelemetry.adapters.f1.sizes import DOCUMENTED_SIZES, PacketId

from f1_helpers import decode_packet, final_classification_packet, session_packet

BOTH = pytest.mark.parametrize("fmt", [2025, 2026])
SRC = "10.0.0.5"
PLAYER = dict(position=4, laps=57, grid=9, points=12, pits=2, status=3, reason=2, best_ms=91234,
              total_s=5400.5, pen_s=5)


def feed(adapter, pkt, source=SRC):
    checked = adapter.check(bytes(pkt), source)
    assert checked.ok, checked.reason
    return adapter.decode(checked, bytes(pkt), source)


def run(fmt, session_type, **car):
    adapter = F1Adapter()
    feed(adapter, session_packet(fmt, session_type))
    return feed(adapter, final_classification_packet(fmt, cars={3: {**PLAYER, **car}}))


def test_sizes_are_the_documented_ones():
    assert DOCUMENTED_SIZES[2025][PacketId.FINAL_CLASSIFICATION] == 1042
    assert DOCUMENTED_SIZES[2026][PacketId.FINAL_CLASSIFICATION] == 1134
    assert len(final_classification_packet(2025)) == 1042
    assert len(final_classification_packet(2026)) == 1134


@BOTH
def test_decodes_player_car_only(fmt):
    p = decode_packet(final_classification_packet(fmt, cars={3: PLAYER}))
    assert isinstance(p, FinalClassification)
    assert (p.position, p.num_laps, p.grid_position, p.result_status, p.best_lap_time_ms) == (4, 57, 9, 3, 91234)
    assert (p.total_race_time_s, p.penalties_time_s, p.num_cars) == (5400.5, 5, 20)


@BOTH
def test_race_emits_one_race_finished(fmt):
    results = run(fmt, 15).race_results
    assert results == [RaceFinished(track_key="F1:7", session_type="Race", session_uid="deadbeef12345678",
                                    position=4, grid_position=9, laps=57, best_lap_ms=91234,
                                    total_time_s=5405.5, penalties_s=5, status="finished", num_cars=20)]


@pytest.mark.parametrize("stype,name", [(16, "Race 2"), (17, "Race 3")])
def test_other_race_types(stype, name):
    assert run(2025, stype).race_results[0].session_type == name


@pytest.mark.parametrize("stype", [1, 4, 5, 8, 10, 14, 18, 0])
def test_non_race_sessions_emit_nothing(stype):
    assert run(2025, stype).race_results == []


def test_no_session_packet_yet_emits_nothing():
    adapter = F1Adapter()
    r = feed(adapter, final_classification_packet(2025, cars={3: PLAYER}))
    assert r.race_results == []


def test_zero_best_lap_is_none_and_zero_time_is_none():
    r = run(2025, 15, best_ms=0, total_s=0.0, pen_s=0).race_results[0]
    assert r.best_lap_ms is None and r.total_time_s is None


def test_grid_zero_is_none():
    assert run(2025, 15, grid=0).race_results[0].grid_position is None


@pytest.mark.parametrize("code,name", [(0, "invalid"), (1, "inactive"), (2, "active"), (3, "finished"),
                                       (4, "dnf"), (5, "dsq"), (6, "not_classified"), (7, "retired")])
def test_status_mapping(code, name):
    assert run(2025, 15, status=code).race_results[0].status == name


def test_unknown_status_is_invalid():
    assert run(2025, 15, status=99).race_results[0].status == "invalid"


def test_no_player_car_emits_nothing():
    adapter = F1Adapter()
    feed(adapter, session_packet(2025, 15))
    assert feed(adapter, final_classification_packet(2025, player=255)).race_results == []
