"""F1 implementation of the core GameAdapter interface."""

from __future__ import annotations

from collections.abc import Mapping

from ...core.adapter import Checked, DecodeResult, LiveSummary
from ...core.laps import LiveLap
from .appendix import session_type_name, track_name
from .decode import decode
from .laps import F1LapTracker
from .packets import CarStatus, CarTelemetry, LapData, Motion, Participant, Session
from .sizes import SUPPORTED_FORMATS, PacketId
from .tyres import Compound, TyreCompound
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
        self._session_of: dict[str, str | None] = {}
        self._laps: dict[str, F1LapTracker] = {}

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
        if self._session_of.get(source, checked.session_id) != checked.session_id:
            self._live.pop(source, None)  # new game session: nothing from the old one carries over
        self._session_of[source] = checked.session_id
        live = self._live.setdefault(source, LiveSummary())
        result = DecodeResult()
        if packet is not None and hasattr(packet, "header"):
            tracker = self._laps.setdefault(source, F1LapTracker())
            result.lap_events = tracker.on_packet(packet, packet.header.session_uid)
            result.lap_update = isinstance(packet, LapData)
        if isinstance(packet, Motion):
            live.position = (packet.position[0], packet.position[2])
            result.driving = True
        elif isinstance(packet, Session):
            live.track = track_name(packet.track_id, self._track_overrides)
            live.track_key = f"{self.game}:{packet.track_id}" if packet.track_id >= 0 else None
            live.track_length_m = float(packet.track_length) if packet.track_length else None
            live.session_type = session_type_name(packet.session_type)
            if 0 < packet.sector2_lap_distance_start < packet.sector3_lap_distance_start:
                live.sector_starts_m = (0.0, packet.sector2_lap_distance_start, packet.sector3_lap_distance_start)
        elif isinstance(packet, LapData):
            live.lap = packet.current_lap_num
            live.current_lap_ms = packet.current_lap_time_ms
        elif isinstance(packet, CarTelemetry):
            live.speed_kph = packet.speed_kph
            live.gear = packet.gear
            live.throttle = packet.throttle
            live.brake = packet.brake
            live.rpm = packet.engine_rpm
        elif isinstance(packet, CarStatus):
            live.tyre_class = tyre_class(packet.visual_compound)
            live.tyre_label = tyre_label(packet.actual_compound, packet.visual_compound)
            live.tyre_age_laps = packet.tyres_age_laps
        elif isinstance(packet, Participant):
            live.driver_name = packet.name or None
        return result

    def live_summary(self, source: str) -> LiveSummary | None:
        return self._live.get(source)

    def live_lap(self, source: str) -> LiveLap | None:
        tracker = self._laps.get(source)
        return tracker.live() if tracker else None

    def is_supported_format(self, data_format: str) -> bool:
        return data_format.isdigit() and int(data_format) in SUPPORTED_FORMATS


_TYRE_CLASS = {
    Compound.SOFT: "soft", Compound.SUPER_SOFT: "soft", Compound.MEDIUM: "medium", Compound.HARD: "hard",
    Compound.INTER: "inter", Compound.WET: "wet",
}


def tyre_class(visual: TyreCompound) -> str:
    """Generic class from the visual compound (what the sidewall colour shows)."""
    if visual.compound is Compound.UNKNOWN:
        return "unknown"
    return _TYRE_CLASS.get(visual.compound, "other")


def tyre_label(actual: TyreCompound, visual: TyreCompound) -> str:
    """The actual compound (C0-C6) when known, else the visual one, e.g. "inter"."""
    return actual.label if actual.compound is not Compound.UNKNOWN else visual.label
