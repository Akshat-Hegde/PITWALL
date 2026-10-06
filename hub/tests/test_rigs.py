import logging

from simtelemetry.config import AppConfig, RigConfig
from simtelemetry.core.rigs import RigRegistry


def test_auto_names_in_order_of_first_packet(tmp_path):
    reg = RigRegistry(AppConfig(), tmp_path / "rigs.json")
    a = reg.see("192.168.1.20", 0.0, "2025", "aa")
    b = reg.see("192.168.1.10", 1.0, "2025", "bb")
    assert (a.name, b.name) == ("Rig 1", "Rig 2")
    assert reg.see("192.168.1.20", 2.0, "2025", "aa") is a


def test_config_name_overrides_and_is_not_reused(tmp_path):
    cfg = AppConfig(rigs=[RigConfig(ip="10.0.0.5", name="Rig 1", colour="#ff0000")])
    reg = RigRegistry(cfg, tmp_path / "rigs.json")
    configured = reg.get("10.0.0.5")
    assert configured.name == "Rig 1" and configured.colour == "#ff0000"
    assert configured.first_seen is None  # listed before it ever sends
    new = reg.see("10.0.0.9", 0.0, "2026", None)
    assert new.name != "Rig 1"


def test_auto_names_persist_across_restarts(tmp_path):
    state = tmp_path / "rigs.json"
    reg = RigRegistry(AppConfig(), state)
    reg.see("10.0.0.2", 0.0, "2025", None)
    reg.see("10.0.0.3", 0.0, "2025", None)
    reg2 = RigRegistry(AppConfig(), state)
    reg2.see("10.0.0.3", 0.0, "2025", None)  # arrives first this time
    assert reg2.get("10.0.0.2").name == "Rig 1"
    assert reg2.get("10.0.0.3").name == "Rig 2"


def test_corrupt_state_file_ignored(tmp_path):
    state = tmp_path / "rigs.json"
    state.write_text("{not json")
    reg = RigRegistry(AppConfig(), state)
    assert reg.see("10.0.0.2", 0.0, None, None).name == "Rig 1"


def test_tracks_format_session_and_driver(tmp_path, caplog):
    reg = RigRegistry(AppConfig(), tmp_path / "rigs.json")
    with caplog.at_level(logging.INFO):
        rig = reg.see("127.0.0.1", 0.0, "2025", "s1")
        reg.see("127.0.0.1", 1.0, "2026", "s2")
        reg.set_driver_name("127.0.0.1", "Akshat")
    assert (rig.data_format, rig.session_id, rig.driver_name) == ("2026", "s2", "Akshat")
    text = caplog.text
    assert "New rig detected: 127.0.0.1 (this PC) -> Rig 1" in text
    assert "changed packet format 2025 -> 2026" in text
