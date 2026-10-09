"""Packet pipeline: receive -> record -> check -> queue -> decode -> registry/health."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import AppConfig
from .core.adapter import Checked, GameAdapter
from .core.health import HealthMonitor, RigState
from .core.laps import LapBook, LapContext
from .core.rigs import Rig, RigRegistry
from .tools.recorder import Recorder

log = logging.getLogger(__name__)

QUEUE_MAX = 20_000  # ~10 rigs x 60 Hz x 6 packets for >5 s of backlog
DROP_QUEUE_FULL = "queue_full"


class Hub:
    def __init__(self, config: AppConfig, adapter: GameAdapter, registry: RigRegistry,
                 recorder: Recorder | None = None) -> None:
        self.config = config
        self.adapter = adapter
        self.registry = registry
        self.health = HealthMonitor(config.health)
        self.recorder = recorder
        self.laps = LapBook(outline_display=config.map.model_dump())
        self.started_at = time.monotonic()
        self._queue: asyncio.Queue[tuple[Checked, bytes, str, float]] = asyncio.Queue(QUEUE_MAX)

    # --- receive path (sync, called from datagram_received) -------------------------

    def on_datagram(self, data: bytes, source_ip: str, wall_time: float) -> None:
        if self.recorder is not None:
            self.recorder.write(wall_time, source_ip, data)
        now = time.monotonic()
        checked = self.adapter.check(data, source_ip)
        self.registry.see(source_ip, now, checked.data_format, checked.session_id)
        if not checked.ok:
            self.health.on_drop(source_ip, checked.reason or "rejected", now)
            return
        try:
            self._queue.put_nowait((checked, data, source_ip, now))
        except asyncio.QueueFull:
            self.health.on_drop(source_ip, DROP_QUEUE_FULL, now)

    # --- background tasks ------------------------------------------------------------

    async def consume(self) -> None:
        while True:
            checked, data, ip, received = await self._queue.get()
            try:
                result = self.adapter.decode(checked, data, ip)
            except Exception:  # a bad packet must never stop the pipeline
                log.exception("Decoder failed on %s packet from %s", checked.label, ip)
                self.health.on_drop(ip, "decode_error", received)
                continue
            self.health.on_packet(ip, checked.label or "?", received, result.driving)
            summary = self.adapter.live_summary(ip)
            if summary is not None:
                self.registry.set_driver_name(ip, summary.driver_name)
            if result.lap_events or result.lap_update:
                self.laps.update(ip, self.lap_context(ip), self.adapter.live_lap(ip), result.lap_events)

    def lap_context(self, ip: str) -> LapContext:
        rig = self.registry.get(ip)
        s = self.adapter.live_summary(ip)
        return LapContext(
            rig_name=rig.name if rig else ip,
            driver=rig.driver_name if rig else None,
            track_key=s.track_key if s else None,
            track_name=s.track if s else None,
            session_id=rig.session_id if rig else None,
            tyre=tyre_dict(s),
            position=s.position if s else None,
            track_length_m=s.track_length_m if s else None,
            sector_starts_m=s.sector_starts_m if s else None,
        )

    async def drain(self) -> None:
        """Wait until every queued packet has been decoded (used after a replay)."""
        while not self._queue.empty():
            await asyncio.sleep(0.02)
        await asyncio.sleep(0)  # let the consumer finish the last item

    async def tick_health(self) -> None:
        interval = self.config.health.summary_interval_s
        next_summary = time.monotonic() + interval
        while True:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            self.health.tick(now)
            if now >= next_summary:
                next_summary = now + interval
                for line in self.summary_lines(now):
                    log.info("%s", line)

    # --- views -----------------------------------------------------------------------

    def _active_formats(self, now: float) -> dict[str, str]:
        return {
            rig.ip: rig.data_format
            for rig in self.registry.all()
            if rig.data_format and self.health.state(rig.ip, now) is not RigState.NO_DATA
        }

    def health_snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        formats = self._active_formats(now)
        rigs = []
        for rig in self.registry.all():
            h = self.health.get(rig.ip)
            summary = self.adapter.live_summary(rig.ip)
            rigs.append({
                "ip": rig.ip,
                "name": rig.name,
                "auto_name": rig.auto_name,
                "config_name": rig.config_name,
                "colour": rig.colour,
                "state": self.health.state(rig.ip, now).value,
                "data_format": rig.data_format,
                "format_supported": rig.data_format is None or self.adapter.is_supported_format(rig.data_format),
                "session_id": rig.session_id,
                "driver_name": rig.driver_name,
                "track": summary.track if summary else None,
                "last_seen_s_ago": round(now - h.last_seen, 2) if h and h.last_seen is not None else None,
                "packets_per_s": round(h.total_rate, 1) if h else 0.0,
                "rates": {k: round(v, 1) for k, v in sorted(h.rates.items())} if h else {},
                "packets_total": sum(h.totals.values()) if h else 0,
                "drops": dict(h.drops) if h else {},
            })
        return {
            "game": self.adapter.game,
            "uptime_s": round(now - self.started_at, 1),
            "udp_port": self.config.network.udp_port,
            "format_mismatch": len(set(formats.values())) > 1,
            "formats": formats,
            # Path of the file being written, None when not recording (disabled or stopped).
            "recording": str(self.recorder.current_path) if self.recorder and not self.recorder.stopped else None,
            # Recorder state incl. "recording stopped: low disk"; None when recording is disabled.
            "recorder": self.recorder.status() if self.recorder else None,
            "rigs": rigs,
        }

    def summary_lines(self, now: float) -> list[str]:
        lines = []
        recorder_line = self.recorder.summary_line() if self.recorder else None
        if recorder_line:
            lines.append(recorder_line)
        formats = self._active_formats(now)
        if len(set(formats.values())) > 1:
            lines.append("WARNING: rigs are sending different packet formats: "
                         + ", ".join(f"{ip}={fmt}" for ip, fmt in formats.items()))
        for rig in self.registry.all():
            h = self.health.get(rig.ip)
            state = self.health.state(rig.ip, now)
            if h is None:
                lines.append(f"{rig.name:<8} {rig.ip:<15} {state.value}")
                continue
            top = " ".join(f"{k}={v:.0f}" for k, v in sorted(h.rates.items()) if v >= 0.5)
            drops = ", ".join(f"{k}={v}" for k, v in sorted(h.drops.items())) or "none"
            lines.append(f"{rig.name:<8} {rig.ip:<15} fmt={rig.data_format or '?'} {state.value:<15} "
                         f"{h.total_rate:5.0f} pkt/s [{top}] drops: {drops}")
        return lines

    def listen_line(self, rig: Rig, now: float) -> str:
        state = self.health.state(rig.ip, now).value
        s = self.adapter.live_summary(rig.ip)
        lap = f"lap {s.lap}" if s and s.lap is not None else "lap -"
        lap_time = format_lap_time(s.current_lap_ms) if s and s.current_lap_ms is not None else "--:--.---"
        speed = f"{s.speed_kph:3d} km/h" if s and s.speed_kph is not None else "  - km/h"
        track = (s.track if s and s.track else "track ?")
        return (f"{rig.name:<8} {rig.ip:<15} fmt={rig.data_format or '?':<5} {track:<22} "
                f"{lap:<7} {lap_time} {speed} {state}")


def tyre_dict(s) -> dict[str, Any] | None:
    """Schema Tyre from a LiveSummary, or None while unknown."""
    if s is None or s.tyre_class is None:
        return None
    return {"compound": s.tyre_class, "label": s.tyre_label or s.tyre_class, "age_laps": s.tyre_age_laps}


def format_lap_time(ms: int) -> str:
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}:{rest // 1000:02d}.{rest % 1000:03d}"
