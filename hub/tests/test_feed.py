"""Dashboard feed: hub state -> docs/WS_SCHEMA.md v1 messages, and the /ws endpoint."""

from __future__ import annotations

import asyncio
import json
import os
import struct
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from simtelemetry.adapters.f1.adapter import F1Adapter
from simtelemetry.adapters.f1.formats import FORMATS
from simtelemetry.adapters.f1.sizes import PacketId
from simtelemetry.api.app import create_app
from simtelemetry.config import AppConfig, RigConfig
from simtelemetry.core.feed import PALETTE, FeedBuilder, FeedConnection
from simtelemetry.core.rigs import RigRegistry
from simtelemetry.hub import Hub
from simtelemetry.tools.recorder import GB, Recorder

from f1_helpers import blank_packet

RIG_A, RIG_B, RIG_C = "192.168.1.21", "192.168.1.22", "192.168.1.23"
PLAYER = 0
FIXTURE = Path(__file__).resolve().parents[2] / "dashboard" / "src" / "testing" / "hub-feed.sample.json"


# --- packet building from the spec layouts --------------------------------------------------

def set_fields(pkt: bytearray, layout, base: int, **values) -> None:
    by_name = {f.name: f for f in layout.fields}
    for name, value in values.items():
        args = value if isinstance(value, tuple) else (value,)
        struct.pack_into("<" + by_name[name].fmt, pkt, base + layout.offset_of(name), *args)


def car_packet(fmt: int, pid: PacketId, array_field: str, car_layout, uid: int, **values) -> bytes:
    pkt = blank_packet(fmt, pid, player=PLAYER, session_uid=uid)
    base = FORMATS[fmt].packets[pid].offset_of(array_field) + PLAYER * car_layout.size
    set_fields(pkt, car_layout, base, **values)
    return bytes(pkt)


def motion(fmt, uid, x, z):
    return car_packet(fmt, PacketId.MOTION, "m_carMotionData", FORMATS[fmt].car_motion, uid,
                      m_worldPositionX=x, m_worldPositionY=5.0, m_worldPositionZ=z)


def telemetry(fmt, uid, speed=287, throttle=0.75, brake=0.0, gear=7, rpm=11240):
    # Per-wheel arrays are RL, RR, FL, FR in the game.
    return car_packet(fmt, PacketId.CAR_TELEMETRY, "m_carTelemetryData", FORMATS[fmt].car_telemetry, uid,
                      m_speed=speed, m_throttle=throttle, m_brake=brake, m_gear=gear, m_engineRPM=rpm,
                      m_drs=1, m_revLightsPercent=82, m_steer=-0.25,
                      m_brakesTemperature=(510, 520, 610, 620), m_tyresSurfaceTemperature=(91, 92, 97, 98),
                      m_tyresInnerTemperature=(101, 102, 103, 104), m_tyresPressure=(21.5, 21.6, 23.1, 23.2))


def status(fmt, uid, actual=18, visual=16, age=2, max_rpm=13000):
    return car_packet(fmt, PacketId.CAR_STATUS, "m_carStatusData", FORMATS[fmt].car_status, uid,
                      m_actualTyreCompound=actual, m_visualTyreCompound=visual, m_tyresAgeLaps=age,
                      m_maxRPM=max_rpm, m_drsAllowed=1, m_ersStoreEnergy=3_000_000.0, m_ersDeployMode=2,
                      m_fuelInTank=12.5, m_fuelRemainingLaps=3.25)


def session(fmt, uid, track_id=7, length=5891, session_type=18):
    pkt = blank_packet(fmt, PacketId.SESSION, player=PLAYER, session_uid=uid)
    set_fields(pkt, FORMATS[fmt].packets[PacketId.SESSION], 0,
               m_trackId=track_id, m_trackLength=length, m_sessionType=session_type, m_weather=1,
               m_airTemperature=23, m_trackTemperature=31)
    return bytes(pkt)


def participants(fmt, uid, name: bytes):
    layout = FORMATS[fmt].participant
    pkt = blank_packet(fmt, PacketId.PARTICIPANTS, player=PLAYER, session_uid=uid)
    pkt[FORMATS[fmt].packets[PacketId.PARTICIPANTS].offset_of("m_numActiveCars")] = 1
    base = FORMATS[fmt].packets[PacketId.PARTICIPANTS].offset_of("m_participants") + PLAYER * layout.size
    at = base + layout.offset_of("m_name")
    pkt[at:at + len(name)] = name
    return bytes(pkt)


def driving_rig(ip, fmt=2025, uid=0x11, x=-412.6, z=188.2, name=b"Akshat"):
    return [(ip, p) for p in (session(fmt, uid), participants(fmt, uid, name), status(fmt, uid),
                              telemetry(fmt, uid), motion(fmt, uid, x, z))]


def make_hub(tmp_path, **cfg) -> Hub:
    config = AppConfig(data_dir=tmp_path, **cfg)
    return Hub(config, F1Adapter(config.track_names), RigRegistry(config, tmp_path / "rigs.json"))


async def feed(hub, packets):
    consumer = asyncio.create_task(hub.consume())
    for ip, data in packets:
        hub.on_datagram(data, ip, 0.0)
    await hub.drain()
    consumer.cancel()


def last_seen(hub) -> float:
    return max(h.last_seen for ip in (r.ip for r in hub.registry.all()) if (h := hub.health.get(ip)))


# --- frames ---------------------------------------------------------------------------------

async def test_driving_rig_frame(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, driving_rig(RIG_A))
    now = last_seen(hub) + 0.05
    frame = FeedBuilder(hub).frame_body(now)
    assert frame["comparison"] is None
    (rig,) = frame["rigs"]
    assert rig == {
        "rig_id": RIG_A, "state": "driving", "last_seen_ms": 50, "driver": "Akshat",
        "session": {"session_id": f"{0x11:016x}", "track_key": "F1:7", "track_name": "Silverstone",
                    "track_length_m": 5891.0, "session_type": "Time Trial", "weather": "light_cloud",
                    "air_temp_c": 23, "track_temp_c": 31},
        "position": {"x": -412.6, "z": 188.2}, "speed_kph": 287, "gear": 7, "throttle": 0.75, "brake": 0.0,
        "rpm": 11240, "max_rpm": 13000, "tyre": {"compound": "soft", "label": "C3", "age_laps": 2},
        "lap": None, "best": None, "personal_best": None, "booking": None,
        "car": {
            "drs_open": True, "drs_allowed": True, "rev_lights_pct": 82, "ers_pct": 75.0, "ers_mode": "hotlap",
            "fuel_kg": 12.5, "fuel_laps": 3.25, "pit_limiter": False, "steer": -0.25, "g_lat": 0.0, "g_long": 0.0,
            "tyre_surface_c": [97, 98, 91, 92], "tyre_inner_c": [103, 104, 101, 102],   # FL, FR, RL, RR
            "tyre_pressure_psi": [23.1, 23.2, 21.5, 21.6], "tyre_wear_pct": None, "brake_c": [610, 620, 510, 520],
            "damage": None, "top_speed_lap_kph": 287, "top_speed_kph": 287,
            "slide_deg": None, "saves": 0, "last_save_at": None, "last_save_peak_deg": None,
        },
    }


@pytest.mark.parametrize("fmt", [2025, 2026])
async def test_tyre_wear_damage_and_speed_trap(tmp_path, fmt):
    hub = make_hub(tmp_path)
    damage = car_packet(fmt, PacketId.CAR_DAMAGE, "m_carDamageData", FORMATS[fmt].car_damage, 0x11,
                        m_tyresWear=(20.0, 21.0, 10.0, 11.5), m_frontLeftWingDamage=15, m_rearWingDamage=3)
    from test_laps import lap_data_bytes
    await feed(hub, driving_rig(RIG_A, fmt=fmt) + [(RIG_A, damage),
                                                  (RIG_A, telemetry(fmt, 0x11, speed=301)),
                                                  (RIG_A, lap_data_bytes(fmt, 0x11, 50.0, 2, 10, 100)),
                                                  (RIG_A, telemetry(fmt, 0x11, speed=150))])
    car = FeedBuilder(hub).frame_body(last_seen(hub))["rigs"][0]["car"]
    assert car["tyre_wear_pct"] == [10.0, 11.5, 20.0, 21.0]
    assert car["damage"]["front_wing_left"] == 15 and car["damage"]["rear_wing"] == 3
    assert (car["top_speed_lap_kph"], car["top_speed_kph"]) == (150, 301)   # new lap resets the lap's trap


@pytest.mark.parametrize("fmt", [2025, 2026])
async def test_both_formats_give_the_same_frame(tmp_path, fmt):
    hub = make_hub(tmp_path)
    await feed(hub, driving_rig(RIG_A, fmt=fmt))
    rig = FeedBuilder(hub).frame_body(last_seen(hub))["rigs"][0]
    assert (rig["position"], rig["gear"], rig["rpm"], rig["tyre"]["label"]) == ({"x": -412.6, "z": 188.2}, 7, 11240, "C3")


async def test_in_menu_and_no_data_states(tmp_path):
    hub = make_hub(tmp_path, rigs=[RigConfig(ip=RIG_C, name="Window")])
    await feed(hub, driving_rig(RIG_A))
    builder = FeedBuilder(hub)
    seen = last_seen(hub)
    # Packets keep coming but no Motion for > no_motion_after_s (2 s): in menu, telemetry hidden.
    in_menu = builder.frame_body(seen + 3)["rigs"]
    rig_a = next(r for r in in_menu if r["rig_id"] == RIG_A)
    assert rig_a["state"] == "in_menu_paused"
    assert rig_a["position"] is None and rig_a["speed_kph"] is None and rig_a["gear"] is None
    assert rig_a["tyre"] is not None and rig_a["session"]["track_key"] == "F1:7"
    # The configured rig that never sent anything is listed as no_data with nulls.
    window = next(r for r in in_menu if r["rig_id"] == RIG_C)
    assert window["state"] == "no_data" and window["last_seen_ms"] is None
    assert window["session"]["track_key"] is None and window["tyre"] is None
    # Silent for > no_data_after_s: no_data, session cleared.
    gone = builder.frame_body(seen + 10)["rigs"]
    assert next(r for r in gone if r["rig_id"] == RIG_A)["session"]["session_id"] is None


async def test_new_session_clears_previous_values(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, driving_rig(RIG_A, uid=0x11))
    await feed(hub, [(RIG_A, motion(2025, 0x22, 1.0, 2.0))])  # new session: no Session packet yet
    rig = FeedBuilder(hub).frame_body(last_seen(hub))["rigs"][0]
    assert rig["session"]["session_id"] == f"{0x22:016x}"
    assert rig["session"]["track_key"] is None and rig["speed_kph"] is None
    assert rig["position"] == {"x": 1.0, "z": 2.0}


async def test_unknown_track_has_no_key(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [(RIG_A, session(2025, 0x11, track_id=-1))])
    s = FeedBuilder(hub).session(hub.registry.get(RIG_A), last_seen(hub))
    assert (s["track_key"], s["track_name"]) == (None, None)


def test_tyre_classes():
    from simtelemetry.adapters.f1.adapter import tyre_class, tyre_label
    from simtelemetry.adapters.f1.tyres import actual_compound, visual_compound
    assert (tyre_class(visual_compound(17)), tyre_label(actual_compound(19), visual_compound(17))) == ("medium", "C2")
    assert (tyre_class(visual_compound(7)), tyre_label(actual_compound(7), visual_compound(7))) == ("inter", "inter")
    assert tyre_class(visual_compound(99)) == "unknown"
    assert tyre_label(actual_compound(99), visual_compound(16)) == "soft"


# --- rig info, colours, status --------------------------------------------------------------

async def test_rig_info_and_colours(tmp_path):
    hub = make_hub(tmp_path, rigs=[RigConfig(ip=RIG_B, name="Front", colour="#00d2be")])
    await feed(hub, driving_rig(RIG_A) + driving_rig(RIG_C, fmt=2026))
    infos = {r["rig_id"]: r for r in FeedBuilder(hub).rig_infos()}
    assert infos[RIG_B] == {"rig_id": RIG_B, "name": "Front", "colour": "#00d2be", "address": RIG_B, "game": "F1",
                            "data_format": None, "format_supported": True}
    # Auto colours follow the rig number, so they don't move when other rigs appear.
    assert infos[RIG_A]["name"] == "Rig 2" and infos[RIG_A]["colour"] == PALETTE[1]
    assert infos[RIG_C]["name"] == "Rig 3" and infos[RIG_C]["colour"] == PALETTE[2]


async def test_status_warnings(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, driving_rig(RIG_A, fmt=2025) + driving_rig(RIG_B, fmt=2026))
    bad = bytearray(motion(2025, 0x11, 0, 0))[:-3]
    hub.on_datagram(bytes(bad), RIG_C, 0.0)       # wrong size
    unsupported = bytearray(motion(2025, 0x11, 0, 0))
    struct.pack_into("<H", unsupported, 0, 2024)
    hub.on_datagram(bytes(unsupported), RIG_C, 0.0)
    status = FeedBuilder(hub).status(time.monotonic())
    assert status["format_mismatch"] is True
    assert status["formats"] == {RIG_A: "2025", RIG_B: "2026", RIG_C: "2024"}
    codes = [(w["code"], w["rig_id"]) for w in status["warnings"]]
    assert codes == [("format_mismatch", None), ("format_unsupported", RIG_C), ("size_mismatch", RIG_C)]
    assert status["warnings"][0]["message"] == "Rigs send different UDP formats (2024 and 2025 and 2026)"
    assert status["recorder"] is None


def test_size_mismatch_warning_expires(tmp_path):
    hub = make_hub(tmp_path)
    hub.on_datagram(bytes(motion(2025, 0x11, 0, 0))[:-3], RIG_A, 0.0)
    builder = FeedBuilder(hub)
    t = time.monotonic()
    assert [w["code"] for w in builder.status(t)["warnings"]] == ["size_mismatch"]
    assert builder.status(t + 11)["warnings"] == []


def test_recorder_stopped_warning(tmp_path):
    hub = make_hub(tmp_path)
    hub.recorder = Recorder(tmp_path / "rec", disk_free=lambda p: int(0.6 * GB))
    hub.recorder.start()
    status = FeedBuilder(hub).status(time.monotonic())
    assert status["recorder"] == {"state": "stopped", "message": "recording stopped: low disk", "free_gb": 0.6}
    assert status["warnings"] == [{"code": "recorder_stopped", "rig_id": None,
                                   "message": "Recording stopped: low disk (0.6 GB free)"}]
    hub.recorder.close()


# --- per-connection message sequence -------------------------------------------------------

async def test_connection_sequence(tmp_path):
    hub = make_hub(tmp_path, cafe={"name": "Pit Stop", "branding": {"--brand-accent": "#0a7cff"}})
    await feed(hub, driving_rig(RIG_A))
    conn = FeedConnection(FeedBuilder(hub), clock=lambda: 1_791_302_400.123)
    t = last_seen(hub)
    snap = conn.start(t)
    assert (snap["v"], snap["type"], snap["seq"], snap["ts"]) == (1, "snapshot", 0, 1_791_302_400_123)
    assert snap["cafe"] == {"name": "Pit Stop", "branding": {"--brand-accent": "#0a7cff"}, "tagline": "", "logo": None, "wifi": None}
    assert snap["hub"]["frame_hz"] == 15 and snap["outlines"] == []
    assert [(b["period"], b["lap_class"], b["track_name"], b["entries"]) for b in snap["leaderboards"]] == \
        [(p, c, "Silverstone", []) for c in ("open", "pro") for p in ("today", "week", "all_time")]

    # Nothing changed: just a frame (status only once a second).
    assert [m["type"] for m in conn.tick(t + 0.05)] == ["frame"]
    assert [m["type"] for m in conn.tick(t + 1.1)] == ["status", "frame"]

    # A second rig appears and the first changes session.
    await feed(hub, driving_rig(RIG_B) + [(RIG_A, session(2025, 0x99, track_id=10))])
    t2 = last_seen(hub)
    msgs = conn.tick(t2)
    assert [m["type"] for m in msgs] == ["rig_info", "session_changed", "status", "frame"]
    assert msgs[0]["rig"]["rig_id"] == RIG_B
    assert msgs[1]["rig_id"] == RIG_A and msgs[1]["session"]["track_key"] == "F1:10"
    assert [m["seq"] for m in msgs] == [4, 5, 6, 7]  # after snapshot, frame, status, frame


# --- /ws endpoint and static files -----------------------------------------------------------

async def test_websocket_endpoint(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, driving_rig(RIG_A))
    hub.config.dashboard.frame_hz = 20
    with TestClient(create_app(hub, dashboard_dir=tmp_path / "missing")) as client:
        with client.websocket_connect("/ws") as ws:
            msgs = [json.loads(ws.receive_text()) for _ in range(6)]
    assert msgs[0]["type"] == "snapshot"
    assert [m["seq"] for m in msgs] == list(range(6))
    assert {m["type"] for m in msgs[1:]} <= {"frame", "status"}
    assert msgs[0]["rigs"][0]["rig_id"] == RIG_A


def test_dashboard_files_served(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Live timing</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    client = TestClient(create_app(make_hub(tmp_path), dashboard_dir=dist))
    assert "Live timing" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/health").json()["game"] == "F1"


def test_missing_dashboard_explains_how_to_build(tmp_path):
    client = TestClient(create_app(make_hub(tmp_path), dashboard_dir=tmp_path / "nope"))
    page = client.get("/")
    assert page.status_code == 200 and "npm run build" in page.text


def test_frame_rate_limits_in_config(tmp_path):
    from simtelemetry.config import ConfigError, load_config
    path = tmp_path / "hub.toml"
    path.write_text("[dashboard]\nframe_hz = 30\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="frame_hz"):
        load_config(path)


# --- shared fixture with the dashboard's schema validator --------------------------------------

def _shape(value):
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_shape(v) for v in value]
    return type(value).__name__


async def test_sample_feed_matches_dashboard_fixture(tmp_path):
    """dashboard/src/testing/hub-feed.sample.json is validated by the dashboard's schema checker.

    Regenerate with SIMTELEMETRY_UPDATE_FIXTURES=1 when the feed changes on purpose.
    """
    hub = make_hub(tmp_path, rigs=[RigConfig(ip=RIG_C, name="Window")])
    await feed(hub, driving_rig(RIG_A) + driving_rig(RIG_B, fmt=2026, uid=0x22, x=10.5, z=-3.25, name=b"Guest"))
    hub.on_datagram(bytes(motion(2026, 0x22, 0, 0))[:-3], RIG_B, 0.0)  # size warning
    conn = FeedConnection(FeedBuilder(hub), clock=lambda: 1_791_302_400.0)
    t = last_seen(hub)
    messages = [conn.start(t)]
    await feed(hub, drive_full_lap(RIG_A, 0x11, 88123, b"Akshat", steps=60))  # lap side
    messages += conn.tick(last_seen(hub))
    await feed(hub, [(RIG_A, session(2025, 0x33, track_id=10))])
    messages += conn.tick(last_seen(hub))
    if os.environ.get("SIMTELEMETRY_UPDATE_FIXTURES"):
        FIXTURE.write_text(json.dumps(messages, indent=1) + "\n", encoding="utf-8")
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert [m["type"] for m in committed] == [m["type"] for m in messages]
    assert _shape(committed) == _shape(messages), "feed changed: regenerate the fixture (see docstring)"


# --- lap side: live laps, bests, head-to-head, outline, leaderboard ---------------------------

def drive_full_lap(ip, uid, lap_ms, name, fmt=2025, steps=300, length=5891.0):
    """Lap 1 from the line to the end with positions on a circle, then the rollover and history."""
    import math
    from test_laps import history_bytes, lap_data_bytes
    packets = [session(fmt, uid), participants(fmt, uid, name), status(fmt, uid), telemetry(fmt, uid)]
    radius = length / (2 * math.pi)
    for i in range(steps + 1):
        d = length * i / steps
        t = 100.0 + lap_ms / 1000 * i / steps
        a = 2 * math.pi * i / steps
        sector = 0 if d < 1900 else 1 if d < 3900 else 2
        packets.append(motion(fmt, uid, radius * math.cos(a), radius * math.sin(a)))
        packets.append(lap_data_bytes(fmt, uid, t, 1, d, round(lap_ms * i / steps), sector=sector,
                                      s1=28011 if sector >= 1 else 0, s2=33456 if sector >= 2 else 0))
    s3 = lap_ms - 28011 - 33456
    packets.append(lap_data_bytes(fmt, uid, 100.0 + lap_ms / 1000 + 0.05, 2, 1.0, 50, last_ms=lap_ms))
    packets.append(history_bytes(fmt, uid, 100.0 + lap_ms / 1000 + 0.1,
                                 [(lap_ms, 28011, 33456, s3, True), (0, 0, 0, 0, True)]))
    return [(ip, p) for p in packets]


async def test_lap_side_of_the_feed(tmp_path):
    hub = make_hub(tmp_path, map={"flip_z": True})
    conn = FeedConnection(FeedBuilder(hub), clock=lambda: 1_791_302_400.0)
    await feed(hub, driving_rig(RIG_A) + driving_rig(RIG_B))
    conn.start(last_seen(hub))

    await feed(hub, drive_full_lap(RIG_A, 0x11, 88123, b"Akshat"))
    msgs = conn.tick(last_seen(hub))
    types = [m["type"] for m in msgs]
    assert types[:5] == ["lap_completed", "track_outline", "leaderboard", "leaderboard", "leaderboard"]
    lap = msgs[0]["lap"]
    assert (lap["rig_id"], lap["lap_number"], lap["lap_ms"], lap["valid"], lap["session_best"]) == \
        (RIG_A, 1, 88123, True, True)
    outline = msgs[1]["outline"]
    assert outline["track_key"] == "F1:7" and (outline["source"], outline["laps"]) == ("laps", 1)
    assert len(outline["points"]) == round(5891 / 6)      # resampled every ~6 m of lap distance
    assert outline["sector_starts"] is None or outline["sector_starts"][0] == 0
    assert outline["display"] == {"flip_x": False, "flip_z": True, "rotate_deg": 0.0}
    assert [(m["leaderboard"]["period"], m["leaderboard"]["lap_class"]) for m in msgs[2:8]] == \
        [(p, c) for c in ("open", "pro") for p in ("today", "week", "all_time")]
    assert msgs[2]["leaderboard"]["entries"][0]["driver"] == "Akshat"

    frame = next(m for m in msgs if m["type"] == "frame")
    rig_a = next(r for r in frame["rigs"] if r["rig_id"] == RIG_A)
    assert rig_a["best"] == {"lap_ms": 88123, "sectors_ms": [28011, 33456, 26656], "lap_number": 1,
                             "set_at": rig_a["best"]["set_at"]}
    assert rig_a["lap"]["number"] == 2 and rig_a["lap"]["last_sectors"][0] == {"ms": 28011, "rating": "session_best"}

    # Rig B drives 1.5 s slower: head-to-head and live delta against rig A's best lap.
    await feed(hub, drive_full_lap(RIG_B, 0x11, 89623, b"Guest"))
    from test_laps import lap_data_bytes
    await feed(hub, [(RIG_B, motion(2025, 0x11, 0.0, 0.0)),
                     (RIG_B, lap_data_bytes(2025, 0x11, 300.0, 2, 2945.5, 44_500))])  # A passed here at 44062 ms
    msgs = conn.tick(last_seen(hub))
    assert [m["type"] for m in msgs if m["type"] in ("lap_completed", "track_outline", "leaderboard")] == \
        ["lap_completed", "track_outline"] + ["leaderboard"] * 6   # the second lap refines the outline
    comparison = next(m for m in msgs if m["type"] == "frame")["comparison"]
    by_rig = {e["rig_id"]: e for e in comparison["rigs"]}
    assert by_rig[RIG_B]["reference_rig_id"] == RIG_A and by_rig[RIG_B]["best_gap_ms"] == 1500
    assert by_rig[RIG_B]["live_delta_ms"] == 438          # 44500 - 44062 (A's trace holds whole ms)
    assert by_rig[RIG_A]["best_gap_ms"] == -1500
    board = next(m for m in msgs if m["type"] == "leaderboard")["leaderboard"]
    assert [(e["rank"], e["driver"], e["gap_ms"]) for e in board["entries"]] == [(1, "Akshat", 0), (2, "Guest", 1500)]

    # A new connection gets all of it in the snapshot.
    snap = FeedConnection(FeedBuilder(hub)).start(last_seen(hub))
    assert len(snap["outlines"]) == 1 and len(snap["leaderboards"][0]["entries"]) == 2
    assert snap["outlines"][0]["laps"] == 2
    assert [l["driver"] for l in snap["recent_laps"]] == ["Guest", "Akshat"]


async def test_pitwall_record_minis_and_session_story(tmp_path):
    """Today's board carries the record lap's mini-sector times; the snapshot carries the last hour's laps."""
    hub = make_hub(tmp_path)
    await feed(hub, driving_rig(RIG_A))
    await feed(hub, drive_full_lap(RIG_A, 0x11, 88123, b"Akshat"))
    snap = FeedConnection(FeedBuilder(hub)).start(last_seen(hub))
    today = next(b for b in snap["leaderboards"] if b["period"] == "today" and b["lap_class"] == "open")
    assert today["entries"][0]["lap_ms"] == 88123
    minis = today["record_minis"]
    assert minis is not None and len(minis) == 24 and abs(sum(minis) - 88123) < 50
    assert today["mini_owners"] == [RIG_A] * 24
    story = snap["session_story"]
    assert [(l["driver"], l["lap_ms"], l["valid"]) for l in story] == [("Akshat", 88123, True)]


def test_cafe_message_on_branding_change(tmp_path):
    from simtelemetry.core.feed import FeedBuilder, FeedConnection
    from test_drivers import make_hub
    hub = make_hub(tmp_path, store=False)
    conn = FeedConnection(FeedBuilder(hub))
    snap = conn.start(0.0)
    assert snap["cafe"] == {"name": hub.config.cafe.name, "branding": {}, "tagline": "", "logo": None, "wifi": None}
    assert not [m for m in conn.tick(0.0) if m["type"] == "cafe"]
    hub.config.cafe.name, hub.config.cafe.logo = "Lap Lab", "logo.png"
    (msg,) = [m for m in conn.tick(0.0) if m["type"] == "cafe"]
    assert msg["cafe"]["name"] == "Lap Lab" and msg["cafe"]["logo"] == "/api/cafe/logo?v=logo.png"
