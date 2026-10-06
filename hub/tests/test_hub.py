"""Pipeline tests: synthetic packets through Hub.on_datagram -> consumer -> registry/health/API."""

import asyncio
import struct
import time

import pytest
from fastapi.testclient import TestClient

from simtelemetry.adapters.f1.adapter import F1Adapter
from simtelemetry.api.app import create_app
from simtelemetry.config import AppConfig
from simtelemetry.core.rigs import RigRegistry
from simtelemetry.hub import Hub, format_lap_time

from f1_helpers import blank_packet

RIG_A, RIG_B = "192.168.1.21", "192.168.1.22"
UID = 0x1122334455667788


def participants(fmt, name: bytes, player=0):
    pkt = blank_packet(fmt, 4, player=player, session_uid=UID)
    stride, name_at = (57, 7) if fmt == 2025 else (60, 10)
    pkt[29] = 1
    pkt[30 + player * stride + name_at:30 + player * stride + name_at + len(name)] = name
    return bytes(pkt)


def session(fmt, track_id):
    pkt = blank_packet(fmt, 1, session_uid=UID)
    struct.pack_into("<bB", pkt, 35, 18, 0)  # session type Time Trial
    struct.pack_into("<b", pkt, 36, track_id)
    return bytes(pkt)


def lap_data(fmt, lap, current_ms, player=0):
    pkt = blank_packet(fmt, 2, player=player, session_uid=UID)
    if player != 255:
        struct.pack_into("<II", pkt, 29 + player * 57, 0, current_ms)
        pkt[29 + player * 57 + 33] = lap
    return bytes(pkt)


def telemetry(fmt, speed, player=0):
    stride = 60 if fmt == 2025 else 59
    pkt = blank_packet(fmt, 6, player=player, session_uid=UID)
    struct.pack_into("<H", pkt, 29 + player * stride, speed)
    return bytes(pkt)


def motion(fmt, player=0):
    return bytes(blank_packet(fmt, 0, player=player, session_uid=UID))


def make_hub(tmp_path, **cfg):
    config = AppConfig(data_dir=tmp_path, **cfg)
    return Hub(config, F1Adapter(config.track_names), RigRegistry(config, tmp_path / "rigs.json"))


async def feed(hub, packets):
    consumer = asyncio.create_task(hub.consume())
    for ip, data in packets:
        hub.on_datagram(data, ip, 0.0)
    await hub.drain()
    consumer.cancel()


async def test_pipeline_populates_registry_and_live_summary(tmp_path):
    hub = make_hub(tmp_path, track_names={7: "Silverstone GP"})
    await feed(hub, [
        (RIG_A, participants(2025, "Akshat".encode())),
        (RIG_A, session(2025, 7)),
        (RIG_A, lap_data(2025, 3, 83456)),
        (RIG_A, telemetry(2025, 287)),
        (RIG_A, motion(2025)),
    ])
    rig = hub.registry.get(RIG_A)
    assert (rig.name, rig.data_format, rig.session_id, rig.driver_name) == \
        ("Rig 1", "2025", f"{UID:016x}", "Akshat")
    line = hub.listen_line(rig, time.monotonic())
    for part in ("Rig 1", RIG_A, "fmt=2025", "Silverstone GP", "lap 3", "1:23.456", "287 km/h", "driving"):
        assert part in line


async def test_size_mismatch_counted_not_decoded(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [(RIG_A, motion(2025)[:-1]), (RIG_A, motion(2025)[:-1]), (RIG_A, b"short")])
    h = hub.health.get(RIG_A)
    assert dict(h.drops) == {"size_mismatch": 2, "too_short": 1}
    assert sum(h.totals.values()) == 0


async def test_unsupported_format_registered_and_flagged(tmp_path):
    hub = make_hub(tmp_path)
    pkt = bytearray(motion(2025))
    struct.pack_into("<H", pkt, 0, 2024)
    await feed(hub, [(RIG_A, bytes(pkt))])
    snap = hub.health_snapshot()["rigs"][0]
    assert snap["data_format"] == "2024"
    assert snap["format_supported"] is False
    assert snap["drops"] == {"unsupported_format": 1}


async def test_format_mismatch_warning(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [(RIG_A, motion(2025)), (RIG_B, motion(2026))])
    snap = hub.health_snapshot()
    assert snap["format_mismatch"] is True
    assert snap["formats"] == {RIG_A: "2025", RIG_B: "2026"}
    assert any("different packet formats" in line for line in hub.summary_lines(time.monotonic()))


async def test_same_format_no_warning(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [(RIG_A, motion(2026)), (RIG_B, motion(2026))])
    assert hub.health_snapshot()["format_mismatch"] is False


async def test_bad_player_index_does_not_break_pipeline(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [(RIG_A, motion(2025, player=255)), (RIG_A, lap_data(2025, 1, 1000, player=255))])
    h = hub.health.get(RIG_A)
    assert h.totals["Motion"] == 1 and h.last_driving is None  # no player car -> not "driving"


async def test_recorder_sees_every_datagram_including_rejected(tmp_path):
    class FakeRecorder:
        current_path = None

        def __init__(self):
            self.items = []

        def write(self, *item):
            self.items.append(item)

    hub = make_hub(tmp_path)
    hub.recorder = FakeRecorder()
    await feed(hub, [(RIG_A, motion(2025)), (RIG_A, b"junk")])
    assert [(ip, data) for _, ip, data in hub.recorder.items] == [(RIG_A, motion(2025)), (RIG_A, b"junk")]


async def test_api_health(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [(RIG_A, participants(2026, b"Driver A")), (RIG_A, motion(2026))])
    hub.health.tick(0)
    client = TestClient(create_app(hub))
    body = client.get("/api/health").json()
    assert body["game"] == "F1"
    rig = body["rigs"][0]
    assert rig["ip"] == RIG_A and rig["name"] == "Rig 1" and rig["driver_name"] == "Driver A"
    assert rig["state"] == "driving"
    assert rig["data_format"] == "2026"
    assert rig["packets_total"] == 2


@pytest.mark.parametrize("ms,text", [(0, "0:00.000"), (83456, "1:23.456"), (600001, "10:00.001")])
def test_format_lap_time(ms, text):
    assert format_lap_time(ms) == text


async def test_low_disk_stop_shown_in_health_and_summary(tmp_path):
    from simtelemetry.tools.recorder import Recorder

    hub = make_hub(tmp_path)
    hub.recorder = Recorder(tmp_path / "rec", disk_free=lambda p: 100 * 1024 ** 2)  # 0.1 GB free
    hub.recorder.start()
    await feed(hub, [(RIG_A, motion(2025))])  # hub keeps working without the recorder
    snap = hub.health_snapshot()
    assert snap["recording"] is None
    assert snap["recorder"]["state"] == "stopped"
    assert snap["recorder"]["message"] == "recording stopped: low disk"
    assert snap["rigs"][0]["packets_total"] == 1
    assert hub.summary_lines(time.monotonic())[0].startswith("recording stopped: low disk (0.1 GB free")
    hub.recorder.close()
