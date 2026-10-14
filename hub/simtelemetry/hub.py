"""Packet pipeline: receive -> record -> check -> queue -> decode -> registry/health."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from pathlib import Path
from typing import Any

from . import paths
from .config import AppConfig
from .core.adapter import Checked, GameAdapter
from .core.health import HealthMonitor, RigState
from .core.drivers import DriverRegistry
from .core.laps import LapBook, LapContext, driver_key
from .core.store import LapStore
from .core.races import RaceBook
from .core.rigs import Rig, RigRegistry
from .tools.recorder import Recorder

log = logging.getLogger(__name__)

QUEUE_MAX = 20_000  # ~10 rigs x 60 Hz x 6 packets for >5 s of backlog
DROP_QUEUE_FULL = "queue_full"


def next_backup_at(now: dt.datetime, hour: int) -> dt.datetime:
    """The next local `hour`:00 strictly after `now`."""
    at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return at if at > now else at + dt.timedelta(days=1)


CATCH_UP_AFTER = dt.timedelta(hours=24)
CATCH_UP_DELAY_S = 120.0


def catch_up_due(last_at_ms: int | None, now: dt.datetime) -> bool:
    """True when there is no backup yet or the newest is over 24 h old (the PC was off at the backup hour)."""
    if last_at_ms is None:
        return True
    return now - dt.datetime.fromtimestamp(last_at_ms / 1000) > CATCH_UP_AFTER


class Hub:
    def __init__(self, config: AppConfig, adapter: GameAdapter, registry: RigRegistry,
                 recorder: Recorder | None = None, store: LapStore | None = None,
                 bundled_outlines: dict[str, dict[str, Any]] | None = None,
                 config_path: Path | None = None) -> None:
        self.config = config
        self.config_path = config_path or paths.config_path()   # the hub.toml actually loaded (for backups)
        self.adapter = adapter
        self.registry = registry
        self.health = HealthMonitor(config.health)
        self.recorder = recorder
        self.laps = LapBook(outline_display=config.map.model_dump(), store=store,
                            day_start_hour=config.leaderboard.day_start_hour, bundled_outlines=bundled_outlines)
        self.drivers = DriverRegistry(store)
        self.races = RaceBook()
        from .core.checkin import CheckinService
        self.checkin = CheckinService(self)
        from .core.tv import TvControl
        self.tv = TvControl(config.data_dir / "tv.json" if store is not None and store.path is not None else None)
        from .core.competitions import Competitions
        self.competitions = Competitions(self.drivers.store, config.data_dir, config.leaderboard.day_start_hour)
        # Other programs listening on the telemetry port on a specific address (see net/udp.py).
        self.port_shadows: list[str] = []
        self._session_top_kph: dict[str, int] = {}             # top speed per rig in the staff session
        self.demo = None                                        # DemoDirector in `run --demo`
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
                if summary.speed_kph and self.drivers.get(ip) is not None:
                    self._session_top_kph[ip] = max(self._session_top_kph.get(ip, 0), summary.speed_kph)
            self.note_race_participant(ip, received)
            if result.race_results:
                for finished in result.race_results:
                    self.races.add(ip, finished, received)
                self.settle_races(received)
            if result.lap_events or result.lap_update:
                try:
                    self.laps.update(ip, self.lap_context(ip), self.adapter.live_lap(ip), result.lap_events)
                except Exception:  # lap tracking must never stop the packet pipeline
                    log.exception("Lap tracking failed on %s packet from %s", checked.label, ip)

    def lap_context(self, ip: str) -> LapContext:
        rig = self.registry.get(ip)
        s = self.adapter.live_summary(ip)
        rig_name = rig.name if rig else ip
        return LapContext(
            rig_name=rig_name,
            driver=self.drivers.lap_name(ip, rig.driver_name if rig else None, rig_name),
            track_key=s.track_key if s else None,
            track_name=s.track if s else None,
            session_id=rig.session_id if rig else None,
            tyre=tyre_dict(s),
            position=s.position if s else None,
            track_length_m=s.track_length_m if s else None,
            sector_starts_m=s.sector_starts_m if s else None,
            pro=s.pro if s else None,
            driver_id=self.drivers.driver_id(ip),
            throttle=s.throttle if s else None,
            brake=s.brake if s else None,
            g_lat=s.g_lat if s else None,
        )

    # --- broadcast moments -----------------------------------------------------------

    def active_track(self, now: float | None = None) -> str | None:
        """The track the TV shows: the one most rigs are on, driving rigs counting double."""
        now = time.monotonic() if now is None else now
        counts: dict[str, int] = {}
        for rig in self.registry.all():
            state = self.health.state(rig.ip, now)
            s = self.adapter.live_summary(rig.ip)
            if state is RigState.NO_DATA or s is None or not s.track_key:
                continue
            counts[s.track_key] = counts.get(s.track_key, 0) + (2 if state is RigState.DRIVING else 1)
        return max(counts, key=lambda k: (counts[k], k)) if counts else None

    def rig_label(self, rig_id: str) -> str:
        """A rig's name for people ("Rig 1" or its configured name), never its address unless nothing else is known:
        the registry first, then the name stored with its laps."""
        rig = self.registry.get(rig_id)
        if rig is not None:
            return rig.name
        return self.drivers.store.rig_names().get(rig_id) or rig_id

    def session_top_speed(self, ip: str) -> int | None:
        return self._session_top_kph.get(ip)

    def session_started(self, ip: str) -> None:
        """Staff started a session on a rig: reset its session stats and show 'now driving'."""
        self._session_top_kph.pop(ip, None)
        self.announce_driver(ip)

    def end_session(self, ip: str) -> dict[str, Any] | None:
        """End the staff session on a rig; returns the story card (None without a counted lap or sharing off)."""
        from .core.cards import build_card
        from .core.feed import lan_address
        session = self.drivers.get(ip)
        if session is None:
            return None
        self.drivers.end(ip)
        return self.session_card(ip, session)

    def session_card(self, ip: str, session: Any) -> dict[str, Any] | None:
        """Story card for a session that has just ended (ended by staff, or replaced by the next driver)."""
        from .core.cards import build_card
        from .core.feed import lan_address
        if not self.config.features.sharing:
            return None
        ended_at = round(time.time() * 1000)
        try:
            card = build_card(self, ip, session, ended_at)
        except Exception:  # a card must never stop a session from ending
            log.exception("Could not make the story card for %s", ip)
            return None
        self._session_top_kph.pop(ip, None)
        if card is None:
            return None
        self.drivers.save_card(ip, session.driver_id, card)
        url = f"http://{lan_address() or 'localhost'}:{self.config.network.http_port}/card/{card['token']}"
        self.laps.publish_moment("card", rig_id=ip, driver=card["driver"], token=card["token"], url=url,
                                 best_ms=card["best_ms"], track_name=card["track_name"])
        self.checkin.card_made(ip, session.started_at, url)   # the guest's phone can fetch it later
        return {**card, "url": url}

    # --- race podium -------------------------------------------------------------------

    def note_race_participant(self, ip: str, now: float) -> None:
        """A rig in a race session on a known track is a participant (even on its results screen)."""
        from .adapters.f1.adapter import RACE_SESSIONS
        s = self.adapter.live_summary(ip)
        if s is not None and s.session_type in RACE_SESSIONS and s.track_key:
            self.races.note_racing(ip, s.track_key, now)

    def settle_races(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.monotonic() if now is None else now
        done = []
        for race in self.races.due(now):
            try:
                done.append(self.finish_race(race))
            except Exception:  # a race must never stop the packet pipeline
                log.exception("Could not publish the race on %s", race.track_key)
        return done

    def race_track_name(self, race: Any) -> str | None:
        for rig, _ in race.results:
            s = self.adapter.live_summary(rig)
            if s is not None and s.track_key == race.track_key and s.track:
                return s.track
        try:
            return self.config.track_names.get(int(race.track_key.split(":", 1)[1]))
        except (IndexError, ValueError):
            return None

    def finish_race(self, race: Any) -> dict[str, Any]:
        """Race cards for every rig that finished, plus the podium moment when 2 or more cafe drivers raced."""
        from .core.cards import build_race_card
        from .core.feed import lan_address
        from .core.wifi import wifi_share
        features = self.config.features
        race.track_name = race.track_name or self.race_track_name(race)
        if not (features.sharing and features.race_podium):
            return {"cards": [], "moment": None}
        base = f"http://{lan_address() or 'localhost'}:{self.config.network.http_port}/card/"
        cards = []
        for rig, result in race.results:
            card = build_race_card(self, rig, result, race)
            if card is None:
                continue
            self.drivers.save_card(rig, self.drivers.driver_id(rig), card)
            cards.append((rig, result, card))
        moment = None
        if len(cards) == 1:
            rig, result, card = cards[0]
            self.laps.publish_moment("card", rig_id=rig, driver=card["driver"], token=card["token"],
                                     url=base + card["token"], best_ms=card["best_ms"],
                                     track_name=card["track_name"], card_kind="race", position=card["position"])
        elif cards:
            moment = self.laps.publish_moment(
                "race_podium", track_key=race.track_key, track_name=race.track_name,
                session_type=race.session_type,
                drivers=[{"rank": i, "position": res.position, "driver": card["driver"], "rig_id": rig,
                          "grid_position": res.grid_position, "laps": res.laps, "best_lap_ms": res.best_lap_ms,
                          "total_time_s": res.total_time_s, "status": res.status,
                          "card_url": base + card["token"], "card_token": card["token"]}
                         for i, (rig, res, card) in enumerate(cards, 1)],
                wifi=wifi_share(self.config))
        return {"cards": [c for _, _, c in cards], "moment": moment}

    async def tick_races(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                self.settle_races()
            except Exception:
                log.exception("Race check failed")

    def announce_driver(self, ip: str) -> dict[str, Any] | None:
        """'Now driving' moment when staff start a session on a rig."""
        if not self.config.features.moments:
            return None
        rig = self.registry.get(ip)
        s = self.adapter.live_summary(ip)
        assigned = self.drivers.get(ip)
        if rig is None or assigned is None:
            return None
        track_key = (s.track_key if s else None) or self.active_track()
        record = self.laps.record_holder(track_key, "today") if track_key else None
        best = self.laps.driver_best(track_key, driver_key(assigned.name, ip, assigned.driver_id)) if track_key else None
        return self.laps.publish_moment(
            "now_driving", rig_id=ip, rig_name=rig.name, driver=assigned.name, track_key=track_key,
            track_name=(s.track if s else None) or (record or {}).get("track_name"),
            today_record=({"driver": record["driver"] or record["rig_name"], "lap_ms": record["lap_ms"]}
                          if record else None),
            personal_best_ms=best["lap_ms"] if best else None)

    def podium(self, reason: str) -> dict[str, Any] | None:
        """Podium moment: today's top three on the shown track ("hourly" or "staff")."""
        track_key = self.active_track()
        if not self.config.features.podium or track_key is None:
            return None
        since = self.laps.period_starts()["today"]
        board = self.laps.board(track_key, "today", since, limit=3)
        if not board["entries"]:
            return None
        return self.laps.publish_moment("podium", reason=reason, track_key=track_key,
                                        track_name=board["track_name"], entries=board["entries"])

    async def tick_podium(self, clock=time.time) -> None:
        """Podium at the end of every [moments] podium_every_min minutes on the wall clock."""
        last_slot: int | None = None
        while True:
            await asyncio.sleep(5.0)
            every = self.config.moments.podium_every_min
            if every <= 0:
                continue
            slot = int(clock() // 60) // every
            if last_slot is not None and slot != last_slot:
                self.podium("hourly" if every == 60 else "scheduled")
            last_slot = slot

    def announce_challenge_winners(self) -> list[dict[str, Any]]:
        """'Challenge winner' moments for challenges that have just ended."""
        if not self.config.features.challenges:
            return []
        out = []
        for c in self.competitions.due_winners():
            winner = c["entries"][0] if c["entries"] else None
            out.append(self.laps.publish_moment(
                "challenge_winner", challenge_id=c["id"], title=c["title"], track_name=c["track_name"],
                lap_class=c["lap_class"], prize=c["prize"], winner=winner, runners_up=c["entries"][1:3]))
        return out

    async def tick_competitions(self) -> None:
        while True:
            await asyncio.sleep(15.0)
            try:
                self.announce_challenge_winners()
            except Exception:
                log.exception("Challenge winner check failed")

    def run_backup(self, now: dt.datetime | None = None):
        """One backup now plus pruning; returns the zip path. Blocking: call from a thread."""
        from .core.backup import make_backup, prune
        cfg = self.config
        out = make_backup(cfg.data_dir, self.config_path, cfg.backups_dir, now or dt.datetime.now())
        prune(cfg.backups_dir, cfg.backup.keep)
        return out

    async def backup_loop(self) -> None:
        """Back up every night at [backup] hour, plus one shortly after start if the last is over a day old
        (a PC that is off at the backup hour would otherwise never back up). Never ends the hub."""
        from .core.backup import last_backup
        try:
            last = last_backup(self.config.backups_dir)
            due = catch_up_due(last["at"] if last else None, dt.datetime.now())
        except Exception:
            log.exception("Could not check the last backup")
            due = False
        if due:
            await asyncio.sleep(CATCH_UP_DELAY_S)
            await self._backup_once("Catch-up backup")
        while True:
            at = next_backup_at(dt.datetime.now(), self.config.backup.hour)
            await asyncio.sleep(max(1.0, (at - dt.datetime.now()).total_seconds()))
            await self._backup_once("Backup")

    async def _backup_once(self, label: str) -> None:
        try:
            out = await asyncio.to_thread(self.run_backup)
            log.info("%s saved: %s", label, out)
        except Exception:
            log.exception("%s failed (will try again tomorrow)", label)

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


def personal_best_key(hub: Hub, rig: Rig) -> str:
    """Driver key under which this rig's current laps are stored (see DriverRegistry.lap_name)."""
    return driver_key(hub.drivers.lap_name(rig.ip, rig.driver_name, rig.name), rig.ip, hub.drivers.driver_id(rig.ip))


def tyre_dict(s) -> dict[str, Any] | None:
    """Schema Tyre from a LiveSummary, or None while unknown."""
    if s is None or s.tyre_class is None:
        return None
    return {"compound": s.tyre_class, "label": s.tyre_label or s.tyre_class, "age_laps": s.tyre_age_laps}


def format_lap_time(ms: int) -> str:
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}:{rest // 1000:02d}.{rest % 1000:03d}"
