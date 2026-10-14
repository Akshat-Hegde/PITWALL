"""Demo director: trigger each broadcast moment on demand while filming (`run --demo` only).

The staff page shows a Director panel in demo mode. Every action goes through the hub's own moment and
session code, so what the TV shows is exactly what a real event would look like.
"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Any

from ..core.drivers import DriverError
from .demo_sim import TRACK_ID, DemoSimulator

if TYPE_CHECKING:
    from ..hub import Hub

TRACK_KEY = f"F1:{TRACK_ID}"
ACTIONS = ("now_driving", "record", "battle", "podium", "challenge_winner", "card", "race")


class DemoDirector:
    def __init__(self, hub: Hub, sim: DemoSimulator, seed: int = 5) -> None:
        self.hub = hub
        self.sim = sim
        self.rng = random.Random(seed)
        profiles = [d for d in hub.drivers.store.search_drivers_by_name("", limit=500) if d["phone"]]
        self.profiles = profiles or [hub.drivers.create_quick_profile(n) for n in ("Maya R", "Kofi M", "Rosa V")]
        self._next = 0

    def _profile(self) -> dict[str, Any]:
        p = self.profiles[self._next % len(self.profiles)]
        self._next += 1
        return p

    def start_sessions(self) -> None:
        """Every simulated rig starts with a driver profile and a booking (no moments at start-up)."""
        for rig in self.sim.rigs:
            self.hub.drivers.assign(rig.ip, driver_id=self._profile()["id"], minutes=self.rng.choice([20, 30, 45]))

    def run(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        if action not in ACTIONS:
            raise DriverError(f"Unknown action. Choose one of: {', '.join(ACTIONS)}.")
        return getattr(self, action)(body)

    # --- actions -----------------------------------------------------------------------------

    def now_driving(self, body: dict[str, Any]) -> dict[str, Any]:
        rig = self.rng.choice(self.sim.rigs)
        self.hub.drivers.assign(rig.ip, driver_id=self._profile()["id"], minutes=30)
        self.hub.session_started(rig.ip)
        return {"shown": "now_driving", "rig": rig.ip}

    def record(self, body: dict[str, Any]) -> dict[str, Any]:
        period = body.get("period") if body.get("period") in ("today", "all_time") else "today"
        lap_class = body.get("lap_class") if body.get("lap_class") in ("pro", "open") else "open"
        laps = self.hub.laps
        holder = laps.record_holder(TRACK_KEY, period, lap_class) or laps.record_holder(TRACK_KEY, period)
        previous_ms = holder["lap_ms"] if holder else 87_500
        previous = (holder["driver"] or holder["rig_name"]) if holder else "Maya R"
        rig = self.rng.choice(self.sim.rigs)
        session = self.hub.drivers.get(rig.ip)
        lap_ms = previous_ms - self.rng.randint(80, 600)
        records = [{"period": period, "lap_class": lap_class, "previous_ms": previous_ms,
                    "previous_driver": previous, "gap_ms": lap_ms - previous_ms}]
        if period == "all_time":
            records.append({**records[0], "period": "today"})
        laps.publish_moment("record", rig_id=rig.ip, driver=session.name if session else rig.name,
                            track_key=TRACK_KEY, track_name=self.hub.config.track_names.get(TRACK_ID),
                            lap_ms=lap_ms, lap_class=lap_class, records=records)
        return {"shown": "record", "period": period, "lap_class": lap_class}

    def battle(self, body: dict[str, Any]) -> dict[str, Any]:
        a, b = self.rng.sample(self.sim.rigs, 2)
        names = [(self.hub.drivers.get(r.ip).name if self.hub.drivers.get(r.ip) else r.name) for r in (a, b)]
        gap = self.rng.randint(20, 280)
        self.hub.laps.publish_moment("battle", rig_ids=[a.ip, b.ip], drivers=names, title="Close fight",
                                     text=f"+{gap / 1000:.3f} apart on best laps")
        return {"shown": "battle"}

    def podium(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.hub.podium("staff") is None:
            raise DriverError("No clean laps today yet: give the rigs a minute.")
        return {"shown": "podium"}

    def challenge_winner(self, body: dict[str, Any]) -> dict[str, Any]:
        c = self.hub.competitions.current_challenge()
        if c is None:
            raise DriverError("No challenge in the demo data.")
        winner = c["entries"][0] if c["entries"] else {"rank": 1, "driver": "Maya R", "lap_ms": 87_400, "gap_ms": 0}
        self.hub.laps.publish_moment("challenge_winner", challenge_id=c["id"], title=c["title"],
                                     track_name=c["track_name"], lap_class=c["lap_class"], prize=c["prize"],
                                     winner=winner, runners_up=c["entries"][1:3])
        return {"shown": "challenge_winner"}

    def card(self, body: dict[str, Any]) -> dict[str, Any]:
        """End a session whose driver has a clean lap (a real story card and QR), then start the next driver."""
        for rig in self.rng.sample(self.sim.rigs, len(self.sim.rigs)):
            session = self.hub.drivers.get(rig.ip)
            if session is None:
                continue
            laps = [r for r in self.hub.laps.laps
                    if r.rig_id == rig.ip and r.counted and r.completed_at >= session.started_at]
            if not laps:
                continue
            card = self.hub.end_session(rig.ip)
            self.hub.drivers.assign(rig.ip, driver_id=self._profile()["id"], minutes=30)
            if card:
                return {"shown": "card", "url": card["url"], "token": card["token"]}
        raise DriverError("No driver has finished a clean lap in this session yet: give it two or three minutes.")

    def race(self, body: dict[str, Any]) -> dict[str, Any]:
        """A 4-rig race ends: every rig reports its result, so the TV shows the race podium and 'Grab your card'."""
        from ..core.adapter import RaceFinished
        from ..core.races import RACE_SETTLE_S
        rigs = self.sim.rigs[:4]
        if len(rigs) < 2:
            raise DriverError("The demo needs at least two rigs for a race.")
        order = list(range(1, len(rigs) + 1))
        self.rng.shuffle(order)
        now = time.monotonic()
        base = 5 * 87.0 + self.rng.uniform(0, 8)
        grid = self.rng.sample(range(1, 21), len(rigs))
        for rig, pos, grid_pos in zip(rigs, order, grid):
            self.hub.races.add(rig.ip, RaceFinished(
                track_key=TRACK_KEY, session_type="Race", session_uid=f"demo{self.rng.getrandbits(32):08x}",
                position=pos, grid_position=grid_pos, laps=5,
                best_lap_ms=87_000 + pos * 90 + self.rng.randint(0, 300), total_time_s=base + pos * 3.7,
                penalties_s=0, status="finished", num_cars=20), now)
        done = self.hub.settle_races(now + RACE_SETTLE_S + 1)
        if not done or done[0]["moment"] is None:
            raise DriverError("Race podium is switched off ([features] sharing / race_podium).")
        return {"shown": "race_podium", "drivers": len(rigs)}
