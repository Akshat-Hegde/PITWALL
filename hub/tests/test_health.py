import pytest

from simtelemetry.config import HealthConfig
from simtelemetry.core.health import HealthMonitor, RigState

IP = "192.168.1.10"


def test_rates_per_label():
    h = HealthMonitor(HealthConfig())
    h.tick(0.0)
    for i in range(60):
        h.on_packet(IP, "Motion", i / 30, driving=True)
    for i in range(4):
        h.on_packet(IP, "Session", i / 2, driving=False)
    h.tick(2.0)
    rig = h.get(IP)
    assert rig.rates["Motion"] == pytest.approx(30.0)
    assert rig.rates["Session"] == pytest.approx(2.0)
    assert rig.total_rate == pytest.approx(32.0)
    h.tick(3.0)  # nothing new in the last second
    assert h.get(IP).rates["Motion"] == 0.0


def test_drops_by_reason():
    h = HealthMonitor(HealthConfig())
    h.on_drop(IP, "size_mismatch", 0.0)
    h.on_drop(IP, "size_mismatch", 0.1)
    h.on_drop(IP, "unsupported_format", 0.2)
    assert dict(h.get(IP).drops) == {"size_mismatch": 2, "unsupported_format": 1}


def test_states():
    h = HealthMonitor(HealthConfig(no_motion_after_s=2.0, no_data_after_s=5.0))
    assert h.state(IP, 0.0) is RigState.NO_DATA
    h.on_packet(IP, "Motion", 10.0, driving=True)
    assert h.state(IP, 11.9) is RigState.DRIVING
    h.on_packet(IP, "Session", 12.5, driving=False)  # menu: packets but no Motion
    assert h.state(IP, 12.5) is RigState.IN_MENU
    assert h.state(IP, 17.4) is RigState.IN_MENU
    assert h.state(IP, 17.6) is RigState.NO_DATA


def test_only_dropped_packets_still_counts_as_connected():
    # A rig on an unsupported format is connected (and shown with drops), not "no data".
    h = HealthMonitor(HealthConfig())
    h.on_drop(IP, "unsupported_format", 1.0)
    assert h.state(IP, 1.5) is RigState.IN_MENU
