"""First gate for every datagram: header sanity, format/ID dispatch and exact size check."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from .header import HEADER_SIZE, PacketHeader, parse_header
from .sizes import DOCUMENTED_SIZES, PacketId

log = logging.getLogger(__name__)


class Rejection(str, Enum):
    TOO_SHORT = "too_short"                    # shorter than the 29-byte header
    UNSUPPORTED_FORMAT = "unsupported_format"  # m_packetFormat not 2025/2026
    UNKNOWN_PACKET_ID = "unknown_packet_id"    # ID not defined for this format
    SIZE_MISMATCH = "size_mismatch"            # length != documented size


@dataclass(frozen=True, slots=True)
class Accepted:
    header: PacketHeader
    packet_id: PacketId


@dataclass(frozen=True, slots=True)
class Rejected:
    reason: Rejection
    length: int
    header: PacketHeader | None = None
    expected_length: int | None = None


def validate(data: bytes | bytearray | memoryview) -> Accepted | Rejected:
    """Classify one datagram. Pure: no logging, no state."""
    length = len(data)
    if length < HEADER_SIZE:
        return Rejected(Rejection.TOO_SHORT, length)

    header = parse_header(data)
    sizes = DOCUMENTED_SIZES.get(header.packet_format)
    if sizes is None:
        return Rejected(Rejection.UNSUPPORTED_FORMAT, length, header)

    try:
        packet_id = PacketId(header.packet_id)
    except ValueError:
        return Rejected(Rejection.UNKNOWN_PACKET_ID, length, header)
    expected = sizes.get(packet_id)
    if expected is None:
        return Rejected(Rejection.UNKNOWN_PACKET_ID, length, header)
    if length != expected:
        return Rejected(Rejection.SIZE_MISMATCH, length, header, expected)
    return Accepted(header, packet_id)


class PacketGate:
    """Runs validate() and logs each distinct rejection once per source.

    A misconfigured rig sends the same bad packet many times per second, so repeats are
    logged at DEBUG; per-rig counts are kept by the health monitor.
    """

    def __init__(self) -> None:
        self._seen: set[tuple] = set()

    def check(self, data: bytes | bytearray | memoryview, source: str) -> Accepted | Rejected:
        result = validate(data)
        if isinstance(result, Rejected):
            self._log(result, source)
        return result

    def _log(self, r: Rejected, source: str) -> None:
        h = r.header
        key = (source, r.reason, h.packet_format if h else None, h.packet_id if h else None, r.length)
        level = logging.DEBUG if key in self._seen else logging.WARNING
        self._seen.add(key)
        if r.reason is Rejection.SIZE_MISMATCH:
            assert h is not None
            log.log(level, "Dropped packet from %s: format %d id %d is %d bytes, documented size is %d",
                    source, h.packet_format, h.packet_id, r.length, r.expected_length)
        elif r.reason is Rejection.UNSUPPORTED_FORMAT:
            assert h is not None
            log.log(level, "Dropped packet from %s: unsupported packet format %d (expected 2025 or 2026)",
                    source, h.packet_format)
        elif r.reason is Rejection.UNKNOWN_PACKET_ID:
            assert h is not None
            log.log(level, "Dropped packet from %s: unknown packet id %d for format %d",
                    source, h.packet_id, h.packet_format)
        else:
            log.log(level, "Dropped packet from %s: %d bytes is shorter than the header", source, r.length)
