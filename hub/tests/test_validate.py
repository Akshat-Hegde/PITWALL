import logging

import pytest

from simtelemetry.adapters.f1.sizes import DOCUMENTED_SIZES, PacketId
from simtelemetry.adapters.f1.validate import Accepted, PacketGate, Rejected, Rejection, validate

from f1_helpers import make_header, make_packet

ALL_DOCUMENTED = [(fmt, pid, size) for fmt, table in DOCUMENTED_SIZES.items() for pid, size in table.items()]


@pytest.mark.parametrize("fmt,pid,size", ALL_DOCUMENTED)
def test_documented_size_accepted(fmt, pid, size):
    result = validate(make_packet(fmt, pid, size, player=5))
    assert isinstance(result, Accepted)
    assert result.packet_id is pid
    assert result.header.packet_format == fmt
    assert result.header.player_car_index == 5


@pytest.mark.parametrize("fmt,pid,size", ALL_DOCUMENTED)
@pytest.mark.parametrize("delta", [-1, +1])
def test_off_by_one_rejected(fmt, pid, size, delta):
    result = validate(make_packet(fmt, pid, size + delta))
    assert isinstance(result, Rejected)
    assert result.reason is Rejection.SIZE_MISMATCH
    assert result.expected_length == size
    assert result.length == size + delta


def test_2025_size_under_2026_format_rejected():
    # A 2025-sized Lap Data packet labelled as 2026 must not be accepted.
    result = validate(make_packet(2026, PacketId.LAP_DATA, DOCUMENTED_SIZES[2025][PacketId.LAP_DATA]))
    assert isinstance(result, Rejected) and result.reason is Rejection.SIZE_MISMATCH


@pytest.mark.parametrize("length", [0, 1, 28])
def test_too_short(length):
    result = validate(make_header(2025, 0)[:length])
    assert isinstance(result, Rejected) and result.reason is Rejection.TOO_SHORT


@pytest.mark.parametrize("fmt", [2023, 2024, 0, 65535])
def test_unsupported_format(fmt):
    result = validate(make_packet(fmt, 0, 1349))
    assert isinstance(result, Rejected) and result.reason is Rejection.UNSUPPORTED_FORMAT


def test_packet_16_unknown_in_2025():
    result = validate(make_packet(2025, 16, 269))
    assert isinstance(result, Rejected) and result.reason is Rejection.UNKNOWN_PACKET_ID


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_unknown_packet_id(fmt):
    result = validate(make_packet(fmt, 99, 100))
    assert isinstance(result, Rejected) and result.reason is Rejection.UNKNOWN_PACKET_ID


def test_gate_logs_each_distinct_rejection_once(caplog):
    gate = PacketGate()
    bad = make_packet(2025, PacketId.MOTION, 1000)
    with caplog.at_level(logging.DEBUG, logger="simtelemetry.adapters.f1.validate"):
        for _ in range(5):
            gate.check(bad, "192.168.1.10")
        gate.check(bad, "192.168.1.11")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "192.168.1.10" in warnings[0].getMessage()
    assert "documented size is 1349" in warnings[0].getMessage()
    assert sum(r.levelno == logging.DEBUG for r in caplog.records) == 4


def test_gate_does_not_log_accepted(caplog):
    gate = PacketGate()
    with caplog.at_level(logging.DEBUG, logger="simtelemetry.adapters.f1.validate"):
        assert isinstance(gate.check(make_packet(2026, PacketId.EVENT, 45), "10.0.0.2"), Accepted)
    assert not caplog.records
