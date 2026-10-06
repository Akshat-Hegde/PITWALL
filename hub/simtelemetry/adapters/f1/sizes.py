"""Packet IDs and documented packet sizes per packet format.

Sizes are transcribed from the "// <Name> - <N> bytes" section comments in
docs/F1_25_structures.txt (format 2025) and docs/F1_2026_SeasonPack_structures.txt
(format 2026). tests/test_sizes_table.py re-reads those files to guard the transcription.
"""

from __future__ import annotations

from enum import IntEnum


class PacketId(IntEnum):
    MOTION = 0
    SESSION = 1
    LAP_DATA = 2
    EVENT = 3
    PARTICIPANTS = 4
    CAR_SETUPS = 5
    CAR_TELEMETRY = 6
    CAR_STATUS = 7
    FINAL_CLASSIFICATION = 8
    LOBBY_INFO = 9
    CAR_DAMAGE = 10
    SESSION_HISTORY = 11
    TYRE_SETS = 12
    MOTION_EX = 13
    TIME_TRIAL = 14
    LAP_POSITIONS = 15
    CAR_TELEMETRY_2 = 16  # format 2026 only


FORMAT_2025 = 2025
FORMAT_2026 = 2026

DOCUMENTED_SIZES: dict[int, dict[PacketId, int]] = {
    FORMAT_2025: {
        PacketId.MOTION: 1349,
        PacketId.SESSION: 753,
        PacketId.LAP_DATA: 1285,
        PacketId.EVENT: 45,
        PacketId.PARTICIPANTS: 1284,
        PacketId.CAR_SETUPS: 1133,
        PacketId.CAR_TELEMETRY: 1352,
        PacketId.CAR_STATUS: 1239,
        PacketId.FINAL_CLASSIFICATION: 1042,
        PacketId.LOBBY_INFO: 954,
        PacketId.CAR_DAMAGE: 1041,
        PacketId.SESSION_HISTORY: 1460,
        PacketId.TYRE_SETS: 231,
        PacketId.MOTION_EX: 273,
        PacketId.TIME_TRIAL: 101,
        PacketId.LAP_POSITIONS: 1131,
    },
    FORMAT_2026: {
        PacketId.MOTION: 1325,
        PacketId.SESSION: 926,
        PacketId.LAP_DATA: 1399,
        PacketId.EVENT: 45,
        PacketId.PARTICIPANTS: 1470,
        PacketId.CAR_SETUPS: 1233,
        PacketId.CAR_TELEMETRY: 1448,
        PacketId.CAR_STATUS: 1445,
        PacketId.FINAL_CLASSIFICATION: 1134,
        PacketId.LOBBY_INFO: 1062,
        PacketId.CAR_DAMAGE: 1133,
        PacketId.SESSION_HISTORY: 1460,
        PacketId.TYRE_SETS: 231,
        PacketId.MOTION_EX: 273,
        PacketId.TIME_TRIAL: 104,
        PacketId.LAP_POSITIONS: 1231,
        PacketId.CAR_TELEMETRY_2: 269,
    },
}

SUPPORTED_FORMATS: frozenset[int] = frozenset(DOCUMENTED_SIZES)

# Packets the hub decodes; every other documented packet is validated then ignored.
USED_PACKETS: frozenset[PacketId] = frozenset({
    PacketId.MOTION,
    PacketId.SESSION,
    PacketId.LAP_DATA,
    PacketId.EVENT,
    PacketId.PARTICIPANTS,
    PacketId.CAR_TELEMETRY,
    PacketId.CAR_STATUS,
    PacketId.SESSION_HISTORY,
    PacketId.TIME_TRIAL,
})

# cs_maxNumCarsInUDPData per format.
MAX_CARS: dict[int, int] = {FORMAT_2025: 22, FORMAT_2026: 24}
