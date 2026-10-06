"""F1 implementation of the core GameAdapter interface."""

from __future__ import annotations

from collections.abc import Mapping

from ...core.adapter import Checked, DecodeResult, LiveSummary
from .appendix import session_type_name, track_name
from .decode import decode
from .packets import CarTelemetry, LapData, Motion, Participant, Session
from .sizes import SUPPORTED_FORMATS, PacketId
from .validate import Accepted, PacketGate

PACKET_LABELS: dict[PacketId, str] = {
    PacketId.MOTION: "Motion",
    PacketId.SESSION: "Session",
    PacketId.LAP_DATA: "LapData",
    PacketId.EVENT: "Event",
    PacketId.PARTICIPANTS: "Participants",
    PacketId.CAR_SETUPS: "CarSetups",
    PacketId.CAR_TELEMETRY: "CarTelemetry",
    PacketId.CAR_STATUS: "CarStatus",
    PacketId.FINAL_CLASSIFICATION: "FinalClassification",
    PacketId.LOBBY_INFO: "LobbyInfo",
    PacketId.CAR_DAMAGE: "CarDamage",
    PacketId.SESSION_HISTORY: "SessionHistory",
    PacketId.TYRE_SETS: "TyreSets",
    PacketId.MOTION_EX: "MotionEx",
    PacketId.TIME_TRIAL: "TimeTrial",
    PacketId.LAP_POSITIONS: "LapPositions",
    PacketId.CAR_TELEMETRY_2: "CarTelemetry2",
}


class F1Adapter:
    game = "F1"

    def __init__(self, track_overrides: Mapping[int, str] | None = None) -> None:
        self._gate = PacketGate()
        self._track_overrides = dict(track_overrides or {})
        self._live: dict[str, LiveSummary] = {}

    def check(self, data: bytes, source: str) -> Checked:
        result = self._gate.check(data, source)
        header = result.header
        data_format = str(header.packet_format) if header else None
        session_id = f"{header.session_uid:016x}" if header else None
        if isinstance(result, Accepted):
            return Checked(ok=True, label=PACKET_LABELS[result.packet_id], data_format=data_format,
                           session_id=session_id, payload=result)
        return Checked(ok=False, reason=result.reason.value, data_format=data_format, session_id=session_id)

    def decode(self, checked: Checked, data: bytes, source: str) -> DecodeResult:
        packet = decode(checked.payload, data)
        live = self._live.setdefault(source, LiveSummary())
        if isinstance(packet, Motion):
            return DecodeResult(driving=True)
        if isinstance(packet, Session):
            live.track = track_name(packet.track_id, self._track_overrides)
            live.session_type = session_type_name(packet.session_type)
        elif isinstance(packet, LapData):
            live.lap = packet.current_lap_num
            live.current_lap_ms = packet.current_lap_time_ms
        elif isinstance(packet, CarTelemetry):
            live.speed_kph = packet.speed_kph
        elif isinstance(packet, Participant):
            live.driver_name = packet.name or None
        return DecodeResult()

    def live_summary(self, source: str) -> LiveSummary | None:
        return self._live.get(source)

    def is_supported_format(self, data_format: str) -> bool:
        return data_format.isdigit() and int(data_format) in SUPPORTED_FORMATS
