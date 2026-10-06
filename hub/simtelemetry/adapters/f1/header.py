"""PacketHeader: 29 bytes, identical in packet formats 2025 and 2026."""

from __future__ import annotations

import struct
from dataclasses import dataclass

# struct PacketHeader (F1_25_structures.txt / F1_2026_SeasonPack_structures.txt)
#   uint16 m_packetFormat; uint8 m_gameYear; uint8 m_gameMajorVersion;
#   uint8 m_gameMinorVersion; uint8 m_packetVersion; uint8 m_packetId;
#   uint64 m_sessionUID; float m_sessionTime; uint32 m_frameIdentifier;
#   uint32 m_overallFrameIdentifier; uint8 m_playerCarIndex;
#   uint8 m_secondaryPlayerCarIndex;
HEADER_STRUCT = struct.Struct("<HBBBBBQfIIBB")
HEADER_SIZE = 29

assert HEADER_STRUCT.size == HEADER_SIZE


@dataclass(frozen=True, slots=True)
class PacketHeader:
    packet_format: int
    game_year: int
    game_major_version: int
    game_minor_version: int
    packet_version: int
    packet_id: int
    session_uid: int
    session_time: float
    frame_identifier: int
    overall_frame_identifier: int
    player_car_index: int
    secondary_player_car_index: int


def parse_header(data: bytes | bytearray | memoryview) -> PacketHeader:
    """Unpack the header from the start of a packet. Caller checks the length first."""
    return PacketHeader(*HEADER_STRUCT.unpack_from(data, 0))
