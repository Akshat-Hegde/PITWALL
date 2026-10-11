"""TV page control: staff choose LIVE / MULTIVIEW, the strip's rig and a view over the page; kept across restarts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.feed import FeedBuilder, FeedConnection
from simtelemetry.core.tv import TvControl, TvError

from test_drivers import RIG, client_with_rig, make_hub


def test_setting_is_kept_but_the_overlay_is_not(tmp_path):
    tv = TvControl(tmp_path / "tv.json", clock=lambda: 100.0)
    assert tv.to_json() == {"page": "live", "pinned_rig": None, "overlay": None, "updated_at": 0}
    tv.set(page="multi", pinned_rig="10.0.0.2", overlay="head_to_head")
    again = TvControl(tmp_path / "tv.json")
    assert (again.page, again.pinned_rig, again.overlay, again.updated_at) == ("multi", "10.0.0.2", None, 100_000)
    with pytest.raises(TvError):
        tv.set(page="onboard")
    with pytest.raises(TvError):
        tv.set(overlay="bracket")                      # the tournament preview is demo-only, never staff-triggered


async def test_staff_api_and_feed_message(tmp_path):
    hub, client = await client_with_rig(tmp_path, staff={"pin": "1111"})
    pin = {"X-Staff-Pin": "1111"}
    assert client.put("/api/staff/tv", json={"page": "multi"}).status_code == 401
    conn = FeedConnection(FeedBuilder(hub))
    snap = conn.start(0.0)
    assert snap["tv"]["page"] == "live"
    r = client.put("/api/staff/tv", json={"page": "multi", "pinned_rig": RIG}, headers=pin)
    assert r.status_code == 200 and (r.json()["page"], r.json()["pinned_rig"]) == ("multi", RIG)
    msgs = [m for m in conn.tick(0.0) if m["type"] == "tv"]
    assert len(msgs) == 1 and msgs[0]["tv"]["page"] == "multi"
    assert not [m for m in conn.tick(0.0) if m["type"] == "tv"]           # only on change
    assert client.put("/api/staff/tv", json={"pinned_rig": "10.9.9.9"}, headers=pin).status_code == 404
    assert client.put("/api/staff/tv", json={"page": "x"}, headers=pin).status_code == 400
    assert client.put("/api/staff/tv", json={"overlay": "head_to_head"}, headers=pin).json()["overlay"] == "head_to_head"
    assert client.get("/api/staff/tv", headers=pin).json()["overlay"] == "head_to_head"
    assert 'data-tv-page="multi"' in client.get("/staff").text


def test_overlays_follow_features(tmp_path):
    hub = make_hub(tmp_path, features={"head_to_head": False})
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    r = client.put("/api/staff/tv", json={"overlay": "head_to_head"})
    assert r.status_code == 400 and "switched off" in r.json()["detail"]
