"""Dashboard feed: hub state -> WebSocket messages following docs/WS_SCHEMA.md (v1).

Game-agnostic: everything comes from the registry, health monitor, recorder, the
adapter's LiveSummary and the hub's lap book. Laps, bests, comparison and leaderboard
come from the LapBook (core/laps.py): live and best laps, head-to-head, track outlines,
lap_completed messages and the leaderboard of the track shown on the TV.

FeedBuilder holds what is shared between connections; each WebSocket gets a FeedConnection
with its own seq counter and its own "what did this client already see" state.
"""

from __future__ import annotations

import ipaddress
import re
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .. import __version__
from ..hub import personal_best_key, tyre_dict
from ..tools.recorder import RecorderState
from .health import RigState
from .wifi import wifi_share

if TYPE_CHECKING:
    from ..hub import Hub
    from .rigs import Rig

SCHEMA_VERSION = 1
STATUS_INTERVAL_S = 1.0
SIZE_MISMATCH_WARN_S = 10.0  # keep the warning up this long after the last size-mismatch drop

# Rig colours by rig number, chosen to stay clear of the sector colours (purple/green/yellow).
PALETTE = ("#36C5F0", "#FF8A3D", "#F15BB5", "#5B8CFF", "#2EC4B6",
           "#FF6B6B", "#C0C9D2", "#FFB3C6", "#8D99AE", "#D4A373", "#FFFFFF", "#9C6644")

_NULL_SESSION: dict[str, Any] = {"session_id": None, "track_key": None, "track_name": None,
                                 "track_length_m": None, "session_type": None, "weather": None,
                                 "air_temp_c": None, "track_temp_c": None}


def lan_address(peers: Iterable[str] = ()) -> str | None:
    """This PC's address on the local network (the one games should send telemetry to).

    The address of the default route's interface; when that is missing or loopback (no default gateway), the
    private IPv4 address on the same network as the rigs (`peers`: their source addresses), else the first one.
    """
    address = _default_route_address()
    if address and not address.startswith(("127.", "0.")):
        return address
    local = _private_addresses()
    for peer in peers:
        try:
            ip = ipaddress.IPv4Address(peer)
        except ValueError:
            continue
        if ip.is_loopback:
            continue
        match = next((a for a in local if ip in ipaddress.IPv4Network(f"{a}/24", strict=False)), None)
        if match:
            return match
    return local[0] if local else None


def _default_route_address() -> str | None:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # no packet is sent; this only picks the outgoing interface
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _private_addresses() -> list[str]:
    """This PC's private IPv4 addresses (not loopback or link-local), in the order Windows lists them."""
    import socket
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    out: list[str] = []
    for info in infos:
        address = str(info[4][0])
        ip = ipaddress.IPv4Address(address)
        if ip.is_private and not ip.is_loopback and not ip.is_link_local and address not in out:
            out.append(address)
    return out


def car_detail(s, driving: bool) -> dict[str, Any]:
    """Schema CarDetail: everything beyond speed/gear/pedals the TV can show. Live values only while driving."""
    def live(value):
        return value if driving else None

    return {
        "drs_open": live(s.drs_open),
        "drs_allowed": live(s.drs_allowed),
        "rev_lights_pct": live(s.rev_lights_pct),
        "ers_pct": s.ers_pct,
        "ers_mode": s.ers_mode,
        "fuel_kg": s.fuel_kg,
        "fuel_laps": s.fuel_laps,
        "pit_limiter": live(s.pit_limiter),
        "steer": live(s.steer),
        "g_lat": live(s.g_lat),
        "g_long": live(s.g_long),
        "tyre_surface_c": list(s.tyre_surface_c) if s.tyre_surface_c else None,
        "tyre_inner_c": list(s.tyre_inner_c) if s.tyre_inner_c else None,
        "tyre_pressure_psi": list(s.tyre_pressure_psi) if s.tyre_pressure_psi else None,
        "tyre_wear_pct": list(s.tyre_wear_pct) if s.tyre_wear_pct else None,
        "brake_c": list(s.brake_c) if s.brake_c else None,
        "damage": s.damage,
        "top_speed_lap_kph": s.top_speed_lap_kph,
        "top_speed_kph": s.top_speed_kph,
        "slide_deg": live(s.slide_deg),
        "saves": s.saves,
        "last_save_at": s.last_save_at_ms,
        "last_save_peak_deg": s.last_save_peak_deg,
    }


def rig_colour(rig: Rig) -> str:
    if rig.colour:
        return rig.colour
    m = re.fullmatch(r"Rig (\d+)", rig.auto_name)
    n = int(m.group(1)) - 1 if m else sum(map(ord, rig.ip))
    return PALETTE[n % len(PALETTE)]


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def tv_message(type_: str, body: dict[str, Any], hidden: frozenset[str]) -> dict[str, Any] | None:
    """A lap book message as the TV may see it: None for a lap or moment of a rig beyond the licence, and a moment
    about several rigs (podium, race podium) without those rigs' lines. Racing and the staff page are unaffected."""
    if not hidden:
        return body
    if type_ == "lap_completed":
        return None if body["lap"].get("rig_id") in hidden else body
    if type_ != "moment":
        return body
    moment = body["moment"]
    if moment.get("rig_id") in hidden or any(r in hidden for r in moment.get("rig_ids") or ()):
        return None
    for key in ("drivers", "entries", "runners_up"):
        items = moment.get(key)
        if isinstance(items, list) and any(isinstance(e, dict) and e.get("rig_id") in hidden for e in items):
            kept = [e for e in items if not (isinstance(e, dict) and e.get("rig_id") in hidden)]
            if not kept:
                return None
            moment = {**moment, key: kept}
    winner = moment.get("winner")
    if isinstance(winner, dict) and winner.get("rig_id") in hidden:
        return None
    return body if moment is body["moment"] else {**body, "moment": moment}


class FeedBuilder:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self._size_drops: dict[str, tuple[int, float]] = {}  # ip -> (count, when it last went up)

    @property
    def frame_hz(self) -> float:
        return self.hub.config.dashboard.frame_hz

    # --- pieces ----------------------------------------------------------------------

    def rig_info(self, rig: Rig) -> dict[str, Any]:
        adapter = self.hub.adapter
        return {
            "rig_id": rig.ip,
            "name": rig.name,
            "colour": rig_colour(rig),
            "address": rig.ip,
            "game": adapter.game,
            "data_format": rig.data_format,
            "format_supported": rig.data_format is None or adapter.is_supported_format(rig.data_format),
        }

    def hidden(self) -> frozenset[str]:
        """Rigs the TV leaves out: beyond the licensed rig count (Hub.tv_hidden_rigs)."""
        return self.hub.tv_hidden_rigs()

    def tv_rigs(self) -> list[Rig]:
        """The rigs the TV sees, in registry order."""
        hidden = self.hidden()
        return [rig for rig in self.hub.registry.all() if rig.ip not in hidden]

    def rig_infos(self) -> list[dict[str, Any]]:
        return [self.rig_info(rig) for rig in self.tv_rigs()]

    def session(self, rig: Rig, now: float) -> dict[str, Any]:
        if self.hub.health.state(rig.ip, now) is RigState.NO_DATA:
            return dict(_NULL_SESSION)
        s = self.hub.adapter.live_summary(rig.ip)
        return {
            "session_id": rig.session_id,
            "track_key": s.track_key if s else None,
            "track_name": s.track if s else None,
            "track_length_m": s.track_length_m if s else None,
            "session_type": s.session_type if s else None,
            "weather": s.weather if s else None,
            "air_temp_c": s.air_temp_c if s else None,
            "track_temp_c": s.track_temp_c if s else None,
        }

    def rig_frame(self, rig: Rig, now: float) -> dict[str, Any]:
        hub = self.hub
        state = hub.health.state(rig.ip, now)
        h = hub.health.get(rig.ip)
        s = hub.adapter.live_summary(rig.ip)
        driving = state is RigState.DRIVING and s is not None
        tyre = tyre_dict(s) if state is not RigState.NO_DATA else None
        track_key = s.track_key if s is not None and state is not RigState.NO_DATA else None
        best = hub.laps.rig_best(rig.ip, track_key)
        return {
            "rig_id": rig.ip,
            "state": state.value,
            "last_seen_ms": round((now - h.last_seen) * 1000) if h and h.last_seen is not None else None,
            "driver": hub.drivers.display_name(rig.ip, rig.driver_name) if state is not RigState.NO_DATA else None,
            "session": self.session(rig, now),
            "position": ({"x": round(s.position[0], 1), "z": round(s.position[1], 1)}
                         if driving and s.position is not None else None),
            "speed_kph": s.speed_kph if driving else None,
            "gear": s.gear if driving else None,
            "throttle": _round(s.throttle, 3) if driving else None,
            "brake": _round(s.brake, 3) if driving else None,
            "rpm": s.rpm if driving else None,
            "max_rpm": s.max_rpm if s is not None and state is not RigState.NO_DATA else None,
            "tyre": tyre,
            "car": car_detail(s, driving) if s is not None and state is not RigState.NO_DATA else None,
            "lap": hub.laps.live_view(rig.ip) if driving else None,
            "best": best.best_schema() if best else None,
            "personal_best": hub.laps.driver_best(track_key, personal_best_key(hub, rig)) if track_key else None,
            "booking": self.booking(rig),
        }

    def booking(self, rig: Rig) -> dict[str, Any] | None:
        """Schema Booking: the staff session on the rig (who and until when), or None."""
        a = self.hub.drivers.get(rig.ip)
        return {"driver": a.name, "started_at": a.started_at, "ends_at": a.ends_at} if a else None

    def competition(self, track_key: str | None) -> dict[str, Any]:
        """Schema Competition: the current challenge and the running corporate event (each null if none / off)."""
        hub = self.hub
        hidden = self.hidden()
        features = hub.features
        key = (track_key, hub.laps._lap_version, hub.competitions.version, int(time.time() // 30), hidden,
               features.challenges, features.events)
        if getattr(self, "_competition_key", None) != key:
            self._competition_key = key
            self._competition = {
                "challenge": hub.competitions.current_challenge(exclude=hidden) if features.challenges else None,
                "event": hub.competitions.active_event(track_key) if features.events else None,
            }
        return self._competition

    def head_to_head(self, track_key: str | None) -> dict[str, Any] | None:
        """Schema HeadToHead of the shown track today (null until two drivers have a traced lap)."""
        laps = self.hub.laps
        hidden = self.hidden()
        on = self.hub.features.head_to_head
        key = (track_key, laps.analysis_version, laps._today(), hidden, on)
        if getattr(self, "_h2h_key", None) != key:
            self._h2h_key = key
            self._h2h = laps.head_to_head(track_key, exclude=hidden) if on else None
        return self._h2h

    def queue(self) -> list[dict[str, Any]]:
        """Schema QueueEntry list: who's waiting for a rig, first first (names only, never contact details)."""
        return [{"id": e["id"], "name": e["name"]} for e in self.hub.drivers.queue()]

    def frame_body(self, now: float) -> dict[str, Any]:
        rigs = [self.rig_frame(rig, now) for rig in self.tv_rigs()]
        return {"rigs": rigs, "comparison": self.comparison(rigs)}

    @staticmethod
    def active_track(rigs: list[dict[str, Any]]) -> str | None:
        """The track the TV shows: the one most rigs are on, driving rigs counting double."""
        counts: dict[str, int] = {}
        for r in rigs:
            key = r["session"]["track_key"]
            if key:
                counts[key] = counts.get(key, 0) + (2 if r["state"] == "driving" else 1)
        return max(counts, key=lambda k: (counts[k], k)) if counts else None

    def comparison(self, rigs: list[dict[str, Any]]) -> dict[str, Any] | None:
        track = self.active_track(rigs)
        on_track = [r for r in rigs if track and r["session"]["track_key"] == track]
        result = self.hub.laps.comparison(track, [r["rig_id"] for r in on_track]) if track else None
        if result is not None:
            driving = {r["rig_id"] for r in on_track if r["state"] == "driving"}
            for entry in result["rigs"]:
                if entry["rig_id"] not in driving:
                    entry["live_delta_ms"] = None
        return result

    def leaderboards(self, track_key: str | None, rigs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Today / this week / all time boards of the shown track (none while no track is known)."""
        if track_key is None:
            return []
        hidden = self.hidden()
        boards = self.hub.laps.boards(track_key, exclude=hidden) + self.hub.laps.boards(track_key, "pro", hidden)
        name = next((r["session"]["track_name"] for r in rigs if r["session"]["track_key"] == track_key), None)
        for board in boards:
            board["track_name"] = board["track_name"] or name
        return boards

    def board_key(self, track_key: str | None) -> tuple[Any, ...]:
        """Changes whenever the shown boards may change: new laps, another track, a new day or week."""
        laps = self.hub.laps
        return (track_key, laps.board_version.get(track_key or "", 0), tuple(laps.period_starts().values()),
                self.hidden())

    def status(self, now: float, tv: bool = False) -> dict[str, Any]:
        """Formats, recorder state and warnings. `tv`: the feed's copy, without the rigs the TV leaves out (staff
        Health gets every rig)."""
        hub = self.hub
        hidden = self.hidden() if tv else frozenset()
        formats = {ip: fmt for ip, fmt in hub._active_formats(now).items() if ip not in hidden}
        warnings: list[dict[str, Any]] = []
        if len(set(formats.values())) > 1:
            warnings.append({"code": "format_mismatch", "rig_id": None,
                             "message": "Rigs are set to different UDP Format settings ("
                                        + " and ".join(sorted(set(formats.values())))
                                        + "): set UDP Format to 2025 on every rig."})
        for rig in hub.registry.all():
            if rig.ip in hidden:
                continue
            if rig.data_format and not hub.adapter.is_supported_format(rig.data_format) \
                    and hub.health.state(rig.ip, now) is not RigState.NO_DATA:
                warnings.append({"code": "format_unsupported", "rig_id": rig.ip,
                                 "message": f"{rig.name} is sending telemetry in the wrong format: "
                                            f"set UDP Format to 2025."})
            if self._size_mismatch_recent(rig.ip, now):
                warnings.append({"code": "size_mismatch", "rig_id": rig.ip,
                                 "message": f"{rig.name} is sending telemetry the hub can't read: "
                                            f"set UDP Format to 2025."})
        for shadow in hub.port_shadows:
            warnings.append({"code": "port_shadowed", "rig_id": None, "message": shadow})
        recorder = None
        if hub.recorder is not None:
            rs = hub.recorder.status()
            recorder = {"state": rs["state"], "message": rs["message"], "free_gb": rs["free_gb"]}
            free = f" ({rs['free_gb']:g} GB free)" if rs["free_gb"] is not None else ""
            if hub.recorder.state is RecorderState.STOPPED:
                text = (rs["message"] or "recording stopped").capitalize()
                warnings.append({"code": "recorder_stopped", "rig_id": None, "message": text + free})
            elif hub.recorder.state is RecorderState.LOW_DISK:
                warnings.append({"code": "recorder_low_disk", "rig_id": None,
                                 "message": "Low disk space for recordings" + free})
        return {"format_mismatch": len(set(formats.values())) > 1, "formats": formats,
                "recorder": recorder, "warnings": warnings}

    def _size_mismatch_recent(self, ip: str, now: float) -> bool:
        h = self.hub.health.get(ip)
        count = h.drops.get("size_mismatch", 0) if h else 0
        prev_count, since = self._size_drops.get(ip, (0, float("-inf")))
        if count > prev_count:
            since = now
        self._size_drops[ip] = (count, since)
        return now - since <= SIZE_MISMATCH_WARN_S

    def cafe(self) -> dict[str, Any]:
        c = self.hub.config.cafe
        return {"name": c.name, "branding": dict(c.branding), "tagline": c.tagline,
                "logo": f"/api/cafe/logo?v={c.logo}" if c.logo else None,
                "wifi": wifi_share(self.hub.config, self.hub.features)}

    def tv(self) -> dict[str, Any]:
        """Schema TvSetting; a pinned rig the TV doesn't show (beyond the licence) reads as automatic."""
        tv = self.hub.tv.to_json()
        if tv["pinned_rig"] is not None and tv["pinned_rig"] in self.hidden():
            tv["pinned_rig"] = None
        return tv

    def snapshot_body(self, now: float) -> dict[str, Any]:
        frame = self.frame_body(now)
        hidden = self.hidden()
        return {
            "hub": {"version": __version__, "games": [self.hub.adapter.game], "frame_hz": self.frame_hz,
                    "udp_port": self.hub.config.network.udp_port, "lan_address": self.hub.hub_address(),
                    "steering_rotation_deg": self.hub.config.dashboard.steering_wheel_rotation_deg,
                    # Hub-side switches the TV has no use for stay out of the feed.
                    "features": self.hub.features.model_dump(exclude={"auto_end_sessions", "backup_warning"}),
                    "moments": {"battle_margin_ms": self.hub.config.moments.battle_margin_ms},
                    "sounds": self.hub.config.sounds.model_dump(),
                    # The supplier (9T7) may be shown; off when unbranded. The TV shows "POWERED BY" + wordmark always.
                    "vendor_mark": self.hub.entitlements.vendor_mark},
            "cafe": self.cafe(),
            "status": self.status(now, tv=True),
            "rigs": self.rig_infos(),
            "frame": frame,
            "outlines": list(self.hub.laps.outlines.values()),
            "leaderboards": self.leaderboards(self.active_track(frame["rigs"]), frame["rigs"]),
            "recent_laps": self.hub.laps.recent_laps(exclude=hidden),
            "queue": self.queue(),
            "competition": self.competition(self.active_track(frame["rigs"])),
            "head_to_head": self.head_to_head(self.active_track(frame["rigs"])),
            "tv": self.tv(),
            "session_story": self.hub.laps.session_story(self.active_track(frame["rigs"]), exclude=hidden),
        }


class FeedConnection:
    """Message sequence for one WebSocket client."""

    def __init__(self, builder: FeedBuilder, clock=time.time) -> None:
        self.builder = builder
        self._clock = clock
        self.seq = 0
        self._rig_infos: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, str] = {}                   # rig -> last real game session id sent
        self._status: dict[str, Any] | None = None
        self._status_at = float("-inf")
        self._message_id = 0                                  # last lap book message sent
        self._board: tuple[Any, ...] | None = None            # board_key last sent
        self._queue: list[dict[str, Any]] = []                # queue last sent
        self._competition: dict[str, Any] | None = None       # competition state last sent
        self._h2h: dict[str, Any] | None = None               # head to head last sent
        self._tv: dict[str, Any] | None = None                # TV page setting last sent
        self._cafe: dict[str, Any] | None = None              # cafe name, tagline, colour, logo last sent
        self._epoch = builder.hub.feed_epoch                  # hub.feed_epoch of the last snapshot sent
        self._hidden: frozenset[str] = frozenset()            # rigs the TV leaves out (beyond the licence)

    def _message(self, type_: str, body: dict[str, Any]) -> dict[str, Any]:
        msg = {"v": SCHEMA_VERSION, "type": type_, "seq": self.seq, "ts": round(self._clock() * 1000)}
        msg.update(body)
        self.seq += 1
        return msg

    def start(self, now: float) -> dict[str, Any]:
        self._epoch = self.builder.hub.feed_epoch
        self._hidden = self.builder.hidden()
        body = self.builder.snapshot_body(now)
        self._rig_infos = {r["rig_id"]: r for r in body["rigs"]}
        self._sessions = {f["rig_id"]: f["session"]["session_id"] for f in body["frame"]["rigs"]
                          if f["session"]["session_id"] is not None}
        self._status, self._status_at = body["status"], now
        laps = self.builder.hub.laps
        self._message_id = laps.last_message_id
        self._board = self.builder.board_key(self.builder.active_track(body["frame"]["rigs"]))
        self._queue = body["queue"]
        self._competition = body["competition"]
        self._h2h = body["head_to_head"]
        self._tv = body["tv"]
        self._cafe = body["cafe"]
        return self._message("snapshot", body)

    def tick(self, now: float) -> list[dict[str, Any]]:
        if self.builder.hub.feed_epoch != self._epoch:
            return [self.start(now)]       # e.g. a new licence: a fresh snapshot replaces the TV's state (seq goes on)
        hidden = self.builder.hidden()
        if hidden != self._hidden:
            if any(rig_id in hidden for rig_id in self._rig_infos):
                return [self.start(now)]   # a rig the TV has now falls outside the licence: take it off the TV
            self._hidden = hidden          # only new rigs beyond the licence: they are simply never sent
        out = []
        for info in self.builder.rig_infos():
            if self._rig_infos.get(info["rig_id"]) != info:
                self._rig_infos[info["rig_id"]] = info
                out.append(self._message("rig_info", {"rig": info}))
        frame = self.builder.frame_body(now)
        for rig in frame["rigs"]:
            # Only a different real game session is a change: a gap in packets (no data, session null) is not,
            # so the TV keeps the rig's trails and laps across it.
            session_id = rig["session"]["session_id"]
            if session_id is None:
                continue
            last = self._sessions.get(rig["rig_id"])
            if last is not None and last != session_id:
                out.append(self._message("session_changed", {"rig_id": rig["rig_id"], "session": rig["session"]}))
            self._sessions[rig["rig_id"]] = session_id
        laps = self.builder.hub.laps
        for message_id, type_, body in laps.messages_after(self._message_id):
            self._message_id = message_id
            shown = tv_message(type_, body, hidden)
            if shown is not None:
                out.append(self._message(type_, shown))
        track = self.builder.active_track(frame["rigs"])
        board = self.builder.board_key(track)
        if board != self._board:
            self._board = board
            for leaderboard in self.builder.leaderboards(track, frame["rigs"]):
                out.append(self._message("leaderboard", {"leaderboard": leaderboard}))
        h2h = self.builder.head_to_head(track)
        if h2h != self._h2h:
            self._h2h = h2h
            out.append(self._message("head_to_head", {"head_to_head": h2h}))
        competition = self.builder.competition(track)
        if competition != self._competition:
            self._competition = competition
            out.append(self._message("competition", {"competition": competition}))
        tv = self.builder.tv()
        if tv != self._tv:
            self._tv = tv
            out.append(self._message("tv", {"tv": tv}))
        cafe = self.builder.cafe()
        if cafe != self._cafe:
            self._cafe = cafe
            out.append(self._message("cafe", {"cafe": cafe}))
        queue = self.builder.queue()
        if queue != self._queue:
            self._queue = queue
            out.append(self._message("queue", {"queue": queue}))
        status = self.builder.status(now, tv=True)
        if status != self._status or now - self._status_at >= STATUS_INTERVAL_S:
            self._status, self._status_at = status, now
            out.append(self._message("status", {"status": status}))
        out.append(self._message("frame", frame))
        return out
