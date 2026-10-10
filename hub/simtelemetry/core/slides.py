"""Slide meter and "SAVE!" detection from the car's slide angle (chassis yaw vs direction of travel).

A slide starts when the car is at least SLIDE_START_DEG sideways at speed, and ends once it has been
back under SLIDE_END_DEG for SETTLE_S. It was a save when the peak was big (SAVE_MIN_DEG or more),
it wasn't a spin (peak under SPIN_DEG), it was caught within MAX_SAVE_S and the car is still moving.
Times are game session time (seconds), so replays give the same result.
"""

from __future__ import annotations

from dataclasses import dataclass

SLIDE_START_DEG = 8.0
SLIDE_END_DEG = 3.0
SETTLE_S = 0.25
SAVE_MIN_DEG = 15.0
SPIN_DEG = 70.0
MAX_SAVE_S = 3.0
MIN_SPEED_KPH = 60.0
MIN_END_SPEED_KPH = 40.0


@dataclass(frozen=True, slots=True)
class Save:
    peak_deg: float
    duration_s: float


@dataclass(slots=True)
class SlideDetector:
    sliding: bool = False
    started: float = 0.0
    peak: float = 0.0
    calm_since: float | None = None

    def update(self, t: float, slide_deg: float, speed_kph: float | None) -> Save | None:
        """Feed one sample; returns a Save when a caught slide just ended."""
        angle = abs(slide_deg)
        speed = speed_kph or 0.0
        if t < self.started:  # game time went back (flashback, restart): drop any slide in progress
            self.sliding = False
        if not self.sliding:
            if angle >= SLIDE_START_DEG and speed >= MIN_SPEED_KPH:
                self.sliding, self.started, self.peak, self.calm_since = True, t, angle, None
            return None
        self.peak = max(self.peak, angle)
        if angle >= SLIDE_END_DEG:
            self.calm_since = None
            if t - self.started > MAX_SAVE_S + 2:  # a long slide (spin or drift): give up on it
                self.sliding = False
            return None
        if self.calm_since is None:
            self.calm_since = t
            return None
        if t - self.calm_since < SETTLE_S:
            return None
        self.sliding = False
        duration = self.calm_since - self.started
        if SAVE_MIN_DEG <= self.peak < SPIN_DEG and duration <= MAX_SAVE_S and speed >= MIN_END_SPEED_KPH:
            return Save(round(self.peak, 1), round(duration, 2))
        return None
