"""Story cards: mini-sector times, the card made when a session ends, card API and QR, feature switch."""

from __future__ import annotations

from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.laps import MINI_SECTORS, LapCompleted, LapContext, LiveLap, Trace, mini_sector_times

from test_drivers import RIG, client_with_rig

LENGTH = 4800.0


def full_trace(lap: int, lap_ms: int) -> Trace:
    """Constant speed round a straight-line 'track'."""
    trace = Trace(lap)
    for i in range(0, 481):
        d = i * 10.0
        trace.add(d, round(lap_ms * d / LENGTH), d, 0.0)
    return trace


def test_mini_sector_times_add_up_to_the_lap():
    minis = mini_sector_times(full_trace(2, 96000), LENGTH, 96000)
    assert len(minis) == MINI_SECTORS and sum(minis) == 96000 and set(minis) == {4000}
    partial = Trace(2)
    partial.add(2000.0, 40000, 0, 0)
    assert mini_sector_times(partial, LENGTH, 96000) is None
    assert mini_sector_times(None, LENGTH, 96000) is None


def drive(hub, n, lap_ms, driver):
    """One lap on the rig with a full trace, as the hub would record it."""
    ctx = LapContext(rig_name="Rig 1", driver=driver, track_key="F1:7", track_name="Silverstone", session_id="s",
                     position=(0.0, 0.0), track_length_m=LENGTH, driver_id=hub.drivers.driver_id(RIG))
    rig = hub.laps.rig(RIG)
    rig.traces[n] = full_trace(n, lap_ms)
    hub.laps.update(RIG, ctx, LiveLap(n + 1, 5.0, 100, True, 0, None, None, lap_ms), [
        LapCompleted(n, 0.0, lap_ms, (30000, 33000, lap_ms - 63000), True, False, "test")])


async def test_ending_a_session_makes_a_card_with_qr(tmp_path):
    hub, client = await client_with_rig(tmp_path)
    client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Maya", "minutes": 20})
    hub._session_top_kph[RIG] = 311
    drive(hub, 2, 96000, "Maya")
    drive(hub, 3, 95000, "Maya")
    r = client.delete(f"/api/staff/rigs/{RIG}/driver").json()
    link = r["card"]
    assert link["driver"] == "Maya" and link["url"].endswith("/card/" + link["token"])

    card = client.get(f"/api/cards/{link['token']}").json()
    assert (card["driver"], card["track_name"], card["laps"], card["best_ms"], card["top_speed_kph"]) == \
        ("Maya", "Silverstone", 2, 95000, 311)
    assert card["theoretical_ms"] == 30000 + 33000 + 32000
    assert card["today_position"] == 1 and card["today_drivers"] == 1
    assert len(card["minis"]) == MINI_SECTORS and {m["rating"] for m in card["minis"]} == {"purple"}

    qr = client.get(f"/api/cards/{link['token']}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"] == "image/svg+xml" and b"<svg" in qr.content
    assert client.get("/api/cards/nope").status_code == 404

    moments = [b["moment"] for _, t, b in hub.laps.messages if t == "moment" and b["moment"]["kind"] == "card"]
    assert moments[-1]["token"] == link["token"] and moments[-1]["best_ms"] == 95000


async def test_no_card_without_a_lap_and_replacing_a_driver_makes_one(tmp_path):
    hub, client = await client_with_rig(tmp_path)
    client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Maya"})
    assert client.delete(f"/api/staff/rigs/{RIG}/driver").json()["card"] is None   # no lap: no card
    client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Maya"})
    drive(hub, 2, 96000, "Maya")
    bad = client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": ""})
    assert bad.status_code == 400 and hub.drivers.get(RIG).name == "Maya"           # still Maya's session
    r = client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Kofi"}).json()
    assert r["card"]["driver"] == "Maya" and r["session"]["name"] == "Kofi"


async def test_sharing_can_be_switched_off(tmp_path):
    hub, client = await client_with_rig(tmp_path, features={"sharing": False})
    client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Maya"})
    drive(hub, 2, 96000, "Maya")
    assert client.delete(f"/api/staff/rigs/{RIG}/driver").json()["card"] is None


def test_card_page_serves_the_dashboard(tmp_path):
    from test_drivers import make_hub
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>TV</title>", encoding="utf-8")
    client = TestClient(create_app(make_hub(tmp_path), dashboard_dir=dist))
    assert client.get("/card/abc123").text == client.get("/").text
