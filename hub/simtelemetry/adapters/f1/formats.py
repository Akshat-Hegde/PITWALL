"""Per-format layout registry used by the decoder."""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from . import f2025, f2026
from .layout import Layout
from .sizes import FORMAT_2025, FORMAT_2026, PacketId


@dataclass(frozen=True)
class FormatLayouts:
    packet_format: int
    max_cars: int
    gforce_divisor: float | None   # None: g-force is already float
    packets: dict[PacketId, Layout]  # full-packet layouts for every decoded packet
    car_motion: Layout
    lap_data: Layout
    participant: Layout
    car_telemetry: Layout
    car_status: Layout
    car_damage: Layout
    lap_history: Layout
    tyre_stint: Layout
    time_trial_set: Layout
    event_members: dict[str, Layout]


def _build(module: ModuleType, packet_format: int, gforce_divisor: float | None) -> FormatLayouts:
    return FormatLayouts(
        packet_format=packet_format,
        max_cars=module.MAX_CARS,
        gforce_divisor=gforce_divisor,
        packets={
            PacketId.MOTION: module.PacketMotionData,
            PacketId.SESSION: module.PacketSessionData,
            PacketId.LAP_DATA: module.PacketLapData,
            PacketId.EVENT: module.PacketEventData,
            PacketId.PARTICIPANTS: module.PacketParticipantsData,
            PacketId.CAR_TELEMETRY: module.PacketCarTelemetryData,
            PacketId.CAR_STATUS: module.PacketCarStatusData,
            PacketId.CAR_DAMAGE: module.PacketCarDamageData,
            PacketId.MOTION_EX: module.PacketMotionExData,
            PacketId.SESSION_HISTORY: module.PacketSessionHistoryData,
            PacketId.TIME_TRIAL: module.PacketTimeTrialData,
        },
        car_motion=module.CarMotionData,
        lap_data=module.LapData,
        participant=module.ParticipantData,
        car_telemetry=module.CarTelemetryData,
        car_status=module.CarStatusData,
        car_damage=module.CarDamageData,
        lap_history=module.LapHistoryData,
        tyre_stint=module.TyreStintHistoryData,
        time_trial_set=module.TimeTrialDataSet,
        event_members=module.EVENT_MEMBERS,
    )


FORMATS: dict[int, FormatLayouts] = {
    FORMAT_2025: _build(f2025, FORMAT_2025, None),
    FORMAT_2026: _build(f2026, FORMAT_2026, f2026.GFORCE_QUANTISATION),
}
