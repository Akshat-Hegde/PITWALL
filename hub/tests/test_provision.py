"""Provisioning a cafe's baked-in profile (spec 2.4): fresh, upgrade, adopt, another cafe, --check, hub.toml."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from simtelemetry import licence
from simtelemetry.__main__ import main
from simtelemetry.api.app import create_app
from simtelemetry.config import AppConfig, load_config
from simtelemetry.core.pins import verify_pin
from simtelemetry.core.rigs import RigRegistry
from simtelemetry.core.settings import CafeSettings, SettingsStore, apply_settings
from simtelemetry.core.setup_code import SetupCode
from simtelemetry.provision import (EXIT_BAD_INPUT, EXIT_OK, EXIT_OTHER_CAFE, BakedProfile, load_baked, provision,
                                    set_features)

from licence_helpers import CAFE_ID, Signer, trust
from test_drivers import make_hub
from test_setup_api import PNG

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = (ROOT / "config" / "hub.example.toml").read_text(encoding="utf-8")


def profile(**over) -> dict:
    p = {"v": 1, "cafe_id": CAFE_ID, "name": "Apex Lounge", "tagline": "Race the city", "logo": "logo.png",
         "accent": "#ff2a6d", "wifi": {"ssid": "Apex Guests", "password": "racing123", "security": "WPA"},
         "hours": {"open_hour": 11, "close_hour": 1}, "rigs": 6, "rig_names": ["Senna", "", "Lauda"],
         "games": ["f1_25"], "features": {"events": False, "race_podium": False, "moments": True},
         "variant": "9t7"}
    p.update(over)
    return p


def bake(folder: Path, signer: Signer | None, prof: dict | None = None, logo: bytes | None = PNG,
         code: str | None = None, **lic) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "profile.json").write_text(json.dumps(prof or profile()), encoding="utf-8")
    if logo is not None:
        (folder / "logo.png").write_bytes(logo)
    if code is None and signer is not None:
        code = signer.code(**lic)
    if code is not None:
        (folder / "licence.txt").write_text(code + "\n", encoding="utf-8")
    return folder


@pytest.fixture
def pc(tmp_path):
    """A PC as the installer leaves it before provisioning: the starter hub.toml, an empty data folder."""
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config" / "hub.toml"
    config.parent.mkdir()
    config.write_text(EXAMPLE, encoding="utf-8")
    return data, config


@pytest.fixture
def signer(monkeypatch):
    return trust(monkeypatch)


def snapshot(data: Path, config: Path) -> dict[str, bytes]:
    """Every file in the data folder (but the logs) and hub.toml."""
    files = {f"data/{p.relative_to(data).as_posix()}": p.read_bytes() for p in data.rglob("*")
             if p.is_file() and "logs" not in p.relative_to(data).parts}
    files["config/hub.toml"] = config.read_bytes()
    return files


# --- fresh ------------------------------------------------------------------------------------

def test_fresh_install_fills_everything_in(tmp_path, pc, signer):
    data, config = pc
    src = bake(tmp_path / "baked", signer)
    r = provision(src, data, config)
    assert r.code == EXIT_OK and r.mode == "fresh"
    assert any("Licence installed: Licensed to Apex Lounge · 6 rigs · F1 25." == line for line in r.lines)
    # licence
    assert licence.read_file(data).payload.cafe_id == CAFE_ID
    # settings: the cafe's details, no PINs, setup still to finish
    s = SettingsStore(data).read()
    assert (s.name, s.tagline, s.accent, s.open_hour, s.close_hour) == ("Apex Lounge", "Race the city", "#FF2A6D",
                                                                         11, 1)
    assert (s.wifi_ssid, s.wifi_password, s.wifi_security) == ("Apex Guests", "racing123", "WPA")
    assert s.owner_pin == "" and s.staff_pin == "" and s.setup_done is False and not s.from_older_version()
    # logo: saved like an upload
    assert s.logo.startswith("logo-") and s.logo.endswith(".png")
    assert (data / "branding" / s.logo).read_bytes() == PNG
    # rig names wait for their rigs
    assert json.loads((data / "rigs.json").read_text(encoding="utf-8"))["pending_names"] == {"1": "Senna",
                                                                                              "3": "Lauda"}
    # hub.toml: the features, and everything else kept
    cfg = load_config(config)
    assert cfg.features.events is False and cfg.features.race_podium is False and cfg.features.moments is True
    text = config.read_text(encoding="utf-8")
    old, new = EXAMPLE.splitlines(), text.splitlines()
    assert len(old) == len(new)
    changed = [(a, b) for a, b in zip(old, new) if a != b]
    assert [b.split("#")[0].strip() for _, b in changed] == ["events = false", "race_podium = false"]
    assert all(a.split("#", 2)[2] == b.split("#", 1)[1] for a, b in changed)          # comments kept
    assert all(a.index("#", 1) == b.index("#") for a, b in changed)                   # in their column
    # stamp
    assert json.loads((data / "cafe.json").read_text(encoding="utf-8")) == {"cafe_id": CAFE_ID,
                                                                            "name": "Apex Lounge"}


def test_fresh_install_without_optional_details(tmp_path, pc, signer):
    data, config = pc
    prof = profile(logo=None, wifi=None, hours=None, rig_names=[], features={}, tagline="")
    r = provision(bake(tmp_path / "baked", signer, prof, logo=None), data, config)
    assert r.code == EXIT_OK
    s = SettingsStore(data).read()
    assert s.logo is None and s.wifi_ssid == "" and (s.open_hour, s.close_hour) == (10, 22)
    assert config.read_text(encoding="utf-8") == EXAMPLE            # nothing to change
    assert not (data / "rigs.json").exists()


def test_the_hub_starts_with_the_prefilled_details_and_setup_asks_for_pins(tmp_path, pc, signer):
    data, config = pc
    provision(bake(tmp_path / "baked", signer), data, config)
    code = SetupCode(data).new()
    hub = make_hub(data)
    apply_settings(hub.config, SettingsStore(data).load())
    hub.load_licence()
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    state = client.get("/api/setup").json()
    assert state["setup_done"] is False and state["needs_code"] is True
    assert state["has_settings"] is True and state["has_owner_pin"] is False and state["has_staff_pin"] is False
    assert (state["name"], state["tagline"], state["accent"], state["wifi_ssid"]) == (
        "Apex Lounge", "Race the city", "#FF2A6D", "Apex Guests")
    assert state["licence"] == "Licensed to Apex Lounge · 6 rigs · F1 25"
    assert client.get("/api/cafe/logo").content == PNG
    body = {"name": "Apex Lounge", "tagline": "Race the city", "accent": "#FF2A6D", "open_hour": 11,
            "close_hour": 1, "wifi_ssid": "Apex Guests", "wifi_security": "WPA"}
    headers = {"X-Setup-Code": code}
    r = client.post("/api/setup", json={**body, "owner_pin": "", "staff_pin": "1357"}, headers=headers)
    assert r.status_code == 400 and "Owner PIN" in r.json()["detail"]          # still has to choose one
    r = client.post("/api/setup", json={**body, "owner_pin": "2468", "staff_pin": "1357"}, headers=headers)
    assert r.status_code == 200
    s = SettingsStore(data).read()
    assert s.setup_done and verify_pin("2468", s.owner_pin) and s.wifi_password == "racing123"   # kept
    assert s.logo.startswith("logo-")


def test_a_provisioned_pc_without_pins_is_closed_until_setup_is_finished(tmp_path, pc, signer):
    """No PINs yet must never mean "no PIN needed": owner, staff and /setup stay shut without the setup code."""
    data, config = pc
    provision(bake(tmp_path / "baked", signer), data, config)
    code = SetupCode(data).new()
    hub = make_hub(data)
    apply_settings(hub.config, SettingsStore(data).load())
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    for headers in ({}, {"X-Owner-PIN": ""}, {"X-Staff-PIN": ""}):
        assert client.get("/api/owner/report", headers=headers).status_code == 403
        assert client.get("/api/staff/rigs", headers=headers).status_code == 403
    body = {"name": "Mine now", "owner_pin": "1111", "staff_pin": "2222"}
    assert client.post("/api/setup", json=body).status_code == 401
    assert client.post("/api/setup", json=body, headers={"X-Setup-Code": "WRONG-CODE"}).status_code == 401
    assert client.get("/api/setup").json()["authed"] is False
    assert SettingsStore(data).read().name == "Apex Lounge" and code


def test_a_hub_run_on_hub_toml_pins_is_adopted_not_filled_in(tmp_path, pc, signer):
    """No settings.json but PINs in hub.toml: pre-filled settings would replace them with none."""
    data, config = pc
    config.write_text(EXAMPLE.replace('pin = ""                               # owner PIN',
                                      'pin = "2468"                           # owner PIN'), encoding="utf-8")
    assert load_config(config).owner.pin == "2468"
    before = snapshot(data, config)
    r = provision(bake(tmp_path / "baked", signer), data, config)
    assert r.code == EXIT_OK and r.mode == "adopt"
    after = snapshot(data, config)
    assert {k for k in after if before.get(k) != after[k]} == {"data/licence.txt", "data/cafe.json"}


def test_rig_names_are_applied_as_rigs_register(tmp_path, pc, signer):
    data, config = pc
    provision(bake(tmp_path / "baked", signer, profile(rig_names=["Senna", None, "Lauda", "Rig 4"])), data, config)
    reg = RigRegistry(AppConfig(data_dir=data), data / "rigs.json")
    a = reg.see("10.0.0.21", 0.0, "2025", None)
    b = reg.see("10.0.0.22", 1.0, "2025", None)
    c = reg.see("10.0.0.23", 2.0, "2025", None)
    d = reg.see("10.0.0.24", 3.0, "2025", None)
    assert [(r.number, r.name) for r in (a, b, c, d)] == [(1, "Senna"), (2, "Rig 2"), (3, "Lauda"), (4, "Rig 4")]
    saved = json.loads((data / "rigs.json").read_text(encoding="utf-8"))
    assert "pending_names" not in saved                              # used up
    # a restart keeps them, and an owner's rename wins from then on
    reg2 = RigRegistry(AppConfig(data_dir=data), data / "rigs.json")
    assert reg2.get("10.0.0.21").name == "Senna"
    reg2.rename("10.0.0.21", "Hamilton")
    assert RigRegistry(AppConfig(data_dir=data), data / "rigs.json").get("10.0.0.21").name == "Hamilton"


def test_pending_names_go_to_rigs_already_known_unless_named(tmp_path):
    state = tmp_path / "rigs.json"
    state.write_text(json.dumps({"auto_names": {"10.0.0.1": "Rig 1", "10.0.0.2": "Rig 2"},
                                 "names": {"10.0.0.2": "Owner's"},
                                 "pending_names": {"1": "Senna", "2": "Lauda", "5": "Prost", "x": "bad"}}))
    reg = RigRegistry(AppConfig(data_dir=tmp_path), state)
    assert reg.get("10.0.0.1").name == "Senna" and reg.get("10.0.0.2").name == "Owner's"
    assert json.loads(state.read_text())["pending_names"] == {"5": "Prost"}
    assert reg.see("10.0.0.3", 0.0, "2025", None).name == "Rig 3"     # numbering unchanged
    assert reg.see("10.0.0.4", 0.0, "2025", None).name == "Rig 4"
    assert reg.see("10.0.0.5", 0.0, "2025", None).name == "Prost"


def test_pending_name_already_taken_is_dropped(tmp_path):
    state = tmp_path / "rigs.json"
    state.write_text(json.dumps({"auto_names": {"10.0.0.1": "Rig 1"}, "names": {"10.0.0.1": "Senna"},
                                 "pending_names": {"2": "senna"}}))
    reg = RigRegistry(AppConfig(data_dir=tmp_path), state)
    assert reg.see("10.0.0.2", 0.0, "2025", None).name == "Rig 2"


def test_indic_rig_names_keep_their_joiners(tmp_path, pc, signer):
    data, config = pc
    marathi = "र\u094d\u200dया"                                     # the eyelash "rya" needs the ZWJ
    provision(bake(tmp_path / "baked", signer, profile(rig_names=[marathi])), data, config)
    reg = RigRegistry(AppConfig(data_dir=data), data / "rigs.json")
    assert reg.see("10.0.0.21", 0.0, "2025", None).name == marathi


def test_an_interrupted_fresh_install_is_simply_run_again(tmp_path, pc, signer):
    data, config = pc
    src = bake(tmp_path / "baked", signer)
    SettingsStore(data).save(BakedProfile.model_validate(profile(name="Half done")).settings())  # no stamp yet
    r = provision(src, data, config)
    assert r.mode == "fresh" and SettingsStore(data).read().name == "Apex Lounge"


# --- upgrade: never touches the cafe's own things -----------------------------------------------

def _set_up_by_owner(data: Path, config: Path) -> None:
    """What the cafe changed after the fresh install."""
    s = SettingsStore(data).read()
    (data / "branding" / s.logo).unlink()
    (data / "branding" / "logo-own.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 own")
    SettingsStore(data).save(s.model_copy(update={
        "name": "Apex Racing Club", "tagline": "Ours now", "accent": "#00C2FF", "logo": "logo-own.webp",
        "owner_pin": "2468", "staff_pin": "1357", "setup_done": True, "open_hour": 9, "close_hour": 23,
        "wifi_ssid": "Club Wifi", "wifi_password": "different1", "backup_dir": "E:\\Backups"}))
    reg = RigRegistry(AppConfig(data_dir=data), data / "rigs.json")
    reg.see("10.0.0.21", 0.0, "2025", None)
    reg.rename("10.0.0.21", "Owner's rig")
    config.write_text(config.read_text(encoding="utf-8").replace("events = false", "events = true")
                      + "\n# the owner's note\n", encoding="utf-8")


def test_upgrade_installs_only_a_newer_licence_and_touches_nothing_else(tmp_path, pc, signer):
    data, config = pc
    provision(bake(tmp_path / "v1", signer, seq=1), data, config)
    _set_up_by_owner(data, config)
    before = snapshot(data, config)
    # a newer installer whose profile differs in every field
    other = profile(name="Renamed", tagline="New", accent="#FFFFFF", wifi=None, hours={"open_hour": 8,
                    "close_hour": 20}, rig_names=["X", "Y"], features={"events": False, "moments": False},
                    logo="logo.png")
    r = provision(bake(tmp_path / "v2", signer, other, logo=PNG[:-1] + b"!", seq=2, licence_id="lic-2", rigs=8),
                  data, config)
    assert r.code == EXIT_OK and r.mode == "upgrade"
    assert "Licence installed: Licensed to Apex Lounge · 8 rigs · F1 25." in r.lines
    after = snapshot(data, config)
    changed = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    assert changed == {"data/licence.txt"}
    assert licence.read_file(data).payload.seq == 2


def test_upgrade_with_an_older_or_the_same_licence_keeps_the_installed_one(tmp_path, pc, signer):
    data, config = pc
    provision(bake(tmp_path / "v3", signer, seq=3, licence_id="lic-3"), data, config)
    installed = (data / "licence.txt").read_bytes()
    for name, lic in (("old", {"seq": 2, "licence_id": "lic-2"}), ("same", {"seq": 3, "licence_id": "lic-3"})):
        r = provision(bake(tmp_path / name, signer, **lic), data, config)
        assert r.code == EXIT_OK and r.mode == "upgrade"
        assert "The licence on this PC is already up to date, so it was kept." in r.lines
        assert (data / "licence.txt").read_bytes() == installed


# --- adopt: an existing cafe without a stamp ---------------------------------------------------

def test_adopt_a_set_up_cafe_without_a_stamp(tmp_path, pc, signer):
    data, config = pc
    SettingsStore(data).save(CafeSettings(name="Old Cafe", owner_pin="2468", staff_pin="1357", setup_done=True,
                                          settings_version=1))
    (data / "rigs.json").write_text(json.dumps({"auto_names": {"10.0.0.1": "Rig 1"}}), encoding="utf-8")
    before = snapshot(data, config)
    r = provision(bake(tmp_path / "baked", signer), data, config)
    assert r.code == EXIT_OK and r.mode == "adopt"
    after = snapshot(data, config)
    assert {k for k in after if before.get(k) != after[k]} == {"data/licence.txt", "data/cafe.json"}
    assert json.loads((data / "cafe.json").read_text(encoding="utf-8"))["cafe_id"] == CAFE_ID


@pytest.mark.parametrize("settings_text", [
    # after "Reset owner PIN": setup not done, but the cafe's PINs are there
    lambda: json.dumps(CafeSettings(name="Old Cafe", owner_pin="2468", staff_pin="1357").model_dump()),
    lambda: "{damaged",
])
def test_adopt_never_overwrites_settings_it_cant_be_sure_of(tmp_path, pc, signer, settings_text):
    data, config = pc
    (data / "settings.json").write_text(settings_text(), encoding="utf-8")
    before = (data / "settings.json").read_bytes()
    r = provision(bake(tmp_path / "baked", signer), data, config)
    assert r.mode == "adopt" and (data / "settings.json").read_bytes() == before
    assert config.read_text(encoding="utf-8") == EXAMPLE


# --- another cafe ----------------------------------------------------------------------------

def _owned_by_other(tmp_path, data, config, signer):
    other = profile(cafe_id="cafe-other", name="Turbo Den")
    provision(bake(tmp_path / "other", signer, other, cafe_id="cafe-other", cafe_name="Turbo Den"), data, config)
    s = SettingsStore(data).read()
    SettingsStore(data).save(s.model_copy(update={"owner_pin": "2468", "staff_pin": "1357", "setup_done": True}))


def test_another_cafes_installer_is_refused(tmp_path, pc, signer):
    data, config = pc
    _owned_by_other(tmp_path, data, config, signer)
    before = snapshot(data, config)
    r = provision(bake(tmp_path / "baked", signer), data, config)
    assert r.code == EXIT_OTHER_CAFE
    assert r.lines == ["This installer is for Apex Lounge. This PC belongs to Turbo Den."]
    assert snapshot(data, config) == before


def test_without_a_stamp_the_installed_licence_says_whose_pc_it_is(tmp_path, pc, signer):
    data, config = pc
    _owned_by_other(tmp_path, data, config, signer)
    (data / "cafe.json").unlink()
    r = provision(bake(tmp_path / "baked", signer), data, config, check=True)
    assert r.code == EXIT_OTHER_CAFE and r.lines == ["This installer is for Apex Lounge. This PC belongs to Turbo Den."]


def test_force_restamps_and_licenses_but_keeps_the_settings(tmp_path, pc, signer):
    data, config = pc
    _owned_by_other(tmp_path, data, config, signer)
    settings_before = (data / "settings.json").read_bytes()
    rigs_before = (data / "rigs.json").read_bytes()
    toml_before = config.read_bytes()
    r = provision(bake(tmp_path / "baked", signer), data, config, force=True)
    assert r.code == EXIT_OK and r.mode == "adopt"
    assert r.lines[0] == "This PC belonged to Turbo Den. It now belongs to Apex Lounge."
    assert licence.read_file(data).payload.cafe_id == CAFE_ID
    assert json.loads((data / "cafe.json").read_text(encoding="utf-8"))["cafe_id"] == CAFE_ID
    assert (data / "settings.json").read_bytes() == settings_before
    assert (data / "rigs.json").read_bytes() == rigs_before and config.read_bytes() == toml_before


# --- --check -------------------------------------------------------------------------------

def test_check_writes_nothing(tmp_path, pc, signer):
    data, config = pc
    src = bake(tmp_path / "baked", signer)
    before = snapshot(data, config)
    r = provision(src, data, config, check=True)
    assert r.code == EXIT_OK and r.mode is None
    assert snapshot(data, config) == before and list(data.iterdir()) == []
    provision(src, data, config)
    before = snapshot(data, config)
    assert provision(src, data, config, check=True).code == EXIT_OK
    assert snapshot(data, config) == before


def test_check_reports_bad_files(tmp_path, pc, signer):
    data, config = pc
    assert provision(tmp_path / "nothing", data, config, check=True).code == EXIT_BAD_INPUT


# --- bad input -------------------------------------------------------------------------------

@pytest.mark.parametrize("change, words", [
    (lambda d: (d / "profile.json").unlink(), "profile is missing"),
    (lambda d: (d / "profile.json").write_text("{nope", encoding="utf-8"), "damaged"),
    (lambda d: (d / "profile.json").write_text("[1]", encoding="utf-8"), "damaged"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(v=2)), encoding="utf-8"), "different version"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(name="")), encoding="utf-8"), "cafe name"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(rigs=25)), encoding="utf-8"), "number of rigs"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(rigs="6")), encoding="utf-8"), "number of rigs"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(accent="red")), encoding="utf-8"), "colour"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(
        wifi={"ssid": "A", "password": "short", "security": "WPA"})), encoding="utf-8"), "Wi-Fi password"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(
        hours={"open_hour": 20, "close_hour": 10})), encoding="utf-8"), "closing time"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(rig_names=["A"] * 7)), encoding="utf-8"),
     "more rig names than rigs"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(rig_names=["A", "a"])), encoding="utf-8"),
     "two rigs"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(rig_names=["Rig 3"])), encoding="utf-8"),
     "number"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(rig_names=["X" * 17])), encoding="utf-8"),
     "16 characters"),
    (lambda d: (d / "profile.json").write_text(json.dumps(profile(logo="../x.png")), encoding="utf-8"), "logo"),
    (lambda d: (d / "logo.png").unlink(), "logo file is missing"),
    (lambda d: (d / "logo.png").write_bytes(b"GIF89a..."), "PNG, JPEG or WebP"),
    (lambda d: (d / "logo.png").write_bytes(PNG + b"\0" * (1024 * 1024)), "under 1 MB"),
    (lambda d: (d / "licence.txt").unlink(), "licence file is missing"),
])
def test_bad_input_is_refused_plainly_and_writes_nothing(tmp_path, pc, signer, change, words):
    data, config = pc
    src = bake(tmp_path / "baked", signer)
    change(src)
    r = provision(src, data, config)
    assert r.code == EXIT_BAD_INPUT and len(r.lines) == 1
    assert r.lines[0].startswith("This installer's cafe details can't be used (")
    assert words in r.lines[0] and r.lines[0].endswith("Ask your supplier for a new installer.")
    assert "Traceback" not in r.lines[0] and "should" not in r.lines[0]
    assert list(data.iterdir()) == [] and config.read_text(encoding="utf-8") == EXAMPLE


def test_a_licence_for_another_cafe_in_the_package_is_bad_input(tmp_path, pc, signer):
    data, config = pc
    r = provision(bake(tmp_path / "baked", signer, cafe_id="cafe-other"), data, config)
    assert r.code == EXIT_BAD_INPUT and "different cafe" in r.lines[0]


def test_a_licence_that_doesnt_verify_still_provisions_the_rest(tmp_path, pc, signer):
    data, config = pc
    r = provision(bake(tmp_path / "baked", None, code=Signer().code()), data, config)   # another key
    assert r.code == EXIT_OK and r.mode == "fresh"
    assert any("couldn't be checked, so it wasn't installed" in line for line in r.lines)
    assert not (data / "licence.txt").exists()
    assert SettingsStore(data).read().name == "Apex Lounge" and (data / "cafe.json").exists()


def test_unknown_keys_and_features_are_ignored(tmp_path, pc, signer):
    data, config = pc
    prof = profile(future_field=1, features={"events": False, "time_travel": True})
    r = provision(bake(tmp_path / "baked", signer, prof), data, config)
    assert r.code == EXIT_OK and load_config(config).features.events is False


def test_load_baked_accepts_jpeg_and_webp(tmp_path, signer):
    for image, ext in ((b"\xff\xd8\xff\xe0rest", ".jpg"), (b"RIFF\x10\x00\x00\x00WEBPVP8 ", ".webp")):
        src = bake(tmp_path / ext, signer, logo=image)
        assert load_baked(src).logo == (image, ext)


# --- hub.toml ----------------------------------------------------------------------------------

def test_set_features_keeps_comments_and_other_settings():
    text = ("data_dir = \"D:/cafe\"   # mine\n\n[features]   # flags\n"
            "moments = false            # owner turned it off\n# events = true   # corporate\n\n"
            "[owner]\nopen_hour = 9\n")
    out = set_features(text, {"moments": True, "events": False, "battles": False, "sharing": True})
    assert out == ("data_dir = \"D:/cafe\"   # mine\n\n[features]   # flags\n"
                   "moments = true             # owner turned it off\nevents = false    # corporate\n"
                   "battles = false\n\n[owner]\nopen_hour = 9\n")
    parsed = tomllib.loads(out)
    assert parsed["owner"] == {"open_hour": 9} and parsed["data_dir"] == "D:/cafe"


def test_set_features_adds_a_section_and_keeps_windows_line_ends():
    out = set_features("[owner]\r\nopen_hour = 9\r\n", {"events": False})
    assert out == "[owner]\r\nopen_hour = 9\r\n\r\n[features]\r\nevents = false\r\n"


def test_a_hub_toml_with_a_mistake_is_left_alone(tmp_path, pc, signer):
    data, config = pc
    config.write_text("[features\nevents = true\n", encoding="utf-8")
    before = config.read_bytes()
    r = provision(bake(tmp_path / "baked", signer), data, config)
    assert r.code == EXIT_OK and config.read_bytes() == before
    assert any("left as they were" in line for line in r.lines)
    assert SettingsStore(data).read().name == "Apex Lounge"


def test_missing_hub_toml_is_created_with_only_the_features(tmp_path, signer):
    data, config = tmp_path / "data", tmp_path / "config" / "hub.toml"
    assert provision(bake(tmp_path / "baked", signer), data, config).code == EXIT_OK
    assert tomllib.loads(config.read_text(encoding="utf-8")) == {"features": {"events": False,
                                                                            "race_podium": False}}


# --- the command line ----------------------------------------------------------------------

def test_cli_provision_and_check(tmp_path, pc, signer, capsys):
    data, config = pc
    src = bake(tmp_path / "baked", signer)
    args = ["--config", str(config), "--data-dir", str(data)]
    assert main(["provision", str(src), "--check", *args]) == 0
    assert list(data.iterdir()) == []                                   # not even a log
    assert main(["provision", str(src), *args]) == 0
    out = capsys.readouterr().out
    assert "Set up for Apex Lounge." in out and "Traceback" not in out
    other = bake(tmp_path / "other", signer, profile(cafe_id="cafe-other", name="Turbo Den"), cafe_id="cafe-other")
    assert main(["provision", str(other), "--check", *args]) == 3
    assert "This installer is for Turbo Den. This PC belongs to Apex Lounge." in capsys.readouterr().out
    assert main(["provision", str(other), *args]) == 3
    assert main(["provision", str(other), "--force-other-cafe", *args]) == 0
    assert json.loads((data / "cafe.json").read_text(encoding="utf-8"))["cafe_id"] == "cafe-other"


def test_cli_bad_folder_exit_2_without_a_stack_trace(tmp_path, pc, capsys):
    data, config = pc
    code = main(["provision", str(tmp_path / "missing"), "--config", str(config), "--data-dir", str(data)])
    captured = capsys.readouterr()
    assert code == 2 and "This installer's cafe details can't be used" in captured.out
    assert "Traceback" not in captured.out + captured.err


def test_cli_unexpected_error_is_plain(tmp_path, pc, signer, capsys, monkeypatch):
    import simtelemetry.provision as prov
    data, config = pc
    monkeypatch.setattr(prov, "_provision", lambda *a: 1 / 0)
    code = main(["provision", str(bake(tmp_path / "baked", signer)), "--config", str(config),
                 "--data-dir", str(data)])
    out = capsys.readouterr().out
    assert code == 1 and "couldn't install the cafe's details" in out and "Traceback" not in out


def test_cli_disk_error_is_plain(tmp_path, pc, signer, capsys, monkeypatch):
    import simtelemetry.provision as prov
    data, config = pc

    def boom(*a, **k):
        raise PermissionError("denied")
    monkeypatch.setattr(prov, "write_stamp", boom)
    code = main(["provision", str(bake(tmp_path / "baked", signer)), "--config", str(config),
                 "--data-dir", str(data)])
    assert code == 1 and "couldn't save the cafe's details" in capsys.readouterr().out


def test_cli_uses_the_installed_data_folder_by_default(tmp_path, signer, monkeypatch, capsys):
    from simtelemetry import brand
    monkeypatch.setenv(brand.HOME_ENV, str(tmp_path / "home"))
    assert main(["provision", str(bake(tmp_path / "baked", signer))]) == 0
    assert (tmp_path / "home" / "data" / "cafe.json").exists()
    assert (tmp_path / "home" / "config" / "hub.toml").exists()


# --- the factory's preview: `run --demo` on a provisioned folder ------------------------------------------

def test_demo_shows_a_provisioned_cafe(tmp_path, pc, signer, monkeypatch):
    """C11: the preview provisions a demo folder; `run --demo` shows that cafe's details and uses its licence,
    keeps the demo PINs (a provisioned folder has none) and never takes a backup folder from the file."""
    import argparse
    import simtelemetry.__main__ as cli
    from simtelemetry.tools import seed_demo
    data, config = pc
    (data / seed_demo.MARKER).write_text("demo", encoding="utf-8")
    assert provision(bake(tmp_path / "baked", signer, variant="unbranded", rigs=2), data, config).code == EXIT_OK
    s = SettingsStore(data).load()
    SettingsStore(data).save(s.model_copy(update={"backup_dir": str(tmp_path / "real-backups")}))
    monkeypatch.setattr(seed_demo, "seed", lambda d, *a, **k: {"sessions": 0, "laps": 0})
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path))

    cfg = load_config(config)
    cfg.data_dir = data
    cli.prepare_demo(argparse.Namespace(data_dir=data), cfg)
    assert cfg.cafe.name == "Apex Lounge" and cfg.cafe.tagline == "Race the city"
    assert cfg.cafe.logo and (data / "branding" / cfg.cafe.logo).is_file()
    assert cfg.cafe.branding["--brand-accent"].lower() == "#ff2a6d"
    assert cfg.cafe.wifi_ssid == "Apex Guests"
    assert cfg.owner.pin == "0000" and cfg.staff.pin == "0000"
    assert cfg.backups_dir == tmp_path / "backups-demo"            # never the folder in settings.json
    assert cfg.features.events is False and cfg.features.moments is True    # hub.toml written by provision

    hub = make_hub(tmp_path / "hub")
    hub.config.data_dir = data
    ent = hub.load_licence(warn_missing=False, fallback=cli.demo_fallback())
    assert ent.source == "licence" and ent.rigs == 2 and ent.variant == "unbranded" and not ent.vendor_mark


def test_demo_without_settings_is_unchanged(tmp_path, monkeypatch):
    import argparse
    import simtelemetry.__main__ as cli
    from simtelemetry.tools import seed_demo
    monkeypatch.setattr(seed_demo, "seed", lambda d, *a, **k: {"sessions": 0, "laps": 0})
    cfg = AppConfig()
    cfg.data_dir = tmp_path / "demo"
    cfg.owner.pin = "2468"
    cli.prepare_demo(argparse.Namespace(data_dir=cfg.data_dir), cfg)
    assert cfg.cafe.name == AppConfig().cafe.name
    assert cfg.owner.pin == "2468" and cfg.staff.pin == "2468"


def test_demo_never_logs_a_saved_pin_hash(tmp_path, monkeypatch, caplog):
    """C11 review: a demo folder whose /setup was saved has hashed PINs; the start-up line doesn't print the hash."""
    import argparse
    import logging
    import simtelemetry.__main__ as cli
    from simtelemetry.tools import seed_demo
    monkeypatch.setattr(seed_demo, "seed", lambda d, *a, **k: {"sessions": 0, "laps": 0})
    data = tmp_path / "demo"
    data.mkdir()
    store = SettingsStore(data)
    store.save(CafeSettings(name="Grid Cafe", owner_pin="2468", staff_pin="1357", setup_done=True))
    hashed = store.load().owner_pin
    assert hashed.startswith("scrypt$")
    cfg = AppConfig()
    cfg.data_dir = data
    with caplog.at_level(logging.INFO):
        cli.prepare_demo(argparse.Namespace(data_dir=data), cfg)
    assert cfg.cafe.name == "Grid Cafe" and cfg.owner.pin == hashed and verify_pin("2468", cfg.owner.pin)
    assert hashed not in caplog.text and "as saved on the setup page" in caplog.text
