"""Packet pipeline: receive -> record -> check -> queue -> decode -> registry/health."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import brand, licence, paths
from .adapters import game_id as adapter_game_id
from .config import AppConfig, FeaturesConfig
from .core.adapter import Checked, GameAdapter
from .core.health import HealthMonitor, RigState, SilentRigWatch
from .core.drivers import DriverRegistry
from .core.laps import LapBook, LapContext, driver_key
from .core.store import LapStore
from .core.races import RaceBook
from .core.rigs import Rig, RigError, RigRegistry
from .tools.recorder import Recorder

log = logging.getLogger(__name__)

QUEUE_MAX = 20_000  # ~10 rigs x 60 Hz x 6 packets for >5 s of backlog
DROP_QUEUE_FULL = "queue_full"
DROP_GAME_NOT_LICENSED = "game_not_licensed"
NOT_LICENSED = "Not licensed"          # the staff page's mark on a rig beyond the licensed rig count
GAME_LINE_SHOW_S = 60.0                # a rig sending a game the licence doesn't include stays on Health this long
WRONG_SENDER_SHOW_S = 60.0   # a non-rig sending wrong-format packets is listed on staff Health this long
WRONG_SENDERS_MAX = 64      # addresses tracked at once; more (a flood of garbage) are ignored
WRONG_SENDER_LOGS_PER_MIN = 10   # "wrong format" log lines for new senders per minute (a flood gets none)


def next_backup_at(now: dt.datetime, hour: int) -> dt.datetime:
    """The next local `hour`:00 strictly after `now`."""
    at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return at if at > now else at + dt.timedelta(days=1)


AUTO_END_IDLE_S = 300.0      # a timed session over its time ends once the rig hasn't been DRIVING this long
AUTO_END_EVERY_S = 15.0      # how often open sessions are checked for auto-end
AUTO_END_TEXT = {"closing": "Ended automatically at closing time", "overrun": "Ended automatically: time was up"}
NO_CARD_TEXT = "No card this time: no clean lap was completed."

OWN_ADDRESSES_CACHE_S = 60.0     # how long this PC's own addresses are reused (the phone test)

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
                            day_start_hour=config.day_start_hour, bundled_outlines=bundled_outlines)
        self.drivers = DriverRegistry(store)
        self.races = RaceBook()
        from .core.checkin import CheckinService
        self.checkin = CheckinService(self)
        from .core.tv import TvControl
        self.tv = TvControl(config.data_dir / "tv.json" if store is not None and store.path is not None else None)
        from .core.competitions import Competitions
        self.competitions = Competitions(self.drivers.store, config.data_dir, config.day_start_hour)
        # Other programs listening on the telemetry port on a specific address (see net/udp.py).
        self.port_shadows: list[str] = []
        # Problems found at start-up (hub.toml, settings.json, laps.db): staff and setup pages only, never the TV.
        self.startup_warnings: list[dict[str, Any]] = []
        # Set up with 0.4 or before and the setup page not saved since: sessions now end at closing time, so the
        # staff and setup pages remind the owner to check the opening hours until the setup page is saved.
        self.settings_from_older_version = False
        self.udp_busy: str | None = None    # set while another program holds the telemetry port (retried)
        self._session_top_kph: dict[str, int] = {}             # top speed per rig in the staff session
        self.demo = None                                        # DemoDirector in `run --demo`
        self.started_at = time.monotonic()
        from .core.address import ADDRESS_FILE, AddressWatch
        persist = store is not None and store.path is not None
        self.address_watch = AddressWatch(config.data_dir / ADDRESS_FILE if persist else None, self.hub_address)
        from .core.phone_test import PHONE_TEST_FILE, PhoneTest
        self.phone_test = PhoneTest(config.data_dir / PHONE_TEST_FILE if persist else None)   # /hello visits
        self._own_addresses: tuple[float, set[str]] | None = None     # (looked up at, addresses), see own_addresses
        from .core.backup import STATUS_FILE, BackupStatus, first_use_time, last_backup
        try:
            found = last_backup(config.backups_dir)
        except OSError:                                # a USB stick that is slow or gone: decided later
            found = None
        self.backup_status = BackupStatus(config.data_dir / STATUS_FILE if persist else None,
                                          first_use=first_use_time(config.data_dir, time.time()) if persist else None,
                                          seed_last_ok=found["at"] / 1000 if found else None)
        self.silent_watch = SilentRigWatch()
        self.wall_clock = dt.datetime.now                       # opening hours (tests replace it)
        # Addresses sending packets the hub can't read that never sent a valid one: ip -> (last seen, format).
        self.wrong_senders: dict[str, tuple[float, str | None]] = {}
        # The last session on each rig that ended automatically (shown on the staff page until the next one starts).
        self.auto_ended: dict[str, dict[str, Any]] = {}
        # Ending a session (staff End, auto-end, check-in takeover, the next driver) is one at a time, and each
        # session's card is made once: rig -> (session start, card) for the last session carded on that rig.
        self._end_lock = threading.RLock()
        self._carded: dict[str, tuple[int, dict[str, Any] | None]] = {}
        from .core.pins import PinAttempts
        self.pin_attempts = PinAttempts()          # wrong PINs on the staff, owner and setup pages
        self._wrong_log_window: tuple[float, int] | None = None     # (window start, lines logged in it)
        self._queue: asyncio.Queue[tuple[Checked, bytes, str, float]] = asyncio.Queue(QUEUE_MAX)
        # Licence (spec 2.2): the fallback until load_licence() runs at start-up (tests and replays keep it).
        self._entitlements: licence.Entitlements = licence.FALLBACK
        self.licence_problem: str | None = None       # "missing" / "damaged": staff, setup and owner pages say so
        self._licence_lock = threading.RLock()      # re-entrant: a hook may read or re-apply the licence
        # Called with the new entitlements whenever they change (start-up load, a new code): enforcement hooks.
        self.entitlement_hooks: list[Callable[[licence.Entitlements], None]] = []
        # Bumped when every TV must get a fresh snapshot (a new licence): see FeedConnection.tick.
        self.feed_epoch = 0
        # Enforcement (spec 2.3), kept up to date by _apply_entitlements (an entitlement hook, on the event loop):
        self._licensed_features: frozenset[str] = frozenset(licence.FALLBACK.features)
        self._game_allowed = True                   # this adapter's game is in the licence (checked per packet)
        self.unlicensed_game_senders: dict[str, float] = {}   # ip -> last packet of a game the licence lacks
        self.laps.tv_hidden = self.tv_hidden_rigs   # record moments compare with the boards the TV shows
        self.entitlement_hooks.append(self._apply_entitlements)
        self._apply_entitlements(self._entitlements)

    # --- receive path (sync, called from datagram_received) -------------------------

    def on_datagram(self, data: bytes, source_ip: str, wall_time: float) -> None:
        if self.recorder is not None:
            self.recorder.write(wall_time, source_ip, data)
        now = time.monotonic()
        checked = self.adapter.check(data, source_ip)
        if not checked.ok:
            # Only a valid packet makes a rig: wrong-format and garbage senders are listed on staff Health instead.
            if self.registry.get(source_ip) is not None:
                self.registry.note_format(source_ip, checked.data_format)
                self.health.on_drop(source_ip, checked.reason or "rejected", now)
            elif self.note_wrong_sender(source_ip, checked.data_format, now):
                self.health.on_drop(source_ip, checked.reason or "rejected", now)   # bounded like wrong_senders
            return
        self.registry.see(source_ip, now, checked.data_format, checked.session_id)
        self.wrong_senders.pop(source_ip, None)
        if not self._game_allowed:
            # A game the licence doesn't include: the rig is listed (staff Health says why), nothing is decoded.
            self.unlicensed_game_senders[source_ip] = now
            self.health.on_drop(source_ip, DROP_GAME_NOT_LICENSED, now)
            return
        try:
            self._queue.put_nowait((checked, data, source_ip, now))
        except asyncio.QueueFull:
            self.health.on_drop(source_ip, DROP_QUEUE_FULL, now)

    def note_wrong_sender(self, ip: str, data_format: str | None, now: float) -> bool:
        """Track an address that sends packets the hub can't read and is not a rig. False when it is ignored
        (WRONG_SENDERS_MAX current senders already): then it gets no health record and no log line either."""
        if ip not in self.wrong_senders:
            if len(self.wrong_senders) >= WRONG_SENDERS_MAX:
                for old in [k for k, (at, _) in list(self.wrong_senders.items()) if now - at > WRONG_SENDER_SHOW_S]:
                    del self.wrong_senders[old]
                    if self.registry.get(old) is None:
                        self.health.forget(old)
                if len(self.wrong_senders) >= WRONG_SENDERS_MAX:
                    return False    # a flood of senders: the list is full of current ones, ignore new ones
            start, count = self._wrong_log_window or (now, 0)
            if now - start >= 60.0:
                start, count = now, 0
            self._wrong_log_window = (start, count + 1)
            if count < WRONG_SENDER_LOGS_PER_MIN:
                log.warning("A PC at %s is sending telemetry in a format the hub can't read (format %s)",
                            ip, data_format or "?")
        self.wrong_senders[ip] = (now, data_format)
        return True

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

    def active_track(self, now: float | None = None, tv: bool = False) -> str | None:
        """The track the TV shows: the one most rigs are on, driving rigs counting double (`tv`: only the rigs the
        TV shows count, as in the feed)."""
        now = time.monotonic() if now is None else now
        counts: dict[str, int] = {}
        hidden = self.tv_hidden_rigs() if tv else frozenset()
        for rig in self.registry.all():
            if rig.ip in hidden:
                continue
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

    def apply_hours(self) -> None:
        """Opening hours changed (from /setup): the business day ("today" boards, challenges) follows at once."""
        self.laps.day_start_hour = self.config.day_start_hour
        self.competitions.day_start_hour = self.config.day_start_hour

    def name_in_use(self, name: str, rig_id: str | None = None) -> str | None:
        """Where a walk-in name is already used today ("driving on Rig 2", "on today's board"), else None.
        Walk-in laps with the same name share one line on the boards, so staff are asked first."""
        folded = name.casefold()
        for ip, session in self.drivers.sessions().items():
            if ip != rig_id and session.driver_id is None and session.name.casefold() == folded:
                return f"driving on {self.rig_label(ip)}"
        since = self.laps.period_starts()["today"] or 0
        if self.drivers.store.has_laps_since(driver_key(name, rig_id or "", None), since):
            return "on today's board"
        return None

    def session_started(self, ip: str) -> None:
        """Staff started a session on a rig: reset its session stats and show 'now driving'."""
        self._session_top_kph.pop(ip, None)
        self.auto_ended.pop(ip, None)
        self.announce_driver(ip)

    def end_session(self, ip: str, session: Any = None) -> dict[str, Any] | None:
        """End the staff session on a rig (or, given `session`, that session if it is still open); returns the
        story card (None without a counted lap or sharing off). Safe to call twice for the same session (staff End
        racing the automatic end): the second call ends nothing and gets the same card, never a second one."""
        with self._end_lock:
            current = self.drivers.get(ip)
            target = session if session is not None else current
            if target is None:
                return None
            if current is target:
                self.drivers.end(ip, expected_session=current)   # never a session started after this read
            return self.session_card(ip, target)

    # --- automatic end (closing time, overrun) ------------------------------------------------

    def auto_end_reason(self, ip: str, session: Any, now: dt.datetime) -> str | None:
        """"closing" once the session's closing time (or the next business day) has come, "overrun" for a timed
        session over its time whose rig hasn't been DRIVING for 5 minutes, else None. Check-in sessions have no
        time, so only closing time ends them."""
        from .core.hours import auto_end_at
        started = dt.datetime.fromtimestamp(session.started_at / 1000)
        if now >= auto_end_at(started, self.config.owner.close_hour, self.config.day_start_hour):
            return "closing"
        if session.ends_at is not None and now.timestamp() * 1000 >= session.ends_at:
            age = max(0.0, now.timestamp() - session.started_at / 1000)
            mono = time.monotonic()
            since = self.health.seconds_since_driving(ip, mono)
            if since is None:       # nothing from the rig since the hub started: count from the start, not from
                since = max(0.0, mono - self.started_at)    # the session's start (a restart must not end a lapping guest)
            if min(since, age) >= AUTO_END_IDLE_S:
                return "overrun"
        return None

    def auto_end_sessions(self) -> list[dict[str, Any]]:
        """End every session that is due (see auto_end_reason) through the normal end_session path, so the card is
        still made. Also run at start-up, so a session left open from a previous day ends at once."""
        if not self.features.auto_end_sessions:
            return []
        now = self.wall_clock()
        done = []
        with self.checkin.lock:          # not while a phone is checking in on the same rig
            for ip, session in self.drivers.sessions().items():
                try:             # one rig failing (its card, say) must not stop the others ending
                    notice = self._auto_end_one(ip, session, now)
                except Exception:
                    log.exception("Automatic session end failed on %s", ip)
                    continue
                if notice is not None:
                    done.append(notice)
        return done

    def _auto_end_one(self, ip: str, session: Any, now: dt.datetime) -> dict[str, Any] | None:
        reason = self.auto_end_reason(ip, session, now)
        if reason is None:
            return None
        with self._end_lock:
            if self.drivers.get(ip) is not session:      # staff ended or replaced it meanwhile
                return None
            try:
                card = self.end_session(ip, session)
            except Exception:
                if self.drivers.get(ip) is session:
                    raise                                 # not ended: try again on the next check
                log.exception("%s's session ended automatically, but its card failed", session.name)
                card = None
        notice = {"rig_id": ip, "rig_name": self.rig_label(ip), "driver": session.name, "reason": reason,
                  "text": AUTO_END_TEXT[reason], "at": round(now.timestamp() * 1000),
                  "card": ({"token": card["token"], "url": card["url"], "driver": card["driver"]}
                           if card else None),
                  "card_note": None if card or not self.features.sharing else NO_CARD_TEXT}
        self.auto_ended[ip] = notice
        log.info("%s: %s's session %s", notice["rig_name"], session.name, notice["text"].lower())
        return notice

    async def tick_auto_end(self, every: float = AUTO_END_EVERY_S) -> None:
        """Check at once (sessions left open from a previous day), then every `every` seconds."""
        while True:
            try:
                self.auto_end_sessions()
            except Exception:  # must never stop the hub
                log.exception("Automatic session end failed")
            await asyncio.sleep(every)

    def session_card(self, ip: str, session: Any) -> dict[str, Any] | None:
        """Story card for a session that has just ended (ended by staff, or replaced by the next driver)."""
        with self._end_lock:
            made = self._carded.get(ip)
            if made is not None and made[0] == session.started_at:
                return made[1]                            # already made for this session: never a second card
            card = self._make_card(ip, session)
            self._carded[ip] = (session.started_at, card)
            return card

    def _make_card(self, ip: str, session: Any) -> dict[str, Any] | None:
        from .core.cards import build_card
        if not self.features.sharing:
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
        url = f"http://{self.hub_address() or 'localhost'}:{self.config.network.http_port}/card/{card['token']}"
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
        from .core.wifi import wifi_share
        features = self.features
        race.track_name = race.track_name or self.race_track_name(race)
        if not (features.sharing and features.race_podium):
            return {"cards": [], "moment": None}
        base = f"http://{self.hub_address() or 'localhost'}:{self.config.network.http_port}/card/"
        cards = []
        for rig, result in race.results:
            card = build_race_card(self, rig, result, race)
            if card is None:
                continue
            self.drivers.save_card(rig, self.drivers.driver_id(rig), card)
            cards.append((rig, result, card))
        moment = None
        shown = [c for c in cards if self.rig_licensed(c[0])]   # the TV leaves out rigs beyond the licence
        if len(shown) == 1:
            rig, result, card = shown[0]
            self.laps.publish_moment("card", rig_id=rig, driver=card["driver"], token=card["token"],
                                     url=base + card["token"], best_ms=card["best_ms"],
                                     track_name=card["track_name"], card_kind="race", position=card["position"])
        elif shown:
            moment = self.laps.publish_moment(
                "race_podium", track_key=race.track_key, track_name=race.track_name,
                session_type=race.session_type,
                drivers=[{"rank": i, "position": res.position, "driver": card["driver"], "rig_id": rig,
                          "grid_position": res.grid_position, "laps": res.laps, "best_lap_ms": res.best_lap_ms,
                          "total_time_s": res.total_time_s, "status": res.status,
                          "card_url": base + card["token"], "card_token": card["token"]}
                         for i, (rig, res, card) in enumerate(shown, 1)],
                wifi=wifi_share(self.config, features))
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
        if not self.features.moments:
            return None
        rig = self.registry.get(ip)
        s = self.adapter.live_summary(ip)
        assigned = self.drivers.get(ip)
        if rig is None or assigned is None:
            return None
        track_key = (s.track_key if s else None) or self.active_track(tv=True)
        record = self.laps.record_holder(track_key, "today", exclude=self.tv_hidden_rigs()) if track_key else None
        best = self.laps.driver_best(track_key, driver_key(assigned.name, ip, assigned.driver_id)) if track_key else None
        return self.laps.publish_moment(
            "now_driving", rig_id=ip, rig_name=rig.name, driver=assigned.name, track_key=track_key,
            track_name=(s.track if s else None) or (record or {}).get("track_name"),
            today_record=({"driver": record["driver"] or record["rig_name"], "lap_ms": record["lap_ms"]}
                          if record else None),
            personal_best_ms=best["lap_ms"] if best else None)

    def podium(self, reason: str) -> dict[str, Any] | None:
        """Podium moment: today's top three on the shown track ("hourly" or "staff"), as the TV's board shows it."""
        track_key = self.active_track(tv=True)
        if not self.features.podium or track_key is None:
            return None
        since = self.laps.period_starts()["today"]
        board = self.laps.board(track_key, "today", since, limit=3, exclude=self.tv_hidden_rigs())
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
        if not self.features.challenges:
            return []
        out = []
        for c in self.competitions.due_winners(exclude=self.tv_hidden_rigs()):
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
        """One backup now plus pruning; returns the zip path. Blocking: call from a thread. Raises BackupFailed
        with a plain sentence for the owner; the raw error goes to the log."""
        from .core.backup import BackupFailed, make_backup, plain_backup_error, prune
        cfg = self.config
        folder = cfg.backups_dir
        try:
            out = make_backup(cfg.data_dir, self.config_path, folder, now or dt.datetime.now())
            prune(folder, cfg.backup.keep)
        except Exception as exc:
            text = plain_backup_error(exc, folder)
            log.exception("Backup to %s failed (%s)", folder, text)
            self.backup_status.failed(text)
            raise BackupFailed(text) from exc
        self.backup_status.ok(folder)
        return out

    def backup_warning(self) -> str | None:
        """"Last backup: 5 days ago. Check the backup folder or USB stick." (owner page and staff Health only)."""
        if not (self.features.backup_warning and self.config.backup.enabled):
            return None
        if self.drivers.store.path is None:          # replays and tests in memory: nothing to back up
            return None
        return self.backup_status.warning()

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
        from .core.backup import BackupFailed
        try:
            out = await asyncio.to_thread(self.run_backup)
            log.info("%s saved: %s", label, out)
        except BackupFailed as exc:                  # already logged with the raw error
            log.warning("%s failed: %s (will try again tomorrow)", label, exc.text)
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

    # --- licence ---------------------------------------------------------------------

    @property
    def entitlements(self) -> licence.Entitlements:
        return self._entitlements

    def load_licence(self, warn_missing: bool = True) -> licence.Entitlements:
        """Read <data>/licence.txt at start-up. Missing or damaged: the fallback, and staff Health, /setup and the
        owner page say so (never the TV). `warn_missing=False` (demo) runs on the fallback quietly."""
        with self._licence_lock:
            return self._load_licence(warn_missing)

    def _load_licence(self, warn_missing: bool) -> licence.Entitlements:
        try:
            found = licence.read_file(self.config.data_dir)
        except licence.LicenceError:
            log.warning("%s is damaged or not signed for this hub; using the fallback licence",
                        self.config.data_dir / licence.LICENCE_FILE)
            found, problem = None, "damaged"
        else:
            problem = None if found is not None or not warn_missing else "missing"
        if found is None:
            if problem == "missing":
                log.warning("No licence file; using the fallback licence (%d rigs)", licence.FALLBACK.rigs)
            self._set_entitlements(licence.FALLBACK, problem)
        else:
            log.info("Licence %s: %s", found.payload.licence_id, licence.summary(licence.entitlements_from(found)))
            self._set_entitlements(licence.entitlements_from(found), None)
        return self._entitlements

    def apply_licence(self, code: Any) -> licence.Entitlements:
        """A new code from the owner page: verified, checked against the current licence (same cafe, higher seq;
        a missing or damaged file counts as no licence yet, so the owner can recover), saved, and applied at once
        with no restart; every TV gets a fresh snapshot. Raises LicenceError with the owner's plain message.
        Call it on the event loop thread (the owner route is async): the hooks change state the feed reads."""
        with self._licence_lock:
            new = licence.verify(code)
            ent = licence.accept_new(self._entitlements, new)
            try:
                licence.write_file(self.config.data_dir, new)
            except OSError:
                log.exception("Could not save %s", self.config.data_dir / licence.LICENCE_FILE)
                raise licence.LicenceError(licence.SAVE_FAILED) from None
            self._set_entitlements(ent, None)
        log.info("New licence %s installed: %s", ent.licence_id, licence.summary(ent))
        return ent

    def _set_entitlements(self, ent: licence.Entitlements, problem: str | None) -> None:
        self._entitlements = ent
        self.licence_problem = problem
        self._on_entitlements_changed()

    def _on_entitlements_changed(self) -> None:
        """Re-apply everything the licence decides (enforcement hooks), then refresh every TV."""
        for hook in list(self.entitlement_hooks):
            try:
                hook(self._entitlements)
            except Exception:  # one hook failing must never stop the licence applying
                log.exception("Applying the licence failed in %r", hook)
        self.refresh_feed()

    def refresh_feed(self) -> None:
        """Every connected TV gets a fresh snapshot on its next tick (it replaces the TV's state)."""
        self.feed_epoch += 1

    def licence_warning(self) -> str | None:
        """"No licence found. ..." or "The licence file is damaged. ..." (staff Health, /setup, owner page)."""
        return licence.PROBLEMS.get(self.licence_problem) if self.licence_problem else None

    def licence_summary(self) -> str:
        return licence.summary(self._entitlements, self.licence_problem)

    def licence_info(self) -> dict[str, Any]:
        """The owner page's Licence card (never the code itself)."""
        ent = self._entitlements
        return {"source": ent.source, "summary": self.licence_summary(),
                "cafe_name": ent.cafe_name, "rigs": ent.rigs, "games": [licence.game_name(g) for g in ent.games],
                "game_ids": list(ent.games), "features": list(ent.features), "variant": ent.variant,
                "licence_id": ent.licence_id, "seq": ent.seq, "warning": self.licence_warning(),
                "rigs_warning": self.licence_rigs_warning()}

    # --- enforcement (spec 2.3) -------------------------------------------------------

    def _apply_entitlements(self, ent: licence.Entitlements) -> None:
        """Entitlement hook (start-up, a new code): which features and game the licence allows. Rigs are checked
        live (tv_hidden_rigs), so a rig that registers later is covered too."""
        self._licensed_features = frozenset(ent.features) | licence.NOT_LICENSED_FLAGS
        game = adapter_game_id(self.adapter)
        self._game_allowed = game is None or game in ent.games
        if self._game_allowed:
            self.unlicensed_game_senders.clear()

    @property
    def features(self) -> FeaturesConfig:
        """The effective [features]: the hub.toml flags AND the licensed features. Every flag is read through this,
        so an unlicensed feature is exactly like a switched-off flag, and the owner can switch a licensed one off
        in hub.toml but can't switch on one the licence doesn't include."""
        raw = self.config.features
        off = {name: False for name in FeaturesConfig.model_fields
               if name not in self._licensed_features and getattr(raw, name)}
        return raw.model_copy(update=off) if off else raw

    def rig_licensed(self, rig_id: str) -> bool:
        """Rig numbers 1..N are licensed. An address that is no rig now (laps from a forgotten rig) counts as
        licensed: it is history, not a rig being raced."""
        rig = self.registry.get(rig_id)
        return rig is None or self._entitlements.licensed(rig.number)

    def tv_hidden_rigs(self) -> frozenset[str]:
        """Rigs beyond the licensed rig count: they still record laps and show on the staff page, but the TV feed
        leaves them out (frames, rig_info, boards, moments)."""
        ent = self._entitlements
        return frozenset(rig.ip for rig in self.registry.all() if not ent.licensed(rig.number))

    def licence_rigs_warning(self) -> str | None:
        """Staff Health, /setup and the owner page (never the TV), only while a rig beyond the licence exists."""
        ent = self._entitlements
        if not self.tv_hidden_rigs():
            return None
        covers = "1 rig" if ent.rigs == 1 else f"{ent.rigs} rigs"
        return (f"This licence covers {covers}. Rig {ent.rigs + 1} and up aren't shown on the TV. "
                f"Contact {ent.supplier} to add rigs.")

    def game_warnings(self, now: float | None = None) -> list[dict[str, Any]]:
        """"Rig 2: This licence doesn't include F1 25." for rigs sending a game the licence lacks (last minute)."""
        if self._game_allowed:
            return []
        now = time.monotonic() if now is None else now
        game = licence.game_name(adapter_game_id(self.adapter) or "")
        return [{"code": "game_not_licensed", "rig_id": ip,
                 "message": f"{self.rig_label(ip)}: This licence doesn't include {game}."}
                for ip, at in sorted(self.unlicensed_game_senders.items()) if now - at <= GAME_LINE_SHOW_S]

    # --- views -----------------------------------------------------------------------

    def add_startup_warning(self, code: str, message: str) -> None:
        self.startup_warnings.append({"code": code, "rig_id": None, "message": message})

    def hours_check_warning(self) -> str | None:
        """After an upgrade from 0.4: sessions now end at closing time, so check the opening hours (until the
        setup page is saved)."""
        if not self.settings_from_older_version or not self.features.auto_end_sessions:
            return None
        from .core.hours import hour_label
        owner = self.config.owner
        closing = "midnight" if owner.close_hour == 24 else hour_label(owner.close_hour, owner.open_hour)
        return (f"Sessions now end automatically at closing time ({closing}). Check your opening hours on the setup "
                "page — if you close after midnight, choose the next-day time.")

    def admin_warnings(self) -> list[dict[str, Any]]:
        """Start-up, port and address problems for the staff Health tab and /setup. Never sent to the TV."""
        warnings = list(self.startup_warnings)
        hours = self.hours_check_warning()
        if hours:
            warnings.append({"code": "check_hours", "rig_id": None, "message": hours})
        if self.licence_problem:
            warnings.append({"code": f"licence_{self.licence_problem}", "rig_id": None,
                             "message": self.licence_warning()})
        rigs_warning = self.licence_rigs_warning()
        if rigs_warning:
            warnings.append({"code": "licence_rigs", "rig_id": None, "message": rigs_warning})
        warnings += self.game_warnings()
        if self.udp_busy:
            warnings.append({"code": "udp_port_busy", "rig_id": None, "message": self.udp_busy})
        try:
            changed = self.address_watch.warning()
        except Exception:  # a warning must never break the page that shows it
            log.exception("Could not check the hub's address")
            changed = None
        if changed is not None:
            warnings.append(changed)
        return warnings

    def hub_address(self) -> str | None:
        """This PC's network address: what every rig's UDP IP Address must be set to."""
        from .core.feed import lan_address
        return lan_address(r.ip for r in self.registry.all())

    def own_addresses(self) -> set[str]:
        """Every address of this PC (a visit from one of them is not a phone). Looked up at most once a minute:
        a phone reloading /hello must not make the hub list its network adapters each time."""
        from .core.feed import _private_addresses
        now = time.monotonic()
        cached = self._own_addresses
        if cached is not None and now - cached[0] < OWN_ADDRESSES_CACHE_S:
            return cached[1]
        found = {a for a in (self.hub_address(), *_private_addresses()) if a}
        self._own_addresses = (now, found)
        return found

    def wrong_sender_warnings(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.monotonic() if now is None else now
        return [{"code": "wrong_format_sender", "rig_id": None,
                 "message": f"A PC at {ip} is sending telemetry in the wrong format: set UDP Format to 2025."}
                for ip, (at, _) in sorted(self.wrong_senders.items()) if now - at <= WRONG_SENDER_SHOW_S]

    def no_data_checklist(self, rig: Rig) -> str:
        address = self.hub_address() or "this PC's network address"
        return (f"On {rig.name} check: UDP Telemetry On · UDP IP Address = {address} · "
                f"Port {self.config.network.udp_port} · Format 2025, then drive out of the garage.")

    def silent_rig_warnings(self, now: float | None = None) -> list[dict[str, Any]]:
        """Rigs silent for over 10 minutes, during opening hours only and at most once per rig per day."""
        now = time.monotonic() if now is None else now
        wall = self.wall_clock()
        owner = self.config.owner
        out = []
        for rig in self.registry.all():
            h = self.health.get(rig.ip)
            last = h.last_seen if h is not None and h.last_seen is not None else self.started_at
            silent = now - last if self.health.state(rig.ip, now) is RigState.NO_DATA else None
            if self.silent_watch.check(rig.ip, silent, wall, owner.open_hour, owner.close_hour):
                out.append({"code": "no_data", "rig_id": rig.ip, "message": self.no_data_checklist(rig)})
        return out

    def state_text(self, ip: str, now: float) -> str:
        """A rig's state for staff and the owner, in plain words."""
        state = self.health.state(ip, now)
        if not self._game_allowed and now - self.unlicensed_game_senders.get(ip, float("-inf")) <= GAME_LINE_SHOW_S:
            return "Game not licensed"
        if state is RigState.DRIVING:
            return "On track"
        if state is RigState.NO_DATA:
            return "No data"
        return "Wrong game settings" if self.health.wrong_format(ip, now) else "In menu"

    def rig_moving(self, ip: str, now: float) -> bool:
        """Its car is moving right now (the setup page's "which rig is which")."""
        s = self.adapter.live_summary(ip)
        return self.health.state(ip, now) is RigState.DRIVING and s is not None and (s.speed_kph or 0) >= 5

    # --- rig edits (setup page) ---------------------------------------------------------

    def rename_rig(self, ip: str, name: Any) -> Rig:
        return self.registry.rename(ip, name)

    def forget_rig(self, ip: str) -> None:
        rig = self.registry.get(ip)
        if rig is None:
            raise RigError("That rig isn't there any more. Reload the page.")
        if self.drivers.get(ip) is not None:
            raise RigError(f"{rig.name} has a session running. End it on the staff page first.")
        now = time.monotonic()
        # A rig sending only wrong-format packets can't come back from them (only a valid packet makes a rig).
        if self.health.state(ip, now) is not RigState.NO_DATA and not self.health.wrong_format(ip, now):
            raise RigError(f"{rig.name} is sending data right now, so it would come straight back. "
                           f"Close the game on that rig first.")
        self.registry.forget(ip)
        self.checkin.forget(ip)
        if self.tv.pinned_rig == ip:
            self.tv.set(pinned_rig=None)

    def merge_rig(self, old_ip: str, new_ip: str) -> Rig:
        """`new_ip` is the rig PC that used to be `old_ip`: name, colour, number, check-in code, its session and
        the TV focus move to the new address, and the old entry is forgotten."""
        from .core.drivers import DriverError
        old, new = self.registry.get(old_ip), self.registry.get(new_ip)
        if old is None or new is None:
            raise RigError("That rig isn't there any more. Reload the page.")
        if old is new:
            raise RigError("Choose a different rig.")
        if self.health.state(old_ip, time.monotonic()) is not RigState.NO_DATA:
            raise RigError(f"{old.name} is still sending data, so it is a different PC.")
        session = self.drivers.get(old_ip)
        try:
            self.drivers.move(old_ip, new_ip)
        except DriverError as exc:
            raise RigError(str(exc)) from None
        if session is not None:
            self.laps.move_rig(old_ip, new_ip, session.started_at)   # the card and check-in page keep its laps
        self.checkin.move(old_ip, new_ip)
        if old_ip in self._session_top_kph:
            self._session_top_kph[new_ip] = self._session_top_kph.pop(old_ip)
        if self.tv.pinned_rig == old_ip:
            self.tv.set(pinned_rig=new_ip)
        return self.registry.merge(old_ip, new_ip)

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
                "state_text": self.state_text(rig.ip, now),
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
            "product": brand.PRODUCT_NAME,      # lets a second copy see that this one is already running
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
