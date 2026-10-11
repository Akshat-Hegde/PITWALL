"""Demo simulator: its packets pass the gate and drive the real pipeline (laps, outline, Pro, head to head)."""

from __future__ import annotations

import asyncio

from simtelemetry.adapters.f1.adapter import F1Adapter
from simtelemetry.config import AppConfig
from simtelemetry.core.rigs import RigRegistry
from simtelemetry.hub import Hub
from simtelemetry.tools.demo_sim import TRACK_ID, DemoSimulator, rig_ip


async def test_simulated_rigs_drive_the_real_pipeline(tmp_path):
    config = AppConfig(data_dir=tmp_path, track_names={TRACK_ID: "Demo Circuit"})
    hub = Hub(config, F1Adapter(config.track_names), RigRegistry(config, tmp_path / "rigs.json"))
    sim = DemoSimulator(hub, rigs=3)
    consumer = asyncio.create_task(hub.consume())
    for _ in range(20 * 60 * 4):                 # four simulated minutes, as fast as possible
        sim.step()
        if sim.tick % 200 == 0:
            await hub.drain()
    await hub.drain()
    consumer.cancel()

    assert all(h.drops == {} for h in (hub.health.get(rig_ip(n)) for n in (1, 2, 3)))  # no packet rejected
    assert [r.name for r in hub.registry.all()] == ["Rig 1", "Rig 2", "Rig 3"]
    s = hub.adapter.live_summary(rig_ip(1))
    assert s.track == "Demo Circuit" and s.driver_name == "Apex_Hunter" and s.pro is True
    assert hub.adapter.live_summary(rig_ip(2)).pro is False
    counted = [r for r in hub.laps.laps if r.counted]
    assert len(counted) >= 3 and all(80_000 < r.lap_ms < 100_000 for r in counted)
    assert {r.lap_class for r in counted if r.rig_id == rig_ip(1)} == {"pro"}
    assert {r.lap_class for r in counted if r.rig_id == rig_ip(2)} == {"open"}
    assert f"F1:{TRACK_ID}" in hub.laps.outlines
    assert hub.laps.head_to_head(f"F1:{TRACK_ID}") is not None


async def test_demo_director_triggers_every_moment(tmp_path):
    from fastapi.testclient import TestClient
    from simtelemetry.api.app import create_app
    from simtelemetry.core.store import LapStore
    from simtelemetry.tools.demo_director import DemoDirector
    from simtelemetry.tools.seed_demo import seed

    seed(tmp_path / "demo", days=3)
    config = AppConfig(data_dir=tmp_path / "demo", track_names={TRACK_ID: "Demo Circuit"})
    hub = Hub(config, F1Adapter(config.track_names), RigRegistry(config, tmp_path / "rigs.json"),
              store=LapStore(tmp_path / "demo" / "laps.db"))
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    assert client.get("/api/staff/rigs").json()["demo"] is False
    assert client.post("/api/staff/demo/podium").status_code == 404     # only in demo mode

    sim = DemoSimulator(hub, rigs=3)
    hub.demo = DemoDirector(hub, sim)
    hub.demo.start_sessions()
    consumer = asyncio.create_task(hub.consume())
    for _ in range(20 * 60 * 4):
        sim.step()
        if sim.tick % 200 == 0:
            await hub.drain()
    await hub.drain()
    consumer.cancel()
    assert all(hub.drivers.get(r.ip) is not None for r in sim.rigs)    # every rig has a booked profile

    def kinds():
        return [b["moment"]["kind"] for _, t, b in hub.laps.messages if t == "moment"]

    assert client.get("/api/staff/rigs").json()["demo"] is True
    for action, body in [("now_driving", {}), ("record", {"period": "all_time", "lap_class": "pro"}),
                         ("record", {"period": "today", "lap_class": "open"}), ("battle", {}), ("podium", {}),
                         ("challenge_winner", {}), ("card", {})]:
        r = client.post(f"/api/staff/demo/{action}", json=body)
        assert r.status_code == 200, (action, r.json())
    assert {"now_driving", "record", "battle", "podium", "challenge_winner", "card"} <= set(kinds())
    before = hub.laps.last_message_id
    client.post("/api/staff/demo/record", json={"period": "all_time", "lap_class": "pro"})
    (record,) = [b["moment"] for _, t, b in hub.laps.messages_after(before) if t == "moment"]
    assert [(r["period"], r["lap_class"]) for r in record["records"]] == [("all_time", "pro"), ("today", "pro")]
    assert client.post("/api/staff/demo/fireworks").status_code == 400


def test_run_demo_is_one_command(tmp_path):
    import socket
    from simtelemetry.__main__ import main
    from simtelemetry.core.store import LapStore

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    demo = tmp_path / "demo"
    assert main(["run", "--demo", "--data-dir", str(demo), "--http-port", str(port), "--duration", "3"]) == 0
    store = LapStore(demo / "laps.db")
    assert store.count() > 1000 and store.outlines() and store.queue()      # seeded history, outline, queue
    assert (demo / ".simtelemetry-demo").exists()
    store.close()
