"""Packet format 2026 layouts, transcribed from docs/F1_2026_SeasonPack_structures.txt.

Structs identical to 2025 are reused from f2025; tests/test_layouts_spec.py still checks
every layout here against the 2026 spec file. Differences that matter to us:
24 cars, quantised int16 g-force, uint16 driver/network/team IDs, uint8 engine temp,
extra ERS float in CarStatusData, larger session packet, collision severity.
"""

from __future__ import annotations

from . import f2025
from .f2025 import (  # noqa: F401  (unchanged in 2026; re-exported so both modules look alike)
    EVENT_STRING_CODE_LEN,
    LapData,
    LapHistoryData,
    LiveryColour,
    MAX_PARTICIPANT_NAME_LEN,
    PacketHeader,
    PacketSessionHistoryData,
    SESSION_FIELDS,
    TyreStintHistoryData,
)
from .layout import Layout, Union

MAX_CARS = 24                   # cs_maxNumCarsInUDPData
MAX_ACTIVE_AERO_ZONES = 8       # cs_maxActiveAeroZonesPerLap
MAX_DRS_ZONES = 4               # cs_maxDRSZonesPerLap

# "For quantised g-Force values, divide the value by 1000.0f to get the actual value"
GFORCE_QUANTISATION = 1000.0

# --- Motion (0) ---------------------------------------------------------------
CarMotionData = Layout("CarMotionData", [
    ("float", "m_worldPositionX"),
    ("float", "m_worldPositionY"),
    ("float", "m_worldPositionZ"),
    ("float", "m_worldVelocityX"),
    ("float", "m_worldVelocityY"),
    ("float", "m_worldVelocityZ"),
    ("int16", "m_worldForwardDirX"),
    ("int16", "m_worldForwardDirY"),
    ("int16", "m_worldForwardDirZ"),
    ("int16", "m_worldRightDirX"),
    ("int16", "m_worldRightDirY"),
    ("int16", "m_worldRightDirZ"),
    ("int16", "m_gForceLateral"),
    ("int16", "m_gForceLongitudinal"),
    ("int16", "m_gForceVertical"),
    ("float", "m_yaw"),
    ("float", "m_pitch"),
    ("float", "m_roll"),
])

PacketMotionData = Layout("PacketMotionData", [
    (PacketHeader, "m_header"),
    (CarMotionData, "m_carMotionData", MAX_CARS),
])

# --- Session (1) --------------------------------------------------------------
MarshalZone = f2025.MarshalZone
WeatherForecastSample = f2025.WeatherForecastSample

ActiveAeroZone = Layout("ActiveAeroZone", [("float", "m_zoneStart"), ("float", "m_zoneEnd")])
DRSZone = Layout("DRSZone", [("float", "m_zoneStart"), ("float", "m_zoneEnd")])

PacketSessionData = Layout("PacketSessionData", SESSION_FIELDS + [
    ("uint8", "m_activeAeroTrackStatus"),
    ("uint8", "m_numActiveAeroZonesFull"),
    (ActiveAeroZone, "m_activeAeroZonesFull", MAX_ACTIVE_AERO_ZONES),
    ("uint8", "m_numActiveAeroZonesPartial"),
    (ActiveAeroZone, "m_activeAeroZonesPartial", MAX_ACTIVE_AERO_ZONES),
    ("uint8", "m_numDRSZones"),
    (DRSZone, "m_drsZones", MAX_DRS_ZONES),
    ("float", "m_startReactionTime"),
    ("uint8", "m_antiLockBrakesAssist"),
    ("uint8", "m_tractionControlAssist"),
    ("uint8", "m_dynamicRacingLineHiVis"),
    ("uint8", "m_dynamicRacingLineColourBlind"),
    ("uint8", "m_recurringRewindPrompt"),
])

# --- Lap Data (2): per-car struct unchanged, array is 24 ----------------------
PacketLapData = Layout("PacketLapData", [
    (PacketHeader, "m_header"),
    (LapData, "m_lapData", MAX_CARS),
    ("uint8", "m_timeTrialPBCarIdx"),
    ("uint8", "m_timeTrialRivalCarIdx"),
])

# --- Event (3): Collision gains severity --------------------------------------
Collision = Layout("Collision", [
    ("uint8", "vehicle1Idx"),
    ("uint8", "vehicle2Idx"),
    ("uint8", "severity"),
])

EVENT_MEMBERS = {**f2025.EVENT_MEMBERS, "Collision": Collision}
FastestLap = EVENT_MEMBERS["FastestLap"]
Flashback = EVENT_MEMBERS["Flashback"]

EventDataDetails = Union("EventDataDetails", EVENT_MEMBERS)

PacketEventData = Layout("PacketEventData", [
    (PacketHeader, "m_header"),
    ("uint8", "m_eventStringCode", EVENT_STRING_CODE_LEN),
    (EventDataDetails, "m_eventDetails"),
])

# --- Participants (4): driver/network/team IDs widened to uint16 ---------------
ParticipantData = Layout("ParticipantData", [
    ("uint8", "m_aiControlled"),
    ("uint16", "m_driverId"),
    ("uint16", "m_networkId"),
    ("uint16", "m_teamId"),
    ("uint8", "m_myTeam"),
    ("uint8", "m_raceNumber"),
    ("uint8", "m_nationality"),
    ("char", "m_name", MAX_PARTICIPANT_NAME_LEN),
    ("uint8", "m_yourTelemetry"),
    ("uint8", "m_showOnlineNames"),
    ("uint16", "m_techLevel"),
    ("uint8", "m_platform"),
    ("uint8", "m_numColours"),
    (LiveryColour, "m_liveryColours", 4),
])

PacketParticipantsData = Layout("PacketParticipantsData", [
    (PacketHeader, "m_header"),
    ("uint8", "m_numActiveCars"),
    (ParticipantData, "m_participants", MAX_CARS),
])

# --- Car Telemetry (6): engine temperature is uint8 ---------------------------
CarTelemetryData = Layout("CarTelemetryData", [
    ("uint16", "m_speed"),
    ("float", "m_throttle"),
    ("float", "m_steer"),
    ("float", "m_brake"),
    ("uint8", "m_clutch"),
    ("int8", "m_gear"),
    ("uint16", "m_engineRPM"),
    ("uint8", "m_drs"),
    ("uint8", "m_revLightsPercent"),
    ("uint16", "m_revLightsBitValue"),
    ("uint16", "m_brakesTemperature", 4),
    ("uint8", "m_tyresSurfaceTemperature", 4),
    ("uint8", "m_tyresInnerTemperature", 4),
    ("uint8", "m_engineTemperature"),
    ("float", "m_tyresPressure", 4),
    ("uint8", "m_surfaceType", 4),
])

PacketCarTelemetryData = Layout("PacketCarTelemetryData", [
    (PacketHeader, "m_header"),
    (CarTelemetryData, "m_carTelemetryData", MAX_CARS),
    ("uint8", "m_mfdPanelIndex"),
    ("uint8", "m_mfdPanelIndexSecondaryPlayer"),
    ("int8", "m_suggestedGear"),
])

# --- Car Status (7): ersHarvestLimitPerLap inserted before ersDeployedThisLap ---
CarStatusData = Layout("CarStatusData", [
    ("uint8", "m_tractionControl"),
    ("uint8", "m_antiLockBrakes"),
    ("uint8", "m_fuelMix"),
    ("uint8", "m_frontBrakeBias"),
    ("uint8", "m_pitLimiterStatus"),
    ("float", "m_fuelInTank"),
    ("float", "m_fuelCapacity"),
    ("float", "m_fuelRemainingLaps"),
    ("uint16", "m_maxRPM"),
    ("uint16", "m_idleRPM"),
    ("uint8", "m_maxGears"),
    ("uint8", "m_drsAllowed"),
    ("uint16", "m_drsActivationDistance"),
    ("uint8", "m_actualTyreCompound"),
    ("uint8", "m_visualTyreCompound"),
    ("uint8", "m_tyresAgeLaps"),
    ("int8", "m_vehicleFIAFlags"),
    ("float", "m_enginePowerICE"),
    ("float", "m_enginePowerMGUK"),
    ("float", "m_ersStoreEnergy"),
    ("uint8", "m_ersDeployMode"),
    ("float", "m_ersHarvestedThisLapMGUK"),
    ("float", "m_ersHarvestedThisLapMGUH"),
    ("float", "m_ersHarvestLimitPerLap"),
    ("float", "m_ersDeployedThisLap"),
    ("uint8", "m_networkPaused"),
])

PacketCarStatusData = Layout("PacketCarStatusData", [
    (PacketHeader, "m_header"),
    (CarStatusData, "m_carStatusData", MAX_CARS),
])

# --- Motion Ex (13): unchanged (player car only, no per-car array) ------------
PacketMotionExData = f2025.PacketMotionExData

# --- Car Damage (10): per-car struct unchanged, array is 24 --------------------
CarDamageData = f2025.CarDamageData

PacketCarDamageData = Layout("PacketCarDamageData", [
    (PacketHeader, "m_header"),
    (CarDamageData, "m_carDamageData", MAX_CARS),
])

# --- Time Trial (14): teamId is uint16 ----------------------------------------
TimeTrialDataSet = Layout("TimeTrialDataSet", [
    ("uint8", "m_carIdx"),
    ("uint16", "m_teamId"),
    ("uint", "m_lapTimeInMS"),
    ("uint", "m_sector1TimeInMS"),
    ("uint", "m_sector2TimeInMS"),
    ("uint", "m_sector3TimeInMS"),
    ("uint8", "m_tractionControl"),
    ("uint8", "m_gearboxAssist"),
    ("uint8", "m_antiLockBrakes"),
    ("uint8", "m_equalCarPerformance"),
    ("uint8", "m_customSetup"),
    ("uint8", "m_valid"),
])

PacketTimeTrialData = Layout("PacketTimeTrialData", [
    (PacketHeader, "m_header"),
    (TimeTrialDataSet, "m_playerSessionBestDataSet"),
    (TimeTrialDataSet, "m_personalBestDataSet"),
    (TimeTrialDataSet, "m_rivalDataSet"),
])
