"""Demo simulator: virtual rigs that send real F1 25 (2025 format) UDP packets into the hub.

Used by `run --demo`. The packets go through the same pipeline as a real game's (packet gate, decoder, lap
tracker, lap book), so the demo shows real outlines, laps, records, head to head and story cards. Each rig
drives a synthetic circuit (a smooth closed curve with a grip-limited speed profile) at its own pace, with a
little driving style, the odd invalid lap and, for some rigs, every assist off (Pro laps).
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..adapters.f1.formats import FORMATS
from ..adapters.f1.sizes import PacketId

if TYPE_CHECKING:
    from ..hub import Hub

TRACK_ID = 7                     # shows as DEMO_TRACK_NAME (the demo config overrides the name)
DEMO_TRACK_NAME = "Demo Circuit"
TICK_HZ = 20
LAYOUTS = FORMATS[2025]
GAME_NAMES = ["Apex_Hunter", "LateBraker77", "Sofia_K", "TurboTom", "Mika H", "DRS_Daisy"]
PACES = [0.995, 0.982, 0.99, 0.986, 0.978, 0.992]
PRO = [True, False, True, False, False, False]  # every assist off on these rigs
DEMO_RIGS = 6                    # simulated rigs in `run --demo` (its fallback licence covers them all)


def rig_ip(n: int) -> str:
    return f"10.20.0.{n}"


# --- the circuit (same construction as the dashboard's mock track) ---------------------------------

@dataclass
class Circuit:
    points: list[tuple[float, float]]
    cum: list[float]
    length: float
    speed: list[float]                # reference speed at each point, m/s

    @classmethod
    def build(cls, n: int = 720, target_m: float = 5200.0) -> "Circuit":
        raw = []
        for i in range(n):
            t = 2 * math.pi * i / n
            r = (1 + 0.18 * math.sin(2 * t + 0.4) + 0.1 * math.sin(3 * t + 1.3) + 0.08 * math.sin(6 * t + 0.7)
                 + 0.05 * math.sin(9 * t + 2.1) + 0.035 * math.sin(13 * t + 0.3))
            raw.append((r * math.cos(t), 0.62 * r * math.sin(t)))
        raw_len = sum(math.dist(raw[i], raw[(i + 1) % n]) for i in range(n))
        pts = [(x * target_m / raw_len, z * target_m / raw_len) for x, z in raw]
        cum = [0.0]
        for i in range(1, n):
            cum.append(cum[-1] + math.dist(pts[i - 1], pts[i]))
        length = cum[-1] + math.dist(pts[-1], pts[0])

        def curvature(a, b, c):
            area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
            d = math.dist(a, b) * math.dist(b, c) * math.dist(a, c)
            return 2 * area2 / d if d > 0 else 0.0

        kappa = [curvature(pts[(i - 2) % n], pts[i], pts[(i + 2) % n]) for i in range(n)]
        smooth = [sum(kappa[(i + k) % n] for k in range(-3, 4)) / 7 for i in range(n)]
        speed = [min(92.0, max(20.0, math.sqrt(20.0 / max(k, 1e-6)))) for k in smooth]
        for _ in range(2):
            for j in range(1, n + 1):
                i, prev = j % n, j - 1
                speed[i] = min(speed[i], math.sqrt(speed[prev] ** 2 + 2 * 11.0 * math.dist(pts[prev], pts[i])))
            for j in range(n - 1, -1, -1):
                nxt = (j + 1) % n
                speed[j] = min(speed[j], math.sqrt(speed[nxt] ** 2 + 2 * 38.0 * math.dist(pts[j], pts[nxt])))
        return cls(pts, cum, length, speed)

    def sample(self, d: float) -> tuple[float, float, float, float]:
        """x, z, reference speed and heading (radians) at distance d into the lap."""
        d %= self.length
        lo, hi = 0, len(self.cum) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.cum[mid] <= d:
                lo = mid
            else:
                hi = mid - 1
        j = (lo + 1) % len(self.points)
        seg_end = self.length if j == 0 else self.cum[j]
        k = (d - self.cum[lo]) / (seg_end - self.cum[lo]) if seg_end > self.cum[lo] else 0.0
        (ax, az), (bx, bz) = self.points[lo], self.points[j]
        return (ax + (bx - ax) * k, az + (bz - az) * k, self.speed[lo] + (self.speed[j] - self.speed[lo]) * k,
                math.atan2(bz - az, bx - ax))


# --- one virtual rig ------------------------------------------------------------------------------

@dataclass
class VirtualRig:
    n: int
    name: str
    pace: float
    pro: bool
    uid: int
    distance: float
    rng: random.Random
    lap: int = 1
    lap_ms: float = 0.0
    last_ms: int = 0
    speed: float = 25.0
    prev_speed: float = 25.0
    valid: bool = True
    invalid_at: float | None = None
    splits: list[int] = field(default_factory=list)
    history: list[tuple[int, int, int, int, bool]] = field(default_factory=list)
    lap_pace: float = 1.0
    session_time: float = 0.0
    frame: int = 0
    tyre_age: int = 0

    @property
    def ip(self) -> str:
        return rig_ip(self.n)

    def step(self, circuit: Circuit, dt: float) -> None:
        self.session_time += dt
        self.frame += 1
        angle = max(0.0, self.distance) / circuit.length * 2 * math.pi
        style = 1 + 0.014 * math.sin(angle * 3 + self.n * 1.9)
        target = circuit.sample(self.distance)[2] * self.pace * self.lap_pace * style
        self.prev_speed = self.speed
        self.speed += (target - self.speed) * min(1.0, dt / 0.25)
        before = self.distance
        self.distance += self.speed * dt
        self.lap_ms += dt * 1000
        if self.valid and self.invalid_at is not None and self.distance >= self.invalid_at:
            self.valid = False
        for k, boundary in enumerate((circuit.length / 3, 2 * circuit.length / 3)):
            if len(self.splits) == k and before < boundary <= self.distance:
                self.splits.append(round(self.lap_ms - (self.distance - boundary) / self.speed * 1000))
        if self.distance >= circuit.length:
            over = self.distance - circuit.length
            lap_ms = round(self.lap_ms - over / self.speed * 1000)
            s1 = self.splits[0] if self.splits else lap_ms // 3
            s2 = (self.splits[1] if len(self.splits) > 1 else 2 * lap_ms // 3) - s1
            self.history.append((lap_ms, s1, s2, lap_ms - s1 - s2, self.valid and self.lap > 1))
            self.last_ms = lap_ms
            self.lap += 1
            self.tyre_age += 1
            self.distance = over
            self.lap_ms = over / self.speed * 1000
            self.splits = []
            self.valid = True
            self.invalid_at = self.rng.random() * circuit.length if self.rng.random() < 0.15 else None
            self.lap_pace = 1 + (self.rng.random() - 0.5) * 0.012

    # --- packets ----------------------------------------------------------------------------

    def _header(self, packet_id: PacketId) -> dict[str, Any]:
        return {"m_packetFormat": 2025, "m_gameYear": 25, "m_gameMajorVersion": 1, "m_gameMinorVersion": 0,
                "m_packetVersion": 1, "m_packetId": int(packet_id), "m_sessionUID": self.uid,
                "m_sessionTime": self.session_time, "m_frameIdentifier": self.frame,
                "m_overallFrameIdentifier": self.frame, "m_playerCarIndex": 0, "m_secondaryPlayerCarIndex": 255}

    def _packet(self, packet_id: PacketId, body: dict[str, Any]) -> bytes:
        return LAYOUTS.packets[packet_id].pack({"m_header": self._header(packet_id), **body})

    def packets(self, circuit: Circuit, tick: int) -> list[bytes]:
        x, z, _, heading = circuit.sample(self.distance)
        kph = self.speed * 3.6
        accel = (self.speed - self.prev_speed) * TICK_HZ           # m/s^2
        braking = accel < -3
        gear = next((g + 1 for g, top in enumerate((90, 130, 165, 200, 235, 270, 300)) if kph < top), 8)
        throttle = 0.0 if braking else 1.0 if accel > 1 else 0.55
        brake = min(1.0, -accel / 30) if braking else 0.0
        curve = math.sin(self.distance / 140)
        out = [
            self._packet(PacketId.MOTION, {"m_carMotionData": [{
                "m_worldPositionX": x, "m_worldPositionZ": z,
                "m_gForceLateral": curve * 3.2, "m_gForceLongitudinal": max(-4.5, min(1.2, accel / 9.81)),
                "m_yaw": heading}]}),
            self._packet(PacketId.LAP_DATA, {"m_lapData": [{
                "m_lastLapTimeInMS": self.last_ms, "m_currentLapTimeInMS": round(self.lap_ms),
                "m_sector1TimeMSPart": (self.splits[0] % 60000) if self.splits else 0,
                "m_sector1TimeMinutesPart": (self.splits[0] // 60000) if self.splits else 0,
                "m_sector2TimeMSPart": ((self.splits[1] - self.splits[0]) % 60000) if len(self.splits) > 1 else 0,
                "m_sector2TimeMinutesPart": ((self.splits[1] - self.splits[0]) // 60000) if len(self.splits) > 1 else 0,
                "m_lapDistance": self.distance, "m_totalDistance": self.distance + (self.lap - 1) * circuit.length,
                "m_carPosition": 1, "m_currentLapNum": self.lap, "m_sector": min(2, len(self.splits)),
                "m_currentLapInvalid": int(not self.valid), "m_driverStatus": 3 if self.lap == 1 else 1,
                "m_resultStatus": 2}], "m_timeTrialPBCarIdx": 255, "m_timeTrialRivalCarIdx": 255}),
            self._packet(PacketId.CAR_TELEMETRY, {"m_carTelemetryData": [{
                "m_speed": round(kph), "m_throttle": throttle, "m_brake": brake, "m_steer": curve * 0.6,
                "m_gear": gear, "m_engineRPM": min(12900, 7000 + round((kph % 45) * 130)),
                "m_drs": int(kph > 285), "m_revLightsPercent": min(100, round((kph % 45) * 2.2)),
                "m_brakesTemperature": [520 + (300 if braking else 0)] * 4,
                "m_tyresSurfaceTemperature": [92, 94, 98, 99], "m_tyresInnerTemperature": [96, 97, 101, 101],
                "m_tyresPressure": [21.4, 21.5, 23.1, 23.2]}], "m_suggestedGear": 0}),
        ]
        if tick % 5 == 0:
            out.append(self._packet(PacketId.CAR_STATUS, {"m_carStatusData": [{
                "m_tractionControl": 0 if self.pro else 2, "m_antiLockBrakes": 0 if self.pro else 1,
                "m_fuelInTank": max(2.0, 18 - (self.lap % 10) * 1.6), "m_fuelRemainingLaps": 4.5 - (self.lap % 10) * 0.4,
                "m_maxRPM": 13000, "m_idleRPM": 4000, "m_maxGears": 8, "m_drsAllowed": 1,
                "m_actualTyreCompound": 18, "m_visualTyreCompound": 16, "m_tyresAgeLaps": self.tyre_age,
                "m_ersStoreEnergy": 2.4e6 + 1.2e6 * math.sin(self.distance / 600), "m_ersDeployMode": 2,
                "m_vehicleFIAFlags": 0}]}))
            out.append(self._packet(PacketId.CAR_DAMAGE, {"m_carDamageData": [{
                "m_tyresWear": [min(60.0, self.tyre_age * 2.4)] * 4}]}))
        if tick % TICK_HZ == 0:
            length = round(circuit.length)
            out.append(self._packet(PacketId.SESSION, {
                "m_weather": 1, "m_trackTemperature": 31, "m_airTemperature": 23, "m_trackLength": length,
                "m_sessionType": 18, "m_trackId": TRACK_ID, "m_formula": 0, "m_sessionTimeLeft": 3600,
                "m_sessionDuration": 3600, "m_gameMode": 0, "m_ruleSet": 0,
                "m_sector2LapDistanceStart": circuit.length / 3, "m_sector3LapDistanceStart": 2 * circuit.length / 3,
                "m_steeringAssist": 0, "m_brakingAssist": 0 if self.pro else 1, "m_gearboxAssist": 1 if self.pro else 3,
                "m_dynamicRacingLine": 0 if self.pro else 2}))
            out.append(self._packet(PacketId.PARTICIPANTS, {"m_numActiveCars": 1, "m_participants": [{
                "m_aiControlled": 0, "m_name": self.name.encode()[:47], "m_showOnlineNames": 1}]}))
            laps = [*self.history[-99:], (0, 0, 0, 0, True)]  # the last entry is the lap in progress
            best = min(range(len(laps) - 1), key=lambda i: laps[i][0], default=None)
            out.append(self._packet(PacketId.SESSION_HISTORY, {
                "m_carIdx": 0, "m_numLaps": len(laps), "m_numTyreStints": 1,
                "m_bestLapTimeLapNum": (best + 1) if best is not None else 0,
                "m_lapHistoryData": [{
                    "m_lapTimeInMS": ms, "m_sector1TimeMSPart": s1 % 60000, "m_sector1TimeMinutesPart": s1 // 60000,
                    "m_sector2TimeMSPart": s2 % 60000, "m_sector2TimeMinutesPart": s2 // 60000,
                    "m_sector3TimeMSPart": s3 % 60000, "m_sector3TimeMinutesPart": s3 // 60000,
                    "m_lapValidBitFlags": 0x0F if ok else 0x0E} for ms, s1, s2, s3, ok in laps],
                "m_tyreStintsHistoryData": [{"m_endLap": 255, "m_tyreActualCompound": 18, "m_tyreVisualCompound": 16}]}))
        return out


class DemoSimulator:
    """Drives `rigs` virtual rigs into the hub at 20 Hz until cancelled."""

    def __init__(self, hub: Hub, rigs: int = DEMO_RIGS, seed: int = 11) -> None:
        self.hub = hub
        self.circuit = Circuit.build()
        rng = random.Random(seed)
        self.rigs = [VirtualRig(n=i + 1, name=GAME_NAMES[i % len(GAME_NAMES)], pace=PACES[i % len(PACES)],
                                pro=PRO[i % len(PRO)], uid=rng.getrandbits(63), distance=-150.0,
                                rng=random.Random(seed + i))
                     for i in range(max(1, min(len(GAME_NAMES), rigs)))]
        # Spread the cars round the circuit, each part-way through its out lap, so the map isn't one bunch.
        for i, rig in enumerate(self.rigs):
            rig.distance = self.circuit.length * i / (len(self.rigs) + 1) + rng.uniform(0, 150)
            rig.lap_ms = rig.distance / 55.0 * 1000
        self.tick = 0

    def step(self, dt: float = 1 / TICK_HZ) -> None:
        now = time.time()
        for rig in self.rigs:
            rig.step(self.circuit, dt)
            for data in rig.packets(self.circuit, self.tick):
                self.hub.on_datagram(data, rig.ip, now)
        self.tick += 1

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        due = loop.time()
        while True:
            due += 1 / TICK_HZ
            await asyncio.sleep(max(0.0, due - loop.time()))
            self.step()
