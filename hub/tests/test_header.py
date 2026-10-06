import pytest

from simtelemetry.adapters.f1.header import HEADER_SIZE, HEADER_STRUCT, parse_header

from f1_helpers import make_header


def test_header_is_29_bytes():
    assert HEADER_SIZE == 29
    assert HEADER_STRUCT.size == 29


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_parse_header_fields(fmt):
    raw = make_header(fmt, 6, session_uid=0x0102030405060708, session_time=12.5,
                      frame=100, overall_frame=101, player=3, secondary=255,
                      game_year=fmt % 100, major=1, minor=7, version=1)
    assert len(raw) == 29
    h = parse_header(raw)
    assert h.packet_format == fmt
    assert h.game_year == fmt % 100
    assert (h.game_major_version, h.game_minor_version, h.packet_version) == (1, 7, 1)
    assert h.packet_id == 6
    assert h.session_uid == 0x0102030405060708
    assert h.session_time == 12.5
    assert (h.frame_identifier, h.overall_frame_identifier) == (100, 101)
    assert (h.player_car_index, h.secondary_player_car_index) == (3, 255)
