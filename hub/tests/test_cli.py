"""End-to-end CLI tests over real localhost sockets."""

import socket
import threading
import time

import pytest

from simtelemetry.__main__ import main
from simtelemetry.tools.recorder import read_recording

from test_hub import lap_data, motion, participants, session, telemetry


def free_port(kind=socket.SOCK_DGRAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def send_later(port: int, packets: list[bytes], delay: float = 0.4, repeat: int = 15, gap: float = 0.1):
    def run():
        time.sleep(delay)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for _ in range(repeat):
                for p in packets:
                    s.sendto(p, ("127.0.0.1", port))
                time.sleep(gap)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


RIG_PACKETS = [participants(2025, b"Akshat"), session(2025, 7), lap_data(2025, 2, 61234),
               telemetry(2025, 250), motion(2025)]


def test_listen_prints_status_lines_and_records(tmp_path, capsys):
    port = free_port()
    sender = send_later(port, RIG_PACKETS)
    code = main(["listen", "--port", str(port), "--data-dir", str(tmp_path), "--duration", "2.5"])
    sender.join()
    assert code == 0
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if "127.0.0.1" in l]
    assert lines, out
    last = lines[-1]
    for part in ("Rig 1", "fmt=2025", "Silverstone", "lap 2", "1:01.234", "250 km/h", "driving"):
        assert part in last, last

    recordings = list((tmp_path / "recordings").glob("*.f1rec"))
    assert len(recordings) == 1
    records = list(read_recording(recordings[0]))
    assert len(records) == len(RIG_PACKETS) * 15  # every datagram, flushed on shutdown
    assert {ip for _, ip, _ in records} == {"127.0.0.1"}


def test_replay_reproduces_rig_state(tmp_path, capsys):
    port = free_port()
    sender = send_later(port, RIG_PACKETS, repeat=3)
    assert main(["record", "--port", str(port), "--data-dir", str(tmp_path), "--duration", "1.5"]) == 0
    sender.join()
    recording = next((tmp_path / "recordings").glob("*.f1rec"))
    capsys.readouterr()

    replay_dir = tmp_path / "replay"
    code = main(["replay", str(recording), "--speed", "0", "--no-api", "--data-dir", str(replay_dir)])
    assert code == 0
    log_text = (replay_dir / "logs" / "hub.log").read_text(encoding="utf-8")
    assert "Replay finished: 15 packets" in log_text
    assert "New rig detected: 127.0.0.1 (this PC) -> Rig 1 (format 2025)" in log_text
    assert "driver: Akshat" in log_text
    assert not list(replay_dir.glob("recordings/*.f1rec"))  # replay never records


def test_udp_port_in_use_gives_clear_message(tmp_path, capsys):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("0.0.0.0", 0))
    port = blocker.getsockname()[1]
    try:
        code = main(["listen", "--port", str(port), "--data-dir", str(tmp_path), "--duration", "1"])
    finally:
        blocker.close()
    assert code == 2
    err = capsys.readouterr().err
    assert f"UDP port {port} is already in use" in err
    assert f"--port {port + 1}" in err
    assert "Traceback" not in err
    assert not list(tmp_path.glob("recordings/*.f1rec"))  # nothing recorded on a failed start


def test_http_port_in_use_gives_clear_message(tmp_path, capsys):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("0.0.0.0", 0))
    blocker.listen()
    http_port = blocker.getsockname()[1]
    try:
        code = main(["run", "--port", str(free_port()), "--http-port", str(http_port),
                     "--data-dir", str(tmp_path), "--duration", "1"])
    finally:
        blocker.close()
    assert code == 2
    assert f"HTTP port {http_port} is already in use" in capsys.readouterr().err


def test_run_serves_health_api(tmp_path):
    import json
    import urllib.request

    udp_port, http_port = free_port(), free_port(socket.SOCK_STREAM)
    sender = send_later(udp_port, RIG_PACKETS, repeat=10)
    result = {}

    def poll():
        time.sleep(1.2)
        with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/api/health", timeout=5) as r:
            result.update(json.load(r))
    poller = threading.Thread(target=poll)
    poller.start()
    code = main(["run", "--port", str(udp_port), "--http-port", str(http_port),
                 "--data-dir", str(tmp_path), "--duration", "2.5"])
    poller.join()
    sender.join()
    assert code == 0
    assert result["udp_port"] == udp_port
    rig = result["rigs"][0]
    assert rig["ip"] == "127.0.0.1" and rig["driver_name"] == "Akshat" and rig["data_format"] == "2025"
    assert result["recording"] is None
    assert not list(tmp_path.glob("recordings/*.f1rec"))  # run: recorder off by default


@pytest.mark.parametrize("argv,config_kwargs,expected", [
    (["run"], {}, False),                                  # production default
    (["listen"], {}, True),                                # dev default
    (["run", "--record"], {}, True),
    (["listen", "--no-record"], {}, False),
    (["run"], {"enabled_in_run": True}, True),
    (["listen"], {"enabled_in_listen": False}, False),
    (["run", "--no-record"], {"enabled_in_run": True}, False),  # flag beats config
    (["record"], {"enabled_in_run": False, "enabled_in_listen": False}, True),
    (["replay", "x.f1rec"], {"enabled_in_run": True, "enabled_in_listen": True}, False),
])
def test_should_record(argv, config_kwargs, expected):
    from simtelemetry.__main__ import build_parser, should_record
    from simtelemetry.config import AppConfig, RecorderConfig
    config = AppConfig(recorder=RecorderConfig(**config_kwargs))
    assert should_record(build_parser().parse_args(argv), config) is expected


def test_record_flags_are_mutually_exclusive():
    from simtelemetry.__main__ import build_parser
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--record", "--no-record"])


def test_hub_keeps_running_when_recording_stops_for_low_disk(tmp_path, capsys):
    """Floor set above any real free space: recording stops at start, listening carries on."""
    config = tmp_path / "hub.toml"
    config.write_text("[recorder]\nwarn_free_gb = 1000000\nstop_free_gb = 1000000\n", encoding="utf-8")
    port = free_port()
    sender = send_later(port, RIG_PACKETS, repeat=10)
    code = main(["listen", "--config", str(config), "--port", str(port), "--data-dir", str(tmp_path),
                 "--duration", "2"])
    sender.join()
    assert code == 0
    captured = capsys.readouterr()
    assert "recording stopped: low disk" in captured.err
    assert any("127.0.0.1" in l and "driving" in l for l in captured.out.splitlines())
    assert not list(tmp_path.glob("recordings/*.f1rec"))


def test_port_shadow_warning(monkeypatch):
    """Another program bound to 127.0.0.1 on the telemetry port is reported (Windows behaviour)."""
    import socket
    import sys
    from simtelemetry.net import udp

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(udp, "_udp_owner", lambda address, port: "simpro3.exe")
    other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    other.bind(("127.0.0.1", 0))
    port = other.getsockname()[1]
    try:
        (message,) = udp.port_shadows(port)
    finally:
        other.close()
    assert message.startswith(f"Another program (simpro3.exe) is listening on 127.0.0.1:{port}")
    assert "UDP IP Address to this PC's network address" in message
    assert udp.port_shadows(port) == []


def test_version_flag(capsys):
    import simtelemetry
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert simtelemetry.__version__ in capsys.readouterr().out


def test_double_click_means_run(monkeypatch, tmp_path):
    from simtelemetry import brand
    monkeypatch.setenv(brand.HOME_ENV, str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("simtelemetry.__main__.run_command", lambda args, config, problems=(): args.command)
    assert main([]) == "run"
