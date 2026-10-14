"""Self check-in: codes, the JSON API, the bad-name filter and staff code management."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.checkin import CheckinSession
from simtelemetry.core.names import is_blocked

from test_drivers import RIG, client_with_rig, feed, lap_packets, make_hub
from test_feed import participants, session

UID = 0x51
LAP1 = (89000, 28000, 33000, 28000, True)


async def checkin_client(tmp_path, **cfg):
    hub, client = await client_with_rig(tmp_path, **cfg)
    code = client.get("/api/staff/checkin/codes").json()["rigs"][0]["code"]
    return hub, client, code


def post(client, code, name="Maya", ip=None):
    return client.post(f"/api/checkin/{code}", json={"name": name})


# --- the main flows ----------------------------------------------------------------------------

async def test_free_rig_starts_a_session_and_laps_go_under_the_name(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [session(2025, UID), participants(2025, UID, b"Akshat")])
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    code = client.get("/api/staff/checkin/codes").json()["rigs"][0]["code"]

    assert client.get(f"/api/checkin/{code}").json() == {"rig_name": "Rig 1", "state": "free", "laps": 0}
    r = post(client, code, "  Maya  ")
    assert r.status_code == 200
    body = r.json()
    assert body["rig_name"] == "Rig 1" and body["driver"] == "Maya" and body["secret"]
    assert body["status_url"] == f"/api/checkin/{code}?secret={body['secret']}"

    (rig,) = client.get("/api/staff/rigs").json()["rigs"]
    assert rig["session"]["name"] == "Maya" and rig["session"]["ends_at"] is None

    await feed(hub, lap_packets(1, 89000, [LAP1], 10.0))
    assert [(r.driver) for r in hub.laps.laps] == ["Maya"]
    status = client.get(f"/api/checkin/{code}", params={"secret": body["secret"]}).json()
    assert status["state"] == "yours" and status["driver"] == "Maya"
    assert status["laps"] == 1 and status["best_ms"] == 89000
    hub.laps.store.close()


async def test_busy_rig_is_409_and_leaks_no_name(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    assert post(client, code, "Maya").status_code == 200
    r = post(client, code, "Kofi")
    assert r.status_code == 409 and "Rig 1 is in use" in r.json()["detail"]
    assert "Maya" not in r.text
    anon = client.get(f"/api/checkin/{code}").json()
    assert anon == {"rig_name": "Rig 1", "state": "busy", "laps": 0} and "Maya" not in json.dumps(anon)
    wrong = client.get(f"/api/checkin/{code}", params={"secret": "nope"}).json()
    assert wrong["state"] == "busy" and "driver" not in wrong
    assert hub.drivers.get(RIG).name == "Maya"


async def test_idle_takeover_after_120_s_makes_the_previous_card(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [session(2025, UID), participants(2025, UID, b"Akshat")])
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    code = client.get("/api/staff/checkin/codes").json()["rigs"][0]["code"]
    hub.drivers._clock = lambda: time.time() - 600          # Maya's session began 10 minutes ago
    first = post(client, code, "Maya").json()
    hub.drivers._clock = time.time
    await feed(hub, lap_packets(1, 89000, [LAP1], 10.0))     # one counted lap, so a card exists

    now = time.monotonic()
    hub.health.on_packet(RIG, "motion", now - 60, True)      # driving a minute ago: still busy
    assert post(client, code, "Kofi").status_code == 409
    hub.health._rigs[RIG].last_driving = None
    hub.health.on_packet(RIG, "motion", now - 130, True)     # driving 130 s ago, the pause since is idle
    hub.health.on_packet(RIG, "session", now - 1, False)

    r = post(client, code, "Kofi")
    assert r.status_code == 200 and r.json()["driver"] == "Kofi"
    assert hub.drivers.get(RIG).name == "Kofi"
    old = client.get(f"/api/checkin/{code}", params={"secret": first["secret"]}).json()
    assert old["state"] == "ended" and "/card/" in old["card_url"]
    hub.laps.store.close()


async def test_a_session_staff_just_started_is_not_taken_over(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    hub.drivers.assign(RIG, "Staff pick")                    # started moments ago, never driven
    assert post(client, code, "Kofi").status_code == 409


async def test_done_gives_the_card_url_and_a_wrong_secret_is_403(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [session(2025, UID), participants(2025, UID, b"Akshat")])
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    code = client.get("/api/staff/checkin/codes").json()["rigs"][0]["code"]
    secret = post(client, code, "Maya").json()["secret"]
    await feed(hub, lap_packets(1, 89000, [LAP1], 10.0))

    assert client.post(f"/api/checkin/{code}/done", json={"secret": "wrong"}).status_code == 403
    assert hub.drivers.get(RIG) is not None
    done = client.post(f"/api/checkin/{code}/done", json={"secret": secret})
    assert done.status_code == 200 and "/card/" in done.json()["card_url"]
    assert hub.drivers.get(RIG) is None
    ended = client.get(f"/api/checkin/{code}", params={"secret": secret}).json()
    assert ended["state"] == "ended" and ended["card_url"] == done.json()["card_url"]
    assert client.post(f"/api/checkin/{code}/done", json={"secret": secret}).status_code == 403  # old secret
    hub.laps.store.close()


async def test_done_without_laps_has_no_card(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    secret = post(client, code, "Maya").json()["secret"]
    done = client.post(f"/api/checkin/{code}/done", json={"secret": secret})
    assert done.status_code == 200 and done.json() == {"card_url": None}


async def test_a_secret_of_another_rig_does_not_end_this_rigs_session(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    post(client, code, "Maya")
    hub.checkin.secrets["other"] = CheckinSession(rig_id="192.168.1.99", started_at=hub.drivers.get(RIG).started_at,
                                                  name="Maya")
    assert client.post(f"/api/checkin/{code}/done", json={"secret": "other"}).status_code == 403


# --- codes, feature switch, rate limit -----------------------------------------------------------

async def test_invalid_code_is_404_json_and_a_friendly_page(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    assert client.get("/api/checkin/nonsense1").status_code == 404
    assert post(client, "nonsense1").status_code == 404
    assert client.post("/api/checkin/nonsense1/done", json={"secret": "x"}).status_code == 404
    page = client.get("/checkin/nonsense1")
    assert page.status_code == 404 and "no longer valid" in page.text and "{{PRODUCT_NAME}}" not in page.text
    ok = client.get(f"/checkin/{code}")
    assert ok.status_code == 200 and "{{PRODUCT_NAME}}" not in ok.text


async def test_codes_are_8_url_safe_characters_and_persist(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    assert len(code) == 8 and code.replace("-", "").replace("_", "").isalnum()
    stored = json.loads((tmp_path / "checkin.json").read_text())
    assert stored == {RIG: code}
    assert client.get("/api/staff/checkin/codes").json()["rigs"][0]["code"] == code


async def test_feature_off_is_403_and_a_friendly_page(tmp_path):
    from simtelemetry.config import FeaturesConfig
    hub, client, code = await checkin_client(tmp_path)
    hub.config.features = FeaturesConfig(self_checkin=False)
    assert client.get(f"/api/checkin/{code}").status_code == 403
    assert post(client, code).status_code == 403
    assert client.post(f"/api/checkin/{code}/done", json={"secret": "x"}).status_code == 403
    page = client.get(f"/checkin/{code}")
    assert "switched off" in page.text and "ask staff" in page.text
    assert hub.drivers.get(RIG) is None


async def test_rate_limit_is_10_posts_a_minute_per_client(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    now = [1000.0]
    hub.checkin.clock = lambda: now[0]
    for _ in range(10):
        assert post(client, code, "x" * 40).status_code == 400   # still counts: it was a POST
    assert post(client, code, "Maya").status_code == 429
    now[0] += 61
    assert post(client, code, "Maya").status_code == 200


async def test_name_filter_and_validation_on_the_api(tmp_path):
    hub, client, code = await checkin_client(tmp_path, checkin={"blocked_words": ["Voldemort"]})
    for bad in ("f.u.c.k", "Voldemort"):
        r = post(client, code, bad)
        assert r.status_code == 400 and r.json()["detail"] == "Please choose another name."
    assert post(client, code, "").status_code == 400
    assert hub.drivers.get(RIG) is None
    assert post(client, code, "Scunthorpe").status_code == 200


# --- the bad-name filter ----------------------------------------------------------------------

@pytest.mark.parametrize("name", ["fuck", "FUCK you", "what the f u c k", "sh1t", "b00bs", "@ss", "$hit",
                                  "f.u.c.k", "fuuuuck", "madarchod", "Bhenchod", "x chutiya", "fück", "shït"])
def test_bad_names_are_blocked(name):
    assert is_blocked(name)


@pytest.mark.parametrize("name", ["Ashish", "Scunthorpe", "Maya R", "Kofi", "Assam", "Dickson", "Classic",
                                  "Hancock", "Sussex", "Lund", "Penistone", "Akshat", "Mia 2", "Rand", "Randi", "Kuta",
                                  "Niga"])
def test_normal_names_pass(name):
    assert not is_blocked(name)


def test_custom_words_extend_the_list():
    assert not is_blocked("Voldemort")
    assert is_blocked("Voldemort", ["voldemort"]) and is_blocked("v0ldemort", ["Voldemort"])


# --- staff codes ------------------------------------------------------------------------------

async def test_staff_regenerate_invalidates_the_old_code(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    r = client.post(f"/api/staff/checkin/codes/{RIG}/regenerate")
    assert r.status_code == 200
    new = r.json()["code"]
    assert new != code and len(new) == 8 and r.json()["url"].endswith(f"/checkin/{new}")
    assert client.get(f"/api/checkin/{code}").status_code == 404
    assert client.get(f"/api/checkin/{new}").status_code == 200
    assert json.loads((tmp_path / "checkin.json").read_text()) == {RIG: new}
    assert client.post("/api/staff/checkin/codes/10.9.9.9/regenerate").status_code == 404


async def test_staff_codes_need_the_pin(tmp_path):
    from simtelemetry.config import StaffConfig
    hub, client = await client_with_rig(tmp_path, staff=StaffConfig(pin="1234"))
    assert client.get("/api/staff/checkin/codes").status_code == 401
    assert client.post(f"/api/staff/checkin/codes/{RIG}/regenerate").status_code == 401
    ok = client.get("/api/staff/checkin/codes", headers={"X-Staff-Pin": "1234"})
    assert ok.status_code == 200 and ok.json()["rigs"][0]["rig_name"] == "Rig 1"


# --- fix round 1 -------------------------------------------------------------------------------

async def test_non_ascii_codes_are_just_invalid(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    assert client.get("/api/checkin/é").status_code == 404
    assert client.post("/api/checkin/é", json={"name": "Maya"}).status_code == 404
    assert client.post("/api/checkin/é/done", json={"secret": "x"}).status_code == 404
    page = client.get("/checkin/é")
    assert page.status_code == 404 and "no longer valid" in page.text
    assert client.get("/checkin/" + "a" * 500).status_code == 404


async def test_staff_ending_the_session_keeps_the_card_link(tmp_path):
    hub = make_hub(tmp_path)
    await feed(hub, [session(2025, UID), participants(2025, UID, b"Akshat")])
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    code = client.get("/api/staff/checkin/codes").json()["rigs"][0]["code"]
    secret = post(client, code, "Maya").json()["secret"]
    await feed(hub, lap_packets(1, 89000, [LAP1], 10.0))
    ended = client.delete(f"/api/staff/rigs/{RIG}/driver").json()
    assert ended["card"]["url"]
    status = client.get(f"/api/checkin/{code}", params={"secret": secret}).json()
    assert status["state"] == "ended" and status["card_url"] == ended["card"]["url"]
    hub.laps.store.close()


async def test_old_secrets_and_idle_clients_are_pruned(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    svc = hub.checkin
    now = [time.time()]
    svc.wall = lambda: now[0]
    svc.clock = lambda: now[0]
    secret = post(client, code, "Maya").json()["secret"]
    assert secret in svc.secrets and "testclient" in svc._posts
    now[0] += 13 * 3600                       # still "current" but over 12 h old
    svc.allow("someone-else")
    svc.lookup(RIG, secret)
    assert secret not in svc.secrets
    assert "testclient" not in svc._posts


async def test_corrupt_codes_file_warns_and_regenerates(tmp_path, caplog):
    (tmp_path / "checkin.json").write_text("{not json", encoding="utf-8")
    hub, client, code = await checkin_client(tmp_path)
    assert len(code) == 8 and "stickers stop working" in caplog.text
