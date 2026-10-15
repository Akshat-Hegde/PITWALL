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


FINAL_CLASSIFICATION_CAR = "<7BIdBBB8B8B8B"   # 46 bytes per car, both formats (cs_maxTyreStints = 8)


def session_packet(packet_format: int, session_type: int, track_id: int = 7, *, session_uid: int = 0xDEADBEEF12345678,
                   player: int = 3) -> bytearray:
    pkt = blank_packet(packet_format, 1, session_uid=session_uid, player=player)
    struct.pack_into("<HBbB", pkt, 33, 5793, session_type, track_id, 0)
    return pkt


def final_classification_packet(packet_format: int, *, player: int = 3, cars: dict[int, dict] | None = None,
                                num_cars: int = 20, session_uid: int = 0xDEADBEEF12345678) -> bytearray:
    """Packet id 8. `cars` maps a car index to field overrides; all other slots hold decoys."""
    pkt = blank_packet(packet_format, 8, player=player, session_uid=session_uid)
    pkt[29] = num_cars
    base = dict(position=1, laps=0, grid=0, points=0, pits=0, status=0, reason=0, best_ms=0, total_s=0.0,
                pen_s=0, num_pen=0, stints=0)
    n_slots = (len(pkt) - 30) // struct.calcsize(FINAL_CLASSIFICATION_CAR)
    for idx in range(n_slots):
        v = {**base, **(cars or {}).get(idx, dict(position=21, laps=99, grid=22, best_ms=1, total_s=1.0))}
        struct.pack_into(FINAL_CLASSIFICATION_CAR, pkt, 30 + idx * struct.calcsize(FINAL_CLASSIFICATION_CAR),
                         v["position"], v["laps"], v["grid"], v["points"], v["pits"], v["status"], v["reason"],
                         v["best_ms"], v["total_s"], v["pen_s"], v["num_pen"], v["stints"], *([0] * 24))
    return pkt


# --- staff page: a PIN is always required ----------------------------------------------------------------

STAFF_PIN = "1357"
STAFF = {"X-Staff-Pin": STAFF_PIN}


def staff_ready(hub):
    """Give the hub a staff PIN (the staff page never runs without one); send STAFF as the client's headers."""
    hub.config.staff.pin = STAFF_PIN
    return hub
