"""Packet format 2025 layouts, transcribed from docs/F1_25_structures.txt.

Only the packets the hub decodes are laid out here; the others are size-checked from
sizes.DOCUMENTED_SIZES and dropped. tests/test_layouts_spec.py compares every layout in
this module field-for-field against the spec file.
"""

from __future__ import annotations

from .layout import Layout, Union

MAX_CARS = 22                  # cs_maxNumCarsInUDPData
MAX_PARTICIPANT_NAME_LEN = 32  # cs_maxParticipantNameLen
MAX_TYRE_STINTS = 8            # cs_maxTyreStints
MAX_MARSHAL_ZONES = 21         # cs_maxMarshalsZonePerLap
MAX_WEATHER_SAMPLES = 64       # cs_maxWeatherForecastSamples
MAX_SESSIONS_IN_WEEKEND = 12   # cs_maxSessionsInWeekend
MAX_LAPS_IN_HISTORY = 100      # cs_maxNumLapsInHistory
EVENT_STRING_CODE_LEN = 4      # cs_eventStringCodeLen

PacketHeader = Layout("PacketHeader", [
    ("uint16", "m_packetFormat"),
    ("uint8", "m_gameYear"),
    ("uint8", "m_gameMajorVersion"),
    ("uint8", "m_gameMinorVersion"),
    ("uint8", "m_packetVersion"),
    ("uint8", "m_packetId"),
    ("uint64", "m_sessionUID"),
    ("float", "m_sessionTime"),
    ("uint32", "m_frameIdentifier"),
    ("uint32", "m_overallFrameIdentifier"),
    ("uint8", "m_playerCarIndex"),
    ("uint8", "m_secondaryPlayerCarIndex"),
])

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
    ("float", "m_gForceLateral"),
    ("float", "m_gForceLongitudinal"),
    ("float", "m_gForceVertical"),
    ("float", "m_yaw"),
    ("float", "m_pitch"),
    ("float", "m_roll"),
])

PacketMotionData = Layout("PacketMotionData", [
    (PacketHeader, "m_header"),
    (CarMotionData, "m_carMotionData", MAX_CARS),
])

# --- Session (1) --------------------------------------------------------------
MarshalZone = Layout("MarshalZone", [
    ("float", "m_zoneStart"),
    ("int8", "m_zoneFlag"),
])

WeatherForecastSample = Layout("WeatherForecastSample", [
    ("uint8", "m_sessionType"),
    ("uint8", "m_timeOffset"),
    ("uint8", "m_weather"),
    ("int8", "m_trackTemperature"),
    ("int8", "m_trackTemperatureChange"),
    ("int8", "m_airTemperature"),
    ("int8", "m_airTemperatureChange"),
    ("uint8", "m_rainPercentage"),
])

# Fields common to the start of PacketSessionData in both formats (2026 appends more).
SESSION_FIELDS = [
    (PacketHeader, "m_header"),
    ("uint8", "m_weather"),
    ("int8", "m_trackTemperature"),
    ("int8", "m_airTemperature"),
    ("uint8", "m_totalLaps"),
    ("uint16", "m_trackLength"),
    ("uint8", "m_sessionType"),
    ("int8", "m_trackId"),
    ("uint8", "m_formula"),
    ("uint16", "m_sessionTimeLeft"),
    ("uint16", "m_sessionDuration"),
    ("uint8", "m_pitSpeedLimit"),
    ("uint8", "m_gamePaused"),
    ("uint8", "m_isSpectating"),
    ("uint8", "m_spectatorCarIndex"),
    ("uint8", "m_sliProNativeSupport"),
    ("uint8", "m_numMarshalZones"),
    (MarshalZone, "m_marshalZones", MAX_MARSHAL_ZONES),
    ("uint8", "m_safetyCarStatus"),
    ("uint8", "m_networkGame"),
    ("uint8", "m_numWeatherForecastSamples"),
    (WeatherForecastSample, "m_weatherForecastSamples", MAX_WEATHER_SAMPLES),
    ("uint8", "m_forecastAccuracy"),
    ("uint8", "m_aiDifficulty"),
    ("uint32", "m_seasonLinkIdentifier"),
    ("uint32", "m_weekendLinkIdentifier"),
    ("uint32", "m_sessionLinkIdentifier"),
    ("uint8", "m_pitStopWindowIdealLap"),
    ("uint8", "m_pitStopWindowLatestLap"),
    ("uint8", "m_pitStopRejoinPosition"),
    ("uint8", "m_steeringAssist"),
    ("uint8", "m_brakingAssist"),
    ("uint8", "m_gearboxAssist"),
    ("uint8", "m_pitAssist"),
    ("uint8", "m_pitReleaseAssist"),
    ("uint8", "m_ERSAssist"),
    ("uint8", "m_DRSAssist"),
    ("uint8", "m_dynamicRacingLine"),
    ("uint8", "m_dynamicRacingLineType"),
    ("uint8", "m_gameMode"),
    ("uint8", "m_ruleSet"),
    ("uint32", "m_timeOfDay"),
    ("uint8", "m_sessionLength"),
    ("uint8", "m_speedUnitsLeadPlayer"),
    ("uint8", "m_temperatureUnitsLeadPlayer"),
    ("uint8", "m_speedUnitsSecondaryPlayer"),
    ("uint8", "m_temperatureUnitsSecondaryPlayer"),
    ("uint8", "m_numSafetyCarPeriods"),
    ("uint8", "m_numVirtualSafetyCarPeriods"),
    ("uint8", "m_numRedFlagPeriods"),
    ("uint8", "m_equalCarPerformance"),
    ("uint8", "m_recoveryMode"),
    ("uint8", "m_flashbackLimit"),
    ("uint8", "m_surfaceType"),
    ("uint8", "m_lowFuelMode"),
    ("uint8", "m_raceStarts"),
    ("uint8", "m_tyreTemperature"),
    ("uint8", "m_pitLaneTyreSim"),
    ("uint8", "m_carDamage"),
    ("uint8", "m_carDamageRate"),
    ("uint8", "m_collisions"),
    ("uint8", "m_collisionsOffForFirstLapOnly"),
    ("uint8", "m_mpUnsafePitRelease"),
    ("uint8", "m_mpOffForGriefing"),
    ("uint8", "m_cornerCuttingStringency"),
    ("uint8", "m_parcFermeRules"),
    ("uint8", "m_pitStopExperience"),
    ("uint8", "m_safetyCar"),
    ("uint8", "m_safetyCarExperience"),
    ("uint8", "m_formationLap"),
    ("uint8", "m_formationLapExperience"),
    ("uint8", "m_redFlags"),
    ("uint8", "m_affectsLicenceLevelSolo"),
    ("uint8", "m_affectsLicenceLevelMP"),
    ("uint8", "m_numSessionsInWeekend"),
    ("uint8", "m_weekendStructure", MAX_SESSIONS_IN_WEEKEND),
    ("float", "m_sector2LapDistanceStart"),
    ("float", "m_sector3LapDistanceStart"),
]

PacketSessionData = Layout("PacketSessionData", SESSION_FIELDS)

# --- Lap Data (2) -------------------------------------------------------------
LapData = Layout("LapData", [
    ("uint32", "m_lastLapTimeInMS"),
    ("uint32", "m_currentLapTimeInMS"),
    ("uint16", "m_sector1TimeMSPart"),
    ("uint8", "m_sector1TimeMinutesPart"),
    ("uint16", "m_sector2TimeMSPart"),
    ("uint8", "m_sector2TimeMinutesPart"),
    ("uint16", "m_deltaToCarInFrontMSPart"),
    ("uint8", "m_deltaToCarInFrontMinutesPart"),
    ("uint16", "m_deltaToRaceLeaderMSPart"),
    ("uint8", "m_deltaToRaceLeaderMinutesPart"),
    ("float", "m_lapDistance"),
    ("float", "m_totalDistance"),
    ("float", "m_safetyCarDelta"),
    ("uint8", "m_carPosition"),
    ("uint8", "m_currentLapNum"),
    ("uint8", "m_pitStatus"),
    ("uint8", "m_numPitStops"),
    ("uint8", "m_sector"),
    ("uint8", "m_currentLapInvalid"),
    ("uint8", "m_penalties"),
    ("uint8", "m_totalWarnings"),
    ("uint8", "m_cornerCuttingWarnings"),
    ("uint8", "m_numUnservedDriveThroughPens"),
    ("uint8", "m_numUnservedStopGoPens"),
    ("uint8", "m_gridPosition"),
    ("uint8", "m_driverStatus"),
    ("uint8", "m_resultStatus"),
    ("uint8", "m_pitLaneTimerActive"),
    ("uint16", "m_pitLaneTimeInLaneInMS"),
    ("uint16", "m_pitStopTimerInMS"),
    ("uint8", "m_pitStopShouldServePen"),
    ("float", "m_speedTrapFastestSpeed"),
    ("uint8", "m_speedTrapFastestLap"),
])

PacketLapData = Layout("PacketLapData", [
    (PacketHeader, "m_header"),
    (LapData, "m_lapData", MAX_CARS),
    ("uint8", "m_timeTrialPBCarIdx"),
    ("uint8", "m_timeTrialRivalCarIdx"),
])

# --- Event (3) ----------------------------------------------------------------
FastestLap = Layout("FastestLap", [("uint8", "vehicleIdx"), ("float", "lapTime")])
Retirement = Layout("Retirement", [("uint8", "vehicleIdx"), ("uint8", "reason")])
DRSDisabled = Layout("DRSDisabled", [("uint8", "reason")])
TeamMateInPits = Layout("TeamMateInPits", [("uint8", "vehicleIdx")])
RaceWinner = Layout("RaceWinner", [("uint8", "vehicleIdx")])
Penalty = Layout("Penalty", [
    ("uint8", "penaltyType"),
    ("uint8", "infringementType"),
    ("uint8", "vehicleIdx"),
    ("uint8", "otherVehicleIdx"),
    ("uint8", "time"),
    ("uint8", "lapNum"),
    ("uint8", "placesGained"),
])
SpeedTrap = Layout("SpeedTrap", [
    ("uint8", "vehicleIdx"),
    ("float", "speed"),
    ("uint8", "isOverallFastestInSession"),
    ("uint8", "isDriverFastestInSession"),
    ("uint8", "fastestVehicleIdxInSession"),
    ("float", "fastestSpeedInSession"),
])
StartLights = Layout("StartLights", [("uint8", "numLights")])
DriveThroughPenaltyServed = Layout("DriveThroughPenaltyServed", [("uint8", "vehicleIdx")])
StopGoPenaltyServed = Layout("StopGoPenaltyServed", [("uint8", "vehicleIdx"), ("float", "stopTime")])
Flashback = Layout("Flashback", [("uint32", "flashbackFrameIdentifier"), ("float", "flashbackSessionTime")])
Buttons = Layout("Buttons", [("uint32", "buttonStatus")])
Overtake = Layout("Overtake", [("uint8", "overtakingVehicleIdx"), ("uint8", "beingOvertakenVehicleIdx")])
SafetyCar = Layout("SafetyCar", [("uint8", "safetyCarType"), ("uint8", "eventType")])
Collision = Layout("Collision", [("uint8", "vehicle1Idx"), ("uint8", "vehicle2Idx")])

EVENT_MEMBERS = {
    layout.name: layout
    for layout in (FastestLap, Retirement, DRSDisabled, TeamMateInPits, RaceWinner, Penalty,
                   SpeedTrap, StartLights, DriveThroughPenaltyServed, StopGoPenaltyServed,
                   Flashback, Buttons, Overtake, SafetyCar, Collision)
}

EventDataDetails = Union("EventDataDetails", EVENT_MEMBERS)

PacketEventData = Layout("PacketEventData", [
    (PacketHeader, "m_header"),
    ("uint8", "m_eventStringCode", EVENT_STRING_CODE_LEN),
    (EventDataDetails, "m_eventDetails"),
])

# --- Participants (4) ---------------------------------------------------------
LiveryColour = Layout("LiveryColour", [("uint8", "red"), ("uint8", "green"), ("uint8", "blue")])

ParticipantData = Layout("ParticipantData", [
    ("uint8", "m_aiControlled"),
    ("uint8", "m_driverId"),
    ("uint8", "m_networkId"),
    ("uint8", "m_teamId"),
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

# --- Car Telemetry (6) --------------------------------------------------------
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
    ("uint16", "m_engineTemperature"),
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

# --- Car Status (7) -----------------------------------------------------------
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
    ("float", "m_ersDeployedThisLap"),
    ("uint8", "m_networkPaused"),
])

PacketCarStatusData = Layout("PacketCarStatusData", [
    (PacketHeader, "m_header"),
    (CarStatusData, "m_carStatusData", MAX_CARS),
])

# --- Session History (11) -----------------------------------------------------
LapHistoryData = Layout("LapHistoryData", [
    ("uint32", "m_lapTimeInMS"),
    ("uint16", "m_sector1TimeMSPart"),
    ("uint8", "m_sector1TimeMinutesPart"),
    ("uint16", "m_sector2TimeMSPart"),
    ("uint8", "m_sector2TimeMinutesPart"),
    ("uint16", "m_sector3TimeMSPart"),
    ("uint8", "m_sector3TimeMinutesPart"),
    ("uint8", "m_lapValidBitFlags"),
])

TyreStintHistoryData = Layout("TyreStintHistoryData", [
    ("uint8", "m_endLap"),
    ("uint8", "m_tyreActualCompound"),
    ("uint8", "m_tyreVisualCompound"),
])

PacketSessionHistoryData = Layout("PacketSessionHistoryData", [
    (PacketHeader, "m_header"),
    ("uint8", "m_carIdx"),
    ("uint8", "m_numLaps"),
    ("uint8", "m_numTyreStints"),
    ("uint8", "m_bestLapTimeLapNum"),
    ("uint8", "m_bestSector1LapNum"),
    ("uint8", "m_bestSector2LapNum"),
    ("uint8", "m_bestSector3LapNum"),
    (LapHistoryData, "m_lapHistoryData", MAX_LAPS_IN_HISTORY),
    (TyreStintHistoryData, "m_tyreStintsHistoryData", MAX_TYRE_STINTS),
])

# --- Time Trial (14) ----------------------------------------------------------
TimeTrialDataSet = Layout("TimeTrialDataSet", [
    ("uint8", "m_carIdx"),
    ("uint8", "m_teamId"),
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
