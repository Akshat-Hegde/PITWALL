"""Decode validated packets into player-car records (packets.py).

Only the player's own car is decoded: the header's m_playerCarIndex selects the slot in
per-car arrays. In Time Trial the arrays also hold ghost cars (PB / rival), and Session
History cycles through them, so nothing else is trusted.
"""

from __future__ import annotations

import struct
from typing import Any, Callable

from .formats import FORMATS, FormatLayouts
from .header import PacketHeader
from .layout import Layout
from .packets import (
    CarDamage,
    MotionEx,
    CarStatus,
    CarTelemetry,
    Decoded,
    Event,
    FastestLapDetails,
    FlashbackDetails,
    LapData,
    LapHistory,
    Motion,
    NoPlayerCar,
    Participant,
    Session,
    SessionHistory,
    TimeTrial,
    TimeTrialSet,
    TyreStint,
)
from .sizes import PacketId
from .tyres import actual_compound, visual_compound
from .validate import Accepted

Buffer = bytes | bytearray | memoryview

# "For the normalised vectors below, to convert to float values divide by 32767.0f"
DIRECTION_SCALE = 32767.0

# m_playerCarIndex value meaning "no player car" (also any index >= the format's car count)
NO_PLAYER_INDEX = 255


def decode(accepted: Accepted, data: Buffer) -> Decoded | NoPlayerCar | None:
    """Decode a packet that passed validate().

    Returns None for packet types the hub ignores and for Session History packets about
    other cars; NoPlayerCar when a per-car packet has no usable player index.
    """
    handler = _HANDLERS.get(accepted.packet_id)
    if handler is None:
        return None
    layouts = FORMATS[accepted.header.packet_format]
    return handler(accepted.header, data, layouts)


def player_index(header: PacketHeader, layouts: FormatLayouts) -> int | None:
    idx = header.player_car_index
    if idx == NO_PLAYER_INDEX or idx >= layouts.max_cars:
        return None
    return idx


def _player_car(data: Buffer, packet: Layout, array_field: str, car: Layout, idx: int) -> dict[str, Any]:
    return car.unpack_from(data, packet.offset_of(array_field) + idx * car.size)


def _ms(minutes: int, ms_part: int) -> int:
    return minutes * 60000 + ms_part


def _decode_motion(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> Motion | NoPlayerCar:
    idx = player_index(header, layouts)
    if idx is None:
        return NoPlayerCar(header, PacketId.MOTION)
    m = _player_car(data, layouts.packets[PacketId.MOTION], "m_carMotionData", layouts.car_motion, idx)
    divisor = layouts.gforce_divisor
    g = (m["m_gForceLateral"], m["m_gForceLongitudinal"], m["m_gForceVertical"])
    if divisor is not None:
        g = tuple(v / divisor for v in g)
    return Motion(
        header=header,
        position=(m["m_worldPositionX"], m["m_worldPositionY"], m["m_worldPositionZ"]),
        velocity=(m["m_worldVelocityX"], m["m_worldVelocityY"], m["m_worldVelocityZ"]),
        forward_dir=(m["m_worldForwardDirX"] / DIRECTION_SCALE,
                     m["m_worldForwardDirY"] / DIRECTION_SCALE,
                     m["m_worldForwardDirZ"] / DIRECTION_SCALE),
        right_dir=(m["m_worldRightDirX"] / DIRECTION_SCALE,
                   m["m_worldRightDirY"] / DIRECTION_SCALE,
                   m["m_worldRightDirZ"] / DIRECTION_SCALE),
        g_force_lateral=float(g[0]),
        g_force_longitudinal=float(g[1]),
        g_force_vertical=float(g[2]),
        yaw=m["m_yaw"],
        pitch=m["m_pitch"],
        roll=m["m_roll"],
    )


def _decode_session(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> Session:
    s = layouts.packets[PacketId.SESSION].unpack_from(data)
    return Session(
        header=header,
        weather=s["m_weather"],
        track_temperature=s["m_trackTemperature"],
        air_temperature=s["m_airTemperature"],
        total_laps=s["m_totalLaps"],
        track_length=s["m_trackLength"],
        session_type=s["m_sessionType"],
        track_id=s["m_trackId"],
        formula=s["m_formula"],
        session_time_left=s["m_sessionTimeLeft"],
        session_duration=s["m_sessionDuration"],
        game_paused=bool(s["m_gamePaused"]),
        is_spectating=bool(s["m_isSpectating"]),
        spectator_car_index=s["m_spectatorCarIndex"],
        network_game=bool(s["m_networkGame"]),
        game_mode=s["m_gameMode"],
        rule_set=s["m_ruleSet"],
        sector2_lap_distance_start=s["m_sector2LapDistanceStart"],
        sector3_lap_distance_start=s["m_sector3LapDistanceStart"],
        steering_assist=s["m_steeringAssist"],
        braking_assist=s["m_brakingAssist"],
        gearbox_assist=s["m_gearboxAssist"],
        dynamic_racing_line=s["m_dynamicRacingLine"],
    )


def _decode_lap_data(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> LapData | NoPlayerCar:
    idx = player_index(header, layouts)
    if idx is None:
        return NoPlayerCar(header, PacketId.LAP_DATA)
    packet = layouts.packets[PacketId.LAP_DATA]
    lap = _player_car(data, packet, "m_lapData", layouts.lap_data, idx)
    pb_idx = data[packet.offset_of("m_timeTrialPBCarIdx")]
    rival_idx = data[packet.offset_of("m_timeTrialRivalCarIdx")]
    return LapData(
        header=header,
        last_lap_time_ms=lap["m_lastLapTimeInMS"],
        current_lap_time_ms=lap["m_currentLapTimeInMS"],
        sector1_time_ms=_ms(lap["m_sector1TimeMinutesPart"], lap["m_sector1TimeMSPart"]),
        sector2_time_ms=_ms(lap["m_sector2TimeMinutesPart"], lap["m_sector2TimeMSPart"]),
        delta_to_car_in_front_ms=_ms(lap["m_deltaToCarInFrontMinutesPart"], lap["m_deltaToCarInFrontMSPart"]),
        delta_to_race_leader_ms=_ms(lap["m_deltaToRaceLeaderMinutesPart"], lap["m_deltaToRaceLeaderMSPart"]),
        lap_distance=lap["m_lapDistance"],
        total_distance=lap["m_totalDistance"],
        car_position=lap["m_carPosition"],
        current_lap_num=lap["m_currentLapNum"],
        pit_status=lap["m_pitStatus"],
        sector=lap["m_sector"],
        current_lap_invalid=bool(lap["m_currentLapInvalid"]),
        driver_status=lap["m_driverStatus"],
        result_status=lap["m_resultStatus"],
        time_trial_pb_car_idx=pb_idx,
        time_trial_rival_car_idx=rival_idx,
    )


# Event codes whose union member we decode. SSTA/SEND carry no details.
_EVENT_MEMBER_FOR_CODE = {"FTLP": "FastestLap", "FLBK": "Flashback"}
EVENT_CODES_USED = frozenset({"SSTA", "SEND", "FTLP", "FLBK"})


def _decode_event(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> Event:
    packet = layouts.packets[PacketId.EVENT]
    code_at = packet.offset_of("m_eventStringCode")
    code = bytes(data[code_at:code_at + 4]).decode("ascii", errors="replace")
    member_name = _EVENT_MEMBER_FOR_CODE.get(code)
    details = None
    if member_name is not None:
        d = layouts.event_members[member_name].unpack_from(data, packet.offset_of("m_eventDetails"))
        if member_name == "FastestLap":
            details = FastestLapDetails(vehicle_idx=d["vehicleIdx"], lap_time_s=d["lapTime"])
        else:
            details = FlashbackDetails(frame_identifier=d["flashbackFrameIdentifier"],
                                       session_time=d["flashbackSessionTime"])
    return Event(header=header, code=code, details=details)


def decode_name(raw: bytes) -> str:
    """UTF-8 up to the first null byte; the game may truncate names mid-character."""
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def _decode_participants(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> Participant | NoPlayerCar:
    idx = player_index(header, layouts)
    if idx is None:
        return NoPlayerCar(header, PacketId.PARTICIPANTS)
    packet = layouts.packets[PacketId.PARTICIPANTS]
    p = _player_car(data, packet, "m_participants", layouts.participant, idx)
    return Participant(
        header=header,
        num_active_cars=data[packet.offset_of("m_numActiveCars")],
        ai_controlled=bool(p["m_aiControlled"]),
        driver_id=p["m_driverId"],
        network_id=p["m_networkId"],
        team_id=p["m_teamId"],
        race_number=p["m_raceNumber"],
        nationality=p["m_nationality"],
        name=decode_name(p["m_name"]),
        your_telemetry_public=bool(p["m_yourTelemetry"]),
        platform=p["m_platform"],
    )


def _decode_car_telemetry(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> CarTelemetry | NoPlayerCar:
    idx = player_index(header, layouts)
    if idx is None:
        return NoPlayerCar(header, PacketId.CAR_TELEMETRY)
    packet = layouts.packets[PacketId.CAR_TELEMETRY]
    t = _player_car(data, packet, "m_carTelemetryData", layouts.car_telemetry, idx)
    suggested = struct.unpack_from("<b", data, packet.offset_of("m_suggestedGear"))[0]
    return CarTelemetry(
        header=header,
        speed_kph=t["m_speed"],
        throttle=t["m_throttle"],
        steer=t["m_steer"],
        brake=t["m_brake"],
        clutch=t["m_clutch"],
        gear=t["m_gear"],
        engine_rpm=t["m_engineRPM"],
        drs=bool(t["m_drs"]),
        rev_lights_percent=t["m_revLightsPercent"],
        engine_temperature=t["m_engineTemperature"],
        brakes_temperature=t["m_brakesTemperature"],
        tyres_surface_temperature=t["m_tyresSurfaceTemperature"],
        tyres_inner_temperature=t["m_tyresInnerTemperature"],
        tyres_pressure=t["m_tyresPressure"],
        surface_type=t["m_surfaceType"],
        suggested_gear=suggested,
    )


def _decode_car_status(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> CarStatus | NoPlayerCar:
    idx = player_index(header, layouts)
    if idx is None:
        return NoPlayerCar(header, PacketId.CAR_STATUS)
    s = _player_car(data, layouts.packets[PacketId.CAR_STATUS], "m_carStatusData", layouts.car_status, idx)
    return CarStatus(
        header=header,
        actual_compound=actual_compound(s["m_actualTyreCompound"]),
        visual_compound=visual_compound(s["m_visualTyreCompound"]),
        tyres_age_laps=s["m_tyresAgeLaps"],
        fia_flag=s["m_vehicleFIAFlags"],
        pit_limiter=bool(s["m_pitLimiterStatus"]),
        fuel_in_tank=s["m_fuelInTank"],
        fuel_remaining_laps=s["m_fuelRemainingLaps"],
        max_rpm=s["m_maxRPM"],
        drs_allowed=bool(s["m_drsAllowed"]),
        ers_store_energy=s["m_ersStoreEnergy"],
        ers_deploy_mode=s["m_ersDeployMode"],
        traction_control=s["m_tractionControl"],
        anti_lock_brakes=bool(s["m_antiLockBrakes"]),
    )


def _decode_motion_ex(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> MotionEx:
    m = layouts.packets[PacketId.MOTION_EX].unpack_from(data)
    return MotionEx(
        header=header,
        chassis_yaw=m["m_chassisYaw"],
        chassis_pitch=m["m_chassisPitch"],
        front_wheels_angle=m["m_frontWheelsAngle"],
        wheel_slip_ratio=m["m_wheelSlipRatio"],
        wheel_slip_angle=m["m_wheelSlipAngle"],
        local_velocity=(m["m_localVelocityX"], m["m_localVelocityY"], m["m_localVelocityZ"]),
        angular_velocity=(m["m_angularVelocityX"], m["m_angularVelocityY"], m["m_angularVelocityZ"]),
    )


def _decode_car_damage(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> CarDamage | NoPlayerCar:
    idx = player_index(header, layouts)
    if idx is None:
        return NoPlayerCar(header, PacketId.CAR_DAMAGE)
    d = _player_car(data, layouts.packets[PacketId.CAR_DAMAGE], "m_carDamageData", layouts.car_damage, idx)
    return CarDamage(
        header=header,
        tyres_wear=tuple(float(w) for w in d["m_tyresWear"]),  # type: ignore[arg-type]
        tyres_damage=d["m_tyresDamage"],
        brakes_damage=d["m_brakesDamage"],
        front_left_wing=d["m_frontLeftWingDamage"],
        front_right_wing=d["m_frontRightWingDamage"],
        rear_wing=d["m_rearWingDamage"],
        floor=d["m_floorDamage"],
        diffuser=d["m_diffuserDamage"],
        sidepod=d["m_sidepodDamage"],
        gearbox=d["m_gearBoxDamage"],
        engine=d["m_engineDamage"],
        drs_fault=bool(d["m_drsFault"]),
        ers_fault=bool(d["m_ersFault"]),
    )


# m_lapValidBitFlags: 0x01 lap valid, 0x02 sector 1 valid, 0x04 sector 2 valid, 0x08 sector 3 valid
def _lap_history(h: dict[str, Any]) -> LapHistory:
    flags = h["m_lapValidBitFlags"]
    return LapHistory(
        lap_time_ms=h["m_lapTimeInMS"],
        sector1_time_ms=_ms(h["m_sector1TimeMinutesPart"], h["m_sector1TimeMSPart"]),
        sector2_time_ms=_ms(h["m_sector2TimeMinutesPart"], h["m_sector2TimeMSPart"]),
        sector3_time_ms=_ms(h["m_sector3TimeMinutesPart"], h["m_sector3TimeMSPart"]),
        lap_valid=bool(flags & 0x01),
        sector1_valid=bool(flags & 0x02),
        sector2_valid=bool(flags & 0x04),
        sector3_valid=bool(flags & 0x08),
    )


def _decode_session_history(header: PacketHeader, data: Buffer,
                            layouts: FormatLayouts) -> SessionHistory | NoPlayerCar | None:
    idx = player_index(header, layouts)
    if idx is None:
        return NoPlayerCar(header, PacketId.SESSION_HISTORY)
    packet = layouts.packets[PacketId.SESSION_HISTORY]
    if data[packet.offset_of("m_carIdx")] != idx:
        return None  # history for another car (Time Trial cycles through ghosts too)
    s = packet.unpack_from(data)
    slots = tuple(_lap_history(h) for h in s["m_lapHistoryData"])
    num_stints = min(s["m_numTyreStints"], len(s["m_tyreStintsHistoryData"]))
    stints = tuple(
        TyreStint(end_lap=t["m_endLap"],
                  actual_compound=actual_compound(t["m_tyreActualCompound"]),
                  visual_compound=visual_compound(t["m_tyreVisualCompound"]))
        for t in s["m_tyreStintsHistoryData"][:num_stints]
    )
    return SessionHistory(
        header=header,
        car_idx=s["m_carIdx"],
        num_laps=min(s["m_numLaps"], len(slots)),
        best_lap_time_lap_num=s["m_bestLapTimeLapNum"],
        best_sector1_lap_num=s["m_bestSector1LapNum"],
        best_sector2_lap_num=s["m_bestSector2LapNum"],
        best_sector3_lap_num=s["m_bestSector3LapNum"],
        slots=slots,
        tyre_stints=stints,
    )


def _time_trial_set(t: dict[str, Any]) -> TimeTrialSet:
    return TimeTrialSet(
        car_idx=t["m_carIdx"],
        team_id=t["m_teamId"],
        lap_time_ms=t["m_lapTimeInMS"],
        sector1_time_ms=t["m_sector1TimeInMS"],
        sector2_time_ms=t["m_sector2TimeInMS"],
        sector3_time_ms=t["m_sector3TimeInMS"],
        traction_control=bool(t["m_tractionControl"]),
        gearbox_assist=bool(t["m_gearboxAssist"]),
        anti_lock_brakes=bool(t["m_antiLockBrakes"]),
        equal_car_performance=bool(t["m_equalCarPerformance"]),
        custom_setup=bool(t["m_customSetup"]),
        valid=bool(t["m_valid"]),
    )


def _decode_time_trial(header: PacketHeader, data: Buffer, layouts: FormatLayouts) -> TimeTrial:
    t = layouts.packets[PacketId.TIME_TRIAL].unpack_from(data)
    return TimeTrial(
        header=header,
        player_session_best=_time_trial_set(t["m_playerSessionBestDataSet"]),
        personal_best=_time_trial_set(t["m_personalBestDataSet"]),
        rival=_time_trial_set(t["m_rivalDataSet"]),
    )


_HANDLERS: dict[PacketId, Callable[[PacketHeader, Buffer, FormatLayouts], Any]] = {
    PacketId.MOTION: _decode_motion,
    PacketId.SESSION: _decode_session,
    PacketId.LAP_DATA: _decode_lap_data,
    PacketId.EVENT: _decode_event,
    PacketId.PARTICIPANTS: _decode_participants,
    PacketId.CAR_TELEMETRY: _decode_car_telemetry,
    PacketId.CAR_STATUS: _decode_car_status,
    PacketId.CAR_DAMAGE: _decode_car_damage,
    PacketId.MOTION_EX: _decode_motion_ex,
    PacketId.SESSION_HISTORY: _decode_session_history,
    PacketId.TIME_TRIAL: _decode_time_trial,
}
