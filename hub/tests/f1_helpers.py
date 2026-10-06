"""Test helpers: build packets with an independently written header pack."""

from __future__ import annotations

import struct
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"


def make_header(packet_format: int, packet_id: int, *, session_uid: int = 0xDEADBEEF12345678,
                session_time: float = 12.5, frame: int = 100, overall_frame: int = 101,
                player: int = 3, secondary: int = 255, game_year: int = 25,
                major: int = 1, minor: int = 7, version: int = 1) -> bytes:
    return (
        struct.pack("<H", packet_format)
        + bytes([game_year, major, minor, version, packet_id])
        + struct.pack("<Q", session_uid)
        + struct.pack("<f", session_time)
        + struct.pack("<I", frame)
        + struct.pack("<I", overall_frame)
        + bytes([player, secondary])
    )


def make_packet(packet_format: int, packet_id: int, total_size: int, **header_kwargs) -> bytes:
    header = make_header(packet_format, packet_id, **header_kwargs)
    return header + bytes(total_size - len(header))


def blank_packet(packet_format: int, packet_id: int, **header_kwargs) -> bytearray:
    """Zero-filled packet of the documented size with a valid header."""
    from simtelemetry.adapters.f1.sizes import DOCUMENTED_SIZES
    return bytearray(make_packet(packet_format, packet_id, DOCUMENTED_SIZES[packet_format][packet_id],
                                 **header_kwargs))


def decode_packet(data: bytes | bytearray):
    """validate() then decode(); the packet must be accepted."""
    from simtelemetry.adapters.f1.decode import decode
    from simtelemetry.adapters.f1.validate import Accepted, validate
    accepted = validate(data)
    assert isinstance(accepted, Accepted), accepted
    return decode(accepted, data)
