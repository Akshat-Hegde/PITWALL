"""Dashboard feed: hub state -> WebSocket messages following docs/WS_SCHEMA.md (v1).

Game-agnostic: everything comes from the registry, health monitor, recorder, the
adapter's LiveSummary and the hub's lap book. Laps, bests, comparison and leaderboard
come from the LapBook (core/laps.py): live and best laps, head-to-head, track outlines,
lap_completed messages and the leaderboard of the track shown on the TV.

FeedBuilder holds what is shared between connections; each WebSocket gets a FeedConnection
with its own seq counter and its own "what did this client already see" state.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from .. import __version__
from ..hub import personal_best_key, tyre_dict
from ..tools.recorder import RecorderState
from .health import RigState

if TYPE_CHECKING:
    from ..hub import Hub
    from .rigs import Rig

SCHEMA_VERSION = 1
STATUS_INTERVAL_S = 1.0
SIZE_MISMATCH_WARN_S = 10.0  # keep the warning up this long after the last size-mismatch drop

# Rig colours by rig number, chosen to stay clear of the sector colours (purple/green/yellow).
PALETTE = ("#36C5F0", "#FF8A3D", "#F15BB5", "#5B8CFF", "#2EC4B6",
           "#FF6B6B", "#C0C9D2", "#FFB3C6", "#8D99AE", "#D4A373")

_NULL_SESSION: dict[str, Any] = {"session_id": None, "track_key": None, "track_name": None,
                                 "track_length_m": None, "session_type": None}


def lan_address() -> str | None:
    """This PC's address on the local network (the one games should send telemetry to)."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # no packet is sent; this only picks the outgoing interface
        address = sock.getsockname()[0]
        return None if address.startswith(("127.", "0.")) else address
    except OSError:
        return None
    finally:
        sock.close()


def rig_colour(rig: Rig) -> str:
    if rig.colour:
        return rig.colour
    m = re.fullmatch(r"Rig (\d+)", rig.auto_name)
    n = int(m.group(1)) - 1 if m else sum(map(ord, rig.ip))
    return PALETTE[n % len(PALETTE)]


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


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

    def rig_infos(self) -> list[dict[str, Any]]:
        return [self.rig_info(rig) for rig in self.hub.registry.all()]

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
            "lap": hub.laps.live_view(rig.ip) if driving else None,
            "best": best.best_schema() if best else None,
            "personal_best": hub.laps.driver_best(track_key, personal_best_key(hub, rig)) if track_key else None,
        }

    def frame_body(self, now: float) -> dict[str, Any]:
        rigs = [self.rig_frame(rig, now) for rig in self.hub.registry.all()]
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
        boards = self.hub.laps.boards(track_key)
        name = next((r["session"]["track_name"] for r in rigs if r["session"]["track_key"] == track_key), None)
        for board in boards:
            board["track_name"] = board["track_name"] or name
        return boards

    def board_key(self, track_key: str | None) -> tuple[Any, ...]:
        """Changes whenever the shown boards may change: new laps, another track, a new day or week."""
        laps = self.hub.laps
        return (track_key, laps.board_version.get(track_key or "", 0), tuple(laps.period_starts().values()))

    def status(self, now: float) -> dict[str, Any]:
        hub = self.hub
        formats = {ip: fmt for ip, fmt in hub._active_formats(now).items()}
        warnings: list[dict[str, Any]] = []
        if len(set(formats.values())) > 1:
            warnings.append({"code": "format_mismatch", "rig_id": None,
                             "message": "Rigs send different UDP formats ("
                                        + " and ".join(sorted(set(formats.values()))) + ")"})
        for rig in hub.registry.all():
            if rig.data_format and not hub.adapter.is_supported_format(rig.data_format) \
                    and hub.health.state(rig.ip, now) is not RigState.NO_DATA:
                warnings.append({"code": "format_unsupported", "rig_id": rig.ip,
                                 "message": f"{rig.name} sends UDP format {rig.data_format}, "
                                            f"which the hub can't read"})
            if self._size_mismatch_recent(rig.ip, now):
                warnings.append({"code": "size_mismatch", "rig_id": rig.ip,
                                 "message": f"{rig.name} sends packets of unexpected size; "
                                            f"check its UDP format setting"})
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

    def snapshot_body(self, now: float) -> dict[str, Any]:
        cafe = self.hub.config.cafe
        frame = self.frame_body(now)
        return {
            "hub": {"version": __version__, "games": [self.hub.adapter.game], "frame_hz": self.frame_hz,
                    "udp_port": self.hub.config.network.udp_port, "lan_address": lan_address()},
            "cafe": {"name": cafe.name, "branding": dict(cafe.branding)},
            "status": self.status(now),
            "rigs": self.rig_infos(),
            "frame": frame,
            "outlines": list(self.hub.laps.outlines.values()),
            "leaderboards": self.leaderboards(self.active_track(frame["rigs"]), frame["rigs"]),
            "recent_laps": self.hub.laps.recent_laps(),
        }


class FeedConnection:
    """Message sequence for one WebSocket client."""

    def __init__(self, builder: FeedBuilder, clock=time.time) -> None:
        self.builder = builder
        self._clock = clock
        self.seq = 0
        self._rig_infos: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._status: dict[str, Any] | None = None
        self._status_at = float("-inf")
        self._message_id = 0                                  # last lap book message sent
        self._board: tuple[Any, ...] | None = None            # board_key last sent

    def _message(self, type_: str, body: dict[str, Any]) -> dict[str, Any]:
        msg = {"v": SCHEMA_VERSION, "type": type_, "seq": self.seq, "ts": round(self._clock() * 1000)}
        msg.update(body)
        self.seq += 1
        return msg

    def start(self, now: float) -> dict[str, Any]:
        body = self.builder.snapshot_body(now)
        self._rig_infos = {r["rig_id"]: r for r in body["rigs"]}
        self._sessions = {f["rig_id"]: f["session"] for f in body["frame"]["rigs"]}
        self._status, self._status_at = body["status"], now
        laps = self.builder.hub.laps
        self._message_id = laps.last_message_id
        self._board = self.builder.board_key(self.builder.active_track(body["frame"]["rigs"]))
        return self._message("snapshot", body)

    def tick(self, now: float) -> list[dict[str, Any]]:
        out = []
        for info in self.builder.rig_infos():
            if self._rig_infos.get(info["rig_id"]) != info:
                self._rig_infos[info["rig_id"]] = info
                out.append(self._message("rig_info", {"rig": info}))
        frame = self.builder.frame_body(now)
        for rig in frame["rigs"]:
            if rig["rig_id"] in self._sessions and self._sessions[rig["rig_id"]] != rig["session"]:
                out.append(self._message("session_changed", {"rig_id": rig["rig_id"], "session": rig["session"]}))
            self._sessions[rig["rig_id"]] = rig["session"]
        laps = self.builder.hub.laps
        for message_id, type_, body in laps.messages_after(self._message_id):
            self._message_id = message_id
            out.append(self._message(type_, body))
        track = self.builder.active_track(frame["rigs"])
        board = self.builder.board_key(track)
        if board != self._board:
            self._board = board
            for leaderboard in self.builder.leaderboards(track, frame["rigs"]):
                out.append(self._message("leaderboard", {"leaderboard": leaderboard}))
        status = self.builder.status(now)
        if status != self._status or now - self._status_at >= STATUS_INTERVAL_S:
            self._status, self._status_at = status, now
            out.append(self._message("status", {"status": status}))
        out.append(self._message("frame", frame))
        return out
