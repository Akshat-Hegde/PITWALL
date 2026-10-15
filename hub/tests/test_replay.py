"""Replay source selection (--from-ip / --as-ip) and replay alongside live rigs (--live)."""

import asyncio
import json
import socket

import pytest

from simtelemetry.__main__ import main
from simtelemetry.tools.recorder import Recorder
from simtelemetry.tools.replay import ReplayError, SourceSelection, replay, select_source

from test_cli import free_port, send_later
from test_hub import lap_data, motion, participants, session, telemetry

RIG_A, RIG_B = "192.168.1.21", "192.168.1.22"


def rig_packets(name: bytes):
    return [participants(2025, name), session(2025, 7), lap_data(2025, 2, 61234), telemetry(2025, 250),
            motion(2025)]


def make_recording(directory, sources: dict[str, bytes], repeat: int = 3):
    rec = Recorder(directory)
    rec.start()
    t = 1000.0
    for _ in range(repeat):
        for ip, name in sources.items():
            for p in rig_packets(name):
                rec.write(t, ip, p)
                t += 0.001
    rec.close()
    return rec.current_path


def collect(path, speed=0, selection=SourceSelection()):
    seen = []
    asyncio.run(replay([path], lambda data, ip, ts: seen.append(ip), speed, selection))
    return seen


# --- select_source / replay() ---------------------------------------------------------

def test_no_options_keeps_original_ips(tmp_path):
    path = make_recording(tmp_path, {RIG_A: b"A", RIG_B: b"B"})
    assert set(collect(path, selection=select_source([path], None, None))) == {RIG_A, RIG_B}


def test_as_ip_remaps_single_source(tmp_path):
    path = make_recording(tmp_path, {RIG_A: b"A"})
    seen = collect(path, selection=select_source([path], None, "10.9.9.9"))
    assert seen and set(seen) == {"10.9.9.9"}


def test_as_ip_with_several_sources_needs_from_ip(tmp_path):
    path = make_recording(tmp_path, {RIG_A: b"A", RIG_B: b"B"})
    with pytest.raises(ReplayError) as exc:
        select_source([path], None, "10.9.9.9")
    message = str(exc.value)
    assert "contains 2 source IPs" in message
    assert f"{RIG_A} (15 packets)" in message and f"{RIG_B} (15 packets)" in message
    assert "--from-ip" in message


def test_from_ip_selects_and_remaps(tmp_path):
    path = make_recording(tmp_path, {RIG_A: b"A", RIG_B: b"B"})
    seen = collect(path, selection=select_source([path], RIG_B, "10.9.9.9"))
    assert seen == ["10.9.9.9"] * 15  # only RIG_B's 15 packets


def test_from_ip_alone_filters_without_remapping(tmp_path):
    path = make_recording(tmp_path, {RIG_A: b"A", RIG_B: b"B"})
    assert set(collect(path, selection=select_source([path], RIG_A, None))) == {RIG_A}


def test_from_ip_not_in_recording(tmp_path):
    path = make_recording(tmp_path, {RIG_A: b"A"})
    with pytest.raises(ReplayError, match=rf"no packets from 10\.0\.0\.1\. Source IPs in the recording: {RIG_A}"):
        select_source([path], "10.0.0.1", "10.9.9.9")


@pytest.mark.parametrize("option,args", [("--as-ip", (None, "192.168.1.300")), ("--from-ip", ("rig2", None))])
def test_invalid_ip_rejected(tmp_path, option, args):
    path = make_recording(tmp_path, {RIG_A: b"A"})
    with pytest.raises(ReplayError, match=f"{option} '.*' is not a valid IP address"):
        select_source([path], *args)


def test_unreadable_recording(tmp_path):
    bad = tmp_path / "bad.f1rec"
    bad.write_bytes(b"nope")
    with pytest.raises(ReplayError, match="Cannot read recording"):
        select_source([bad], None, "10.9.9.9")


# --- CLI ---------------------------------------------------------------------------------

def test_cli_as_ip_ambiguous_exits_cleanly(tmp_path, capsys):
    path = make_recording(tmp_path / "rec", {RIG_A: b"A", RIG_B: b"B"})
    code = main(["replay", str(path), "--as-ip", "10.9.9.9", "--speed", "0", "--no-api",
                 "--data-dir", str(tmp_path / "data")])
    assert code == 2
    err = capsys.readouterr().err
    assert "contains 2 source IPs" in err and "Traceback" not in err


def test_cli_replay_as_ip_registers_remapped_rig(tmp_path):
    path = make_recording(tmp_path / "rec", {RIG_A: b"Recorded Driver", RIG_B: b"Other"})
    data = tmp_path / "data"
    code = main(["replay", str(path), "--from-ip", RIG_A, "--as-ip", "10.9.9.9", "--speed", "0",
                 "--no-api", "--quiet", "--data-dir", str(data)])
    assert code == 0
    log_text = (data / "logs" / "hub.log").read_text(encoding="utf-8")
    assert "New rig detected: 10.9.9.9 -> Rig 1" in log_text
    assert "driver: Recorded Driver" in log_text
    assert RIG_A not in json.loads((data / "rigs.json").read_text())["auto_names"]


def test_cli_replay_live_runs_alongside_live_rig(tmp_path, capsys):
    """A live UDP rig and a recording remapped to another IP share one hub: Rig 1 + Rig 2."""
    path = make_recording(tmp_path / "rec", {RIG_A: b"Recorded Driver"}, repeat=20)
    udp_port, http_port = free_port(), free_port(socket.SOCK_STREAM)
    sender = send_later(udp_port, rig_packets(b"Live Driver"), delay=0.3, repeat=15)
    data = tmp_path / "data"
    code = main(["replay", str(path), "--as-ip", "10.9.9.9", "--live", "--speed", "1",
                 "--port", str(udp_port), "--http-port", str(http_port),
                 "--data-dir", str(data), "--duration", "2.5"])
    sender.join()
    assert code == 0
    out = capsys.readouterr().out
    last_second = [l for l in out.splitlines() if "fmt=2025" in l][-2:]
    assert any("10.9.9.9" in l for l in last_second) and any("127.0.0.1" in l for l in last_second)
    log_text = (data / "logs" / "hub.log").read_text(encoding="utf-8")
    assert "driver: Recorded Driver" in log_text and "driver: Live Driver" in log_text
    names = json.loads((data / "rigs.json").read_text())["auto_names"]
    assert set(names) == {"10.9.9.9", "127.0.0.1"}
    assert sorted(names.values()) == ["Rig 1", "Rig 2"]


def test_cli_replay_live_warns_on_ip_collision(tmp_path):
    path = make_recording(tmp_path / "rec", {RIG_A: b"Recorded"}, repeat=5)
    udp_port = free_port()
    sender = send_later(udp_port, rig_packets(b"Live"), delay=0.3, repeat=5)
    data = tmp_path / "data"
    code = main(["replay", str(path), "--as-ip", "127.0.0.1", "--live", "--speed", "0", "--no-api", "--quiet",
                 "--port", str(udp_port), "--data-dir", str(data), "--duration", "1.5"])
    sender.join()
    assert code == 0
    log_text = (data / "logs" / "hub.log").read_text(encoding="utf-8")
    assert log_text.count("the same IP the recording is replayed as") == 1


async def test_replay_rigs_plays_each_copy_as_its_own_rig():
    import asyncio
    from simtelemetry.tools.replay import replay_rigs
    streams = [[(100.0 + i * 0.01, b"a%d" % i) for i in range(300)], [(50.0 + i * 0.01, b"b%d" % i) for i in range(300)]]
    got: list[tuple[bytes, str]] = []
    task = asyncio.create_task(replay_rigs(streams, lambda data, ip, t: got.append((data, ip)), rigs=3, speed=50))
    want = {"10.30.0.1", "10.30.0.2", "10.30.0.3"}
    for _ in range(500):                                # until every rig has played a few packets (<= 5 s)
        if {ip for _, ip in got} == want and all(sum(i == ip for _, i in got) >= 3 for ip in want):
            break
        await asyncio.sleep(0.01)
    task.cancel()
    ips = {ip for _, ip in got}
    assert ips == {"10.30.0.1", "10.30.0.2", "10.30.0.3"}
    assert {d[:1] for d, ip in got if ip == "10.30.0.2"} == {b"b"}        # second rig plays the second source
    first3 = next(d for d, ip in got if ip == "10.30.0.3")
    assert first3 != b"a0"                                                 # a later copy starts further into it
