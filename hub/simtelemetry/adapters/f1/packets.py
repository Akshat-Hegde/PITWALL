"""Decoded F1 packets, player car only, with format differences already removed.

These are F1-specific; the game-agnostic model is built from them in the normaliser.
"""

from __future__ import annotations

from dataclasses import dataclass

from .header import PacketHeader
from .sizes import PacketId
from .tyres import TyreCompound


@dataclass(frozen=True, slots=True)
class Motion:
    header: PacketHeader
    position: tuple[float, float, float]   # world x, y, z (metres)
    velocity: tuple[float, float, float]   # world x, y, z (m/s)
    forward_dir: tuple[float, float, float]
    right_dir: tuple[float, float, float]
    g_force_lateral: float
    g_force_longitudinal: float
    g_force_vertical: float
    yaw: float
    pitch: float
    roll: float


@dataclass(frozen=True, slots=True)
class Session:
    header: PacketHeader
    weather: int
    track_temperature: int
    air_temperature: int
    total_laps: int
    track_length: int
    session_type: int
    track_id: int                 # -1 = unknown
    formula: int
    session_time_left: int
    session_duration: int
    game_paused: bool
    is_spectating: bool
    spectator_car_index: int
    network_game: bool
    game_mode: int
    rule_set: int
    sector2_lap_distance_start: float
    sector3_lap_distance_start: float


@dataclass(frozen=True, slots=True)
class LapData:
    header: PacketHeader
    last_lap_time_ms: int
    current_lap_time_ms: int
    sector1_time_ms: int          # minutes*60000 + ms part; 0 until sector completed
    sector2_time_ms: int
    delta_to_car_in_front_ms: int
    delta_to_race_leader_ms: int
    lap_distance: float           # metres; negative before the line is first crossed
    total_distance: float
    car_position: int
    current_lap_num: int
    pit_status: int
    sector: int                   # 0 = S1, 1 = S2, 2 = S3
    current_lap_invalid: bool
    driver_status: int            # 0 garage, 1 flying lap, 2 in lap, 3 out lap, 4 on track
    result_status: int
    time_trial_pb_car_idx: int    # 255 if invalid
    time_trial_rival_car_idx: int


@dataclass(frozen=True, slots=True)
class FastestLapDetails:
    vehicle_idx: int
    lap_time_s: float


@dataclass(frozen=True, slots=True)
class FlashbackDetails:
    frame_identifier: int
    session_time: float


@dataclass(frozen=True, slots=True)
class Event:
    header: PacketHeader
    code: str                     # 4-char event string code, e.g. "SSTA"
    details: FastestLapDetails | FlashbackDetails | None


@dataclass(frozen=True, slots=True)
class Participant:
    header: PacketHeader
    num_active_cars: int
    ai_controlled: bool
    driver_id: int                # 255 (2025) / 65535 (2026) for network humans
    network_id: int
    team_id: int
    race_number: int
    nationality: int
    name: str
    your_telemetry_public: bool
    platform: int


@dataclass(frozen=True, slots=True)
class CarTelemetry:
    header: PacketHeader
    speed_kph: int
    throttle: float               # 0..1
    steer: float                  # -1..1
    brake: float                  # 0..1
    clutch: int                   # 0..100
    gear: int                     # -1 R, 0 N, 1..8
    engine_rpm: int
    drs: bool
    rev_lights_percent: int
    engine_temperature: int
    brakes_temperature: tuple[int, int, int, int]       # RL, RR, FL, FR
    tyres_surface_temperature: tuple[int, int, int, int]
    tyres_inner_temperature: tuple[int, int, int, int]
    tyres_pressure: tuple[float, float, float, float]
    surface_type: tuple[int, int, int, int]
    suggested_gear: int


@dataclass(frozen=True, slots=True)
class CarStatus:
    header: PacketHeader
    actual_compound: TyreCompound
    visual_compound: TyreCompound
    tyres_age_laps: int
    fia_flag: int
    pit_limiter: bool
    fuel_in_tank: float
    fuel_remaining_laps: float
    max_rpm: int
    drs_allowed: bool
    ers_store_energy: float
    ers_deploy_mode: int


@dataclass(frozen=True, slots=True)
class MotionEx:
    """Extra motion data, player car only. Per-wheel tuples are RL, RR, FL, FR."""

    header: PacketHeader
    chassis_yaw: float                                   # radians, chassis vs direction of travel
    chassis_pitch: float
    front_wheels_angle: float                            # radians
    wheel_slip_ratio: tuple[float, float, float, float]
    wheel_slip_angle: tuple[float, float, float, float]
    local_velocity: tuple[float, float, float]           # m/s, car frame
    angular_velocity: tuple[float, float, float]         # rad/s


@dataclass(frozen=True, slots=True)
class CarDamage:
    header: PacketHeader
    tyres_wear: tuple[float, float, float, float]       # RL, RR, FL, FR (percentage)
    tyres_damage: tuple[int, int, int, int]
    brakes_damage: tuple[int, int, int, int]
    front_left_wing: int                                 # percentages
    front_right_wing: int
    rear_wing: int
    floor: int
    diffuser: int
    sidepod: int
    gearbox: int
    engine: int
    drs_fault: bool
    ers_fault: bool


@dataclass(frozen=True, slots=True)
class LapHistory:
    lap_time_ms: int
    sector1_time_ms: int
    sector2_time_ms: int
    sector3_time_ms: int
    lap_valid: bool
    sector1_valid: bool
    sector2_valid: bool
    sector3_valid: bool


@dataclass(frozen=True, slots=True)
class TyreStint:
    end_lap: int                  # 255 if current tyre
    actual_compound: TyreCompound
    visual_compound: TyreCompound


@dataclass(frozen=True, slots=True)
class SessionHistory:
    """Player car's lap history. Only the first num_laps slots are trustworthy, and the
    last of those is the lap in progress ("including current partial lap")."""

    header: PacketHeader
    car_idx: int
    num_laps: int                 # clamped to the 100 slots
    best_lap_time_lap_num: int
    best_sector1_lap_num: int
    best_sector2_lap_num: int
    best_sector3_lap_num: int
    slots: tuple[LapHistory, ...]  # all 100 slots as sent
    tyre_stints: tuple[TyreStint, ...]  # first num_tyre_stints only

    @property
    def laps(self) -> tuple[LapHistory, ...]:
        return self.slots[: self.num_laps]


@dataclass(frozen=True, slots=True)
class TimeTrialSet:
    car_idx: int
    team_id: int
    lap_time_ms: int
    sector1_time_ms: int
    sector2_time_ms: int
    sector3_time_ms: int
    traction_control: bool
    gearbox_assist: bool
    anti_lock_brakes: bool
    equal_car_performance: bool
    custom_setup: bool
    valid: bool


@dataclass(frozen=True, slots=True)
class TimeTrial:
    header: PacketHeader
    player_session_best: TimeTrialSet
    personal_best: TimeTrialSet
    rival: TimeTrialSet


@dataclass(frozen=True, slots=True)
class NoPlayerCar:
    """A per-car packet whose header has no usable m_playerCarIndex (255 or out of range)."""

    header: PacketHeader
    packet_id: PacketId


Decoded = (Motion | Session | LapData | Event | Participant | CarTelemetry | CarStatus | CarDamage | SessionHistory
           | TimeTrial | MotionEx)
