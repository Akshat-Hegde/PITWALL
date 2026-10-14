"""Guest Wi-Fi QR: optional owner setting, encoded server-side for the TV."""

from __future__ import annotations

from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.setup_code import SetupCode
from simtelemetry.core.wifi import wifi_share, wifi_string

from test_drivers import make_hub

GOOD = {"name": "Lap Lab", "tagline": "", "accent": "#FF2A6D", "owner_pin": "2468",
        "staff_pin": "", "open_hour": 10, "close_hour": 22}
WIFI = {"wifi_ssid": "Cafe Guest", "wifi_password": "secret-pass", "wifi_security": "WPA"}


def _client(tmp_path, **cfg):
    code = SetupCode(tmp_path).new()
    hub = make_hub(tmp_path, **cfg)
    return hub, TestClient(create_app(hub, dashboard_dir=tmp_path / "none")), {"X-Setup-Code": code}


def test_escapes_special_characters():
    bs = chr(92)
    ssid, password = f'a;b,c:d{bs}e"f', f'p;w,d:{bs}"x'
    expected = (f'WIFI:T:WPA;S:a{bs};b{bs},c{bs}:d{bs}{bs}e{bs}"f;'
                f'P:p{bs};w{bs},d{bs}:{bs}{bs}{bs}"x;;')
    assert wifi_string(ssid, password, "WPA") == expected


def test_open_network_has_no_password_field():
    s = wifi_string("Open Cafe", "", "nopass")
    assert s == "WIFI:T:nopass;S:Open Cafe;;" and ";P:" not in s


def test_save_and_feed(tmp_path):
    hub, client, code = _client(tmp_path)
    assert client.post("/api/setup", json={**GOOD, **WIFI}, headers=code).status_code == 200
    assert hub.config.cafe.wifi_ssid == "Cafe Guest"
    assert wifi_share(hub.config) == {"ssid": "Cafe Guest", "qr": "WIFI:T:WPA;S:Cafe Guest;P:secret-pass;;"}
    from simtelemetry.core.feed import FeedBuilder
    assert FeedBuilder(hub).cafe()["wifi"] == wifi_share(hub.config)


def test_get_setup_never_returns_password(tmp_path):
    _, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, **WIFI}, headers=code)
    body = client.get("/api/setup")
    assert "secret-pass" not in body.text and "wifi_password" not in body.text
    assert body.json()["wifi_ssid"] == "Cafe Guest" and body.json()["wifi_security"] == "WPA"
    post = client.post("/api/setup", json={**GOOD, **WIFI}, headers={"X-Owner-Pin": "2468"})
    assert "secret-pass" not in post.text


def test_blank_password_keeps_it(tmp_path):
    hub, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, **WIFI}, headers=code)
    again = {**GOOD, **WIFI, "wifi_password": "", "name": "Lap Lab 2"}
    assert client.post("/api/setup", json=again, headers={"X-Owner-Pin": "2468"}).status_code == 200
    assert hub.config.cafe.wifi_password == "secret-pass"
    open_net = {**again, "wifi_security": "nopass"}
    assert client.post("/api/setup", json=open_net, headers={"X-Owner-Pin": "2468"}).status_code == 200
    assert wifi_share(hub.config)["qr"] == "WIFI:T:nopass;S:Cafe Guest;;"


def test_wifi_null_when_sharing_off_or_no_ssid(tmp_path):
    hub, client, code = _client(tmp_path)
    assert wifi_share(hub.config) is None                      # no SSID
    client.post("/api/setup", json={**GOOD, **WIFI}, headers=code)
    hub.config.features.sharing = False
    assert wifi_share(hub.config) is None


def test_validation(tmp_path):
    _, client, code = _client(tmp_path)
    for bad in ({"wifi_ssid": "x" * 33, "wifi_password": "secret-pass"},
                {"wifi_ssid": "ok", "wifi_password": "short"},
                {"wifi_ssid": "ok", "wifi_password": "x" * 64},
                {"wifi_ssid": "ok", "wifi_password": "", "wifi_security": "WPA"},
                {"wifi_ssid": "ok", "wifi_password": "secret-pass", "wifi_security": "nopass"},
                {"wifi_ssid": "ok", "wifi_password": "secret-pass", "wifi_security": "WEP"}):
        r = client.post("/api/setup", json={**GOOD, "wifi_security": "WPA", **bad}, headers=code)
        assert r.status_code == 400, bad


def test_password_only_in_qr_string(tmp_path):
    hub, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, **WIFI}, headers=code)
    from simtelemetry.core.feed import FeedBuilder
    snap = FeedBuilder(hub).snapshot_body(0.0)
    assert snap["cafe"]["wifi"]["ssid"] == "Cafe Guest" and "secret-pass" not in snap["cafe"]["wifi"]["ssid"]
    import json
    wifi = {k: v for k, v in snap["cafe"]["wifi"].items() if k != "qr"}
    rest = {**snap, "cafe": {**snap["cafe"], "wifi": wifi}}
    assert "secret-pass" not in json.dumps(rest)
    assert "secret-pass" in snap["cafe"]["wifi"]["qr"]


def test_clearing_ssid_clears_password(tmp_path):
    hub, client, code = _client(tmp_path)
    client.post("/api/setup", json={**GOOD, **WIFI}, headers=code)
    cleared = {**GOOD, "wifi_ssid": "", "wifi_password": "", "wifi_security": "WPA"}
    assert client.post("/api/setup", json=cleared, headers={"X-Owner-Pin": "2468"}).status_code == 200
    assert hub.config.cafe.wifi_password == ""
    assert wifi_share(hub.config) is None
