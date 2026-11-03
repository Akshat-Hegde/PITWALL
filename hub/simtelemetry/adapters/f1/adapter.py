"""F1 implementation of the core GameAdapter interface."""

from __future__ import annotations

from collections.abc import Mapping

from ...core.adapter import Checked, DecodeResult, LiveSummary, RaceFinished
from ...core.laps import LiveLap
from .appendix import session_type_name, track_name
from .decode import decode
from .laps import F1LapTracker
import math
import time

from ...core.slides import SlideDetector
from .packets import CarDamage, CarStatus, FinalClassification, CarTelemetry, LapData, Motion, MotionEx, Participant, Session
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
    # The licence's id for this game. Every packet format the adapter reads (2025, and 2026 when a rig sends it)
    # counts as this game, so no cafe loses a rig over the format setting.
    game_id = "f1_25"

    def __init__(self, track_overrides: Mapping[int, str] | None = None) -> None:
        self._gate = PacketGate()
        self._track_overrides = dict(track_overrides or {})
        self._live: dict[str, LiveSummary] = {}
        self._session_of: dict[str, str | None] = {}
        self._laps: dict[str, F1LapTracker] = {}
        self._slides: dict[str, SlideDetector] = {}
        self._paused: dict[str, bool] = {}      # game paused or spectating (from the Session packet): not driving
        # Frame stall: per source, the last overall frame id and when (clock) it last changed.
        self._frames: dict[str, tuple[int, float]] = {}
        self._clock = time.monotonic

    # m_gamePaused is only set in network games (F1_25_structures.txt), so a single-player pause
    # (e.g. Time Trial) is spotted another way: packets keep arriving but the header's overall
    # frame identifier stops advancing. A car standing still in the garage or pits still has
    # advancing frames, so it is unaffected. TODO: confirm with a real paused Time Trial capture
    # that the game keeps sending packets with a frozen frame id (if it stops sending instead,
    # the no-data handling already covers it).
    FRAME_STALL_S = 0.5

    def _frame_stalled(self, source: str, frame: int) -> bool:
        now = self._clock()
        seen = self._frames.get(source)
        if seen is None or seen[0] != frame:
            self._frames[source] = (frame, now)
            return False
        return now - seen[1] >= self.FRAME_STALL_S

    def check(self, data: bytes, source: str) -> Checked:
        result = self._gate.check(data, source)
        header = result.header
        data_format = str(header.packet_format) if header else None
        # Session UID 0 is not a real session (menus): it never starts or ends one.
        session_id = f"{header.session_uid:016x}" if header and header.session_uid else None
        if isinstance(result, Accepted):
            return Checked(ok=True, label=PACKET_LABELS[result.packet_id], data_format=data_format,
                           session_id=session_id, payload=result)
        return Checked(ok=False, reason=result.reason.value, data_format=data_format, session_id=session_id)

    def decode(self, checked: Checked, data: bytes, source: str) -> DecodeResult:
        packet = decode(checked.payload, data)
        session_id = checked.session_id
        if session_id is not None:
            previous = self._session_of.get(source)
            if previous is not None and previous != session_id:
                self._live.pop(source, None)  # a different real session: nothing from the old one carries over
                self._slides.pop(source, None)
                self._paused.pop(source, None)
                self._frames.pop(source, None)
            self._session_of[source] = session_id
        live = self._live.setdefault(source, LiveSummary())
        result = DecodeResult()
        header = getattr(checked.payload, "header", None)
        stalled = self._frame_stalled(source, header.overall_frame_identifier) if header is not None else False
        if packet is not None and hasattr(packet, "header"):
            tracker = self._laps.setdefault(source, F1LapTracker())
            uid = packet.header.session_uid or tracker.session_uid or 0   # UID 0 (menus) keeps the current session
            result.lap_events = tracker.on_packet(packet, uid)
            result.lap_update = isinstance(packet, LapData)
        if isinstance(packet, Motion):
            live.position = (packet.position[0], packet.position[2])
            live.g_lat = round(packet.g_force_lateral, 2)
            live.g_long = round(packet.g_force_longitudinal, 2)
            # Paused (network game), spectating, or a single-player pause (frame id stalled): not driving.
            result.driving = not self._paused.get(source, False) and not stalled
        elif isinstance(packet, Session):
            self._paused[source] = packet.game_paused or packet.is_spectating
            live.track = track_name(packet.track_id, self._track_overrides)
            live.track_key = f"{self.game}:{packet.track_id}" if packet.track_id >= 0 else None
            live.track_length_m = float(packet.track_length) if packet.track_length else None
            live.session_type = session_type_name(packet.session_type)
            live.weather = WEATHER.get(packet.weather)
            live.air_temp_c = packet.air_temperature
            live.track_temp_c = packet.track_temperature
            live.time_left_s = packet.session_time_left
            live.assists = {**(live.assists or {}), "steering": packet.steering_assist,
                            "braking": packet.braking_assist, "gearbox": packet.gearbox_assist,
                            "racing_line": packet.dynamic_racing_line}
            if 0 < packet.sector2_lap_distance_start < packet.sector3_lap_distance_start:
                live.sector_starts_m = (0.0, packet.sector2_lap_distance_start, packet.sector3_lap_distance_start)
        elif isinstance(packet, LapData):
            if live.top_speed_lap_number != packet.current_lap_num:
                live.top_speed_lap_number = packet.current_lap_num
                live.top_speed_lap_kph = None  # new lap: the lap's speed trap starts again
            live.lap = packet.current_lap_num
            live.current_lap_ms = packet.current_lap_time_ms
        elif isinstance(packet, CarTelemetry):
            live.speed_kph = packet.speed_kph
            live.gear = packet.gear
            live.throttle = packet.throttle
            live.brake = packet.brake
            live.rpm = packet.engine_rpm
            live.steer = round(packet.steer, 3)
            live.drs_open = packet.drs
            live.rev_lights_pct = packet.rev_lights_percent
            live.tyre_surface_c = wheels(packet.tyres_surface_temperature)
            live.tyre_inner_c = wheels(packet.tyres_inner_temperature)
            live.tyre_pressure_psi = wheels(tuple(round(p, 1) for p in packet.tyres_pressure))
            live.brake_c = wheels(packet.brakes_temperature)
            live.top_speed_lap_kph = max(live.top_speed_lap_kph or 0, packet.speed_kph)
            live.top_speed_kph = max(live.top_speed_kph or 0, packet.speed_kph)
        elif isinstance(packet, CarStatus):
            live.tyre_class = tyre_class(packet.visual_compound)
            live.tyre_label = tyre_label(packet.actual_compound, packet.visual_compound)
            live.tyre_age_laps = packet.tyres_age_laps
            live.max_rpm = packet.max_rpm or None
            live.drs_allowed = packet.drs_allowed
            live.ers_pct = round(min(100.0, max(0.0, packet.ers_store_energy / ERS_MAX_J * 100)), 1)
            live.ers_mode = ERS_MODES.get(packet.ers_deploy_mode)
            live.fuel_kg = round(packet.fuel_in_tank, 2)
            live.fuel_laps = round(packet.fuel_remaining_laps, 2)
            live.pit_limiter = packet.pit_limiter
            live.assists = {**(live.assists or {}), "traction_control": packet.traction_control,
                            "anti_lock_brakes": int(packet.anti_lock_brakes)}
        elif isinstance(packet, MotionEx):
            live.slide_deg = round(math.degrees(packet.chassis_yaw), 1)
            save = self._slides.setdefault(source, SlideDetector()).update(
                packet.header.session_time, live.slide_deg, live.speed_kph)
            if save is not None:
                live.saves += 1
                live.last_save_at_ms = round(time.time() * 1000)
                live.last_save_peak_deg = save.peak_deg
        elif isinstance(packet, CarDamage):
            live.tyre_wear_pct = wheels(tuple(round(w, 1) for w in packet.tyres_wear))
            live.damage = {
                "front_wing_left": packet.front_left_wing, "front_wing_right": packet.front_right_wing,
                "rear_wing": packet.rear_wing, "floor": packet.floor, "diffuser": packet.diffuser,
                "sidepod": packet.sidepod, "gearbox": packet.gearbox, "engine": packet.engine,
            }
        elif isinstance(packet, Participant):
            live.driver_name = packet.name or None
        elif isinstance(packet, FinalClassification):
            if live.session_type in RACE_SESSIONS:  # practice, qualifying and Time Trial make no podium
                total = packet.total_race_time_s + packet.penalties_time_s if packet.total_race_time_s else None
                result.race_results.append(RaceFinished(
                    track_key=live.track_key,
                    session_type=live.session_type,
                    session_uid=f"{packet.header.session_uid:016x}",
                    position=packet.position,
                    grid_position=packet.grid_position or None,
                    laps=packet.num_laps,
                    best_lap_ms=packet.best_lap_time_ms or None,
                    total_time_s=total,
                    penalties_s=packet.penalties_time_s,
                    status=RESULT_STATUS.get(packet.result_status, "invalid"),
                    num_cars=packet.num_cars,
                ))
        return result

    def live_summary(self, source: str) -> LiveSummary | None:
        return self._live.get(source)

    def live_lap(self, source: str) -> LiveLap | None:
        tracker = self._laps.get(source)
        return tracker.live() if tracker else None

    def is_supported_format(self, data_format: str) -> bool:
        return data_format.isdigit() and int(data_format) in SUPPORTED_FORMATS


# Session types 15-17 (appendix.SESSION_TYPES): Race, Race 2, Race 3
RACE_SESSIONS = frozenset(session_type_name(i) for i in (15, 16, 17))
# FinalClassificationData m_resultStatus
RESULT_STATUS = {0: "invalid", 1: "inactive", 2: "active", 3: "finished", 4: "dnf", 5: "dsq",
                 6: "not_classified", 7: "retired"}
# Session m_weather: 0 = clear, 1 = light cloud, 2 = overcast, 3 = light rain, 4 = heavy rain, 5 = storm
WEATHER = {0: "clear", 1: "light_cloud", 2: "overcast", 3: "light_rain", 4: "heavy_rain", 5: "storm"}
# CarStatus m_ersDeployMode: 0 = none, 1 = medium, 2 = hotlap, 3 = overtake
ERS_MODES = {0: "none", 1: "medium", 2: "hotlap", 3: "overtake"}
ERS_MAX_J = 4_000_000.0  # ERS store capacity: 4 MJ


def wheels(values):
    """F1 per-wheel arrays are RL, RR, FL, FR; the hub uses FL, FR, RL, RR."""
    rl, rr, fl, fr = values
    return (fl, fr, rl, rr)


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
