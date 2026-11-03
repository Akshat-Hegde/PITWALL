"""The factory's preview (spec 2.7, F9): command lines, ports, provisioning into a temporary folder, the health wait,
Edge windows, cleanup and the preview licence. The hub and Edge are faked, except in the one integration test."""

import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from factory import build as B
from factory import preview as P
from factory.licence_issue import PREVIEW_PREFIX, is_preview
from factory.preview import PreviewError
from factory.profile import load
from simtelemetry import __version__, brand, licence, licence_pubkey
from simtelemetry.provision import provision

from .test_build import cafe, env  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[2]


# --- fakes ---------------------------------------------------------------------------------------

class FakeProc:
    _pid = 40000

    def __init__(self, args, exit_at=None, **kwargs):
        FakeProc._pid += 1
        self.pid = FakeProc._pid
        self.args, self.kwargs = list(args), kwargs
        self.returncode = exit_at
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakePopen:
    def __init__(self, hub_exit=None):
        self.procs: list[FakeProc] = []
        self.hub_exit = hub_exit

    def __call__(self, args, **kwargs):
        proc = FakeProc(args, self.hub_exit if "run" in args else None, **kwargs)
        self.procs.append(proc)
        return proc

    @property
    def hub(self):
        return next(p for p in self.procs if "run" in p.args)

    @property
    def edges(self):
        return [p for p in self.procs if "run" not in p.args]


class FakeProvision:
    """`provision` run in-process with the hub's real code, so the baked folder is checked for real."""

    def __init__(self, rc=None):
        self.calls = []
        self.rc = rc

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if self.rc is not None:
            return subprocess.CompletedProcess(args, self.rc, b"bad files", b"")
        i = args.index("provision")
        src = Path(args[i + 1])
        data = Path(args[args.index("--data-dir") + 1])
        config = Path(args[args.index("--config") + 1])
        res = provision(src, data, config)
        return subprocess.CompletedProcess(args, res.code, "\n".join(res.lines).encode(), b"")


class FakeHub:
    """The hub's HTTP answers: health, check-in codes (rig 1 is busy, rig 2 is free) and staff rigs."""

    def __init__(self, health=True, checkin=True):
        self.health, self.checkin = health, checkin
        self.calls = []

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        if url.endswith("/api/health"):
            if not self.health:
                raise ConnectionRefusedError()
            return 200, b'{"rigs": {}}'
        assert headers == {"X-Staff-Pin": "0000"}
        if url.endswith("/api/staff/checkin/codes"):
            return 200, json.dumps({"enabled": self.checkin, "rigs": [
                {"rig_id": "10.30.0.1", "code": "AAA"}, {"rig_id": "10.30.0.2", "code": "BBB"}]}).encode()
        if url.endswith("/api/staff/rigs"):
            return 200, json.dumps({"rigs": [{"rig_id": "10.30.0.1", "session": {"name": "Maya"}},
                                             {"rig_id": "10.30.0.2", "session": None}]}).encode()
        return 404, b""


@pytest.fixture
def trusted(env, monkeypatch):  # noqa: F811
    """The hub (the in-process provision) trusts the factory key, as a rebuilt hub would after Set up keys."""
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", (env.keys.public,))
    return env


def start(env, p, **kw):  # noqa: F811
    kw.setdefault("store", env.store)
    kw.setdefault("popen", FakePopen())
    kw.setdefault("run", FakeProvision())
    kw.setdefault("get", FakeHub())
    kw.setdefault("port_picker", lambda: 18123)
    kw.setdefault("temp_root", env.tmp / "temp")
    kw.setdefault("job_factory", lambda: None)
    kw.setdefault("program", P.HubProgram(("python", "-m", "simtelemetry"), "python", str(ROOT / "hub")))
    kw.setdefault("health_timeout", 2)
    kw.setdefault("checkin_wait", 0.5)
    (env.tmp / "temp").mkdir(exist_ok=True)
    return P.start_preview(p, env.settings, kw.pop("keys", env.keys), **kw)


# --- the hub program and its command lines ---------------------------------------------------------

def test_python_hub_when_nothing_is_built(env):  # noqa: F811
    prog = P.hub_program(env.settings, python="/venv/python")
    assert prog.kind == "python" and prog.args == ("/venv/python", "-m", "simtelemetry")
    assert prog.pythonpath == str(env.repo / "hub")
    e = prog.env(Path("/tmp/x"), base={"PYTHONPATH": "/other", "PATH": "/bin"})
    assert e["PYTHONPATH"] == os.pathsep.join([str(env.repo / "hub"), "/other"])
    assert e[brand.HOME_ENV] == str(Path("/tmp/x")) and e["PATH"] == "/bin"


def _built(env, version):  # noqa: F811
    exe = P.exe_path(env.settings)
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    (exe.parent / B.STAMP_FILE).write_text(json.dumps({"version": version, "commit": "abc"}), encoding="utf-8")
    return exe


def test_built_program_when_its_stamp_is_this_version(env):  # noqa: F811
    exe = _built(env, __version__)
    prog = P.hub_program(env.settings)
    assert prog.kind == "exe" and prog.args == (str(exe),) and prog.pythonpath is None
    assert "PYTHONPATH" not in prog.env(env.tmp, base={})
    assert exe == env.repo / "dist" / brand.EXE_NAME / f"{brand.EXE_NAME}.exe"


def test_older_built_program_is_not_used(env):  # noqa: F811
    _built(env, "0.0.1")
    assert P.hub_program(env.settings).kind == "python"


def test_console_python_instead_of_pythonw(tmp_path):
    (tmp_path / "pythonw.exe").write_bytes(b"")
    (tmp_path / "python.exe").write_bytes(b"")
    assert P.console_python(str(tmp_path / "pythonw.exe")) == str(tmp_path / "python.exe")
    assert P.console_python(str(tmp_path / "python.exe")) == str(tmp_path / "python.exe")
    assert P.console_python() == sys.executable or sys.executable.lower().endswith("pythonw.exe")


def test_command_lines():
    prog = P.HubProgram(("hub.exe",), "exe")
    data, config, baked = Path("/t/data"), Path("/t/config/hub.toml"), Path("/t/baked")
    assert P.provision_command(prog, baked, data, config) == [
        "hub.exe", "provision", str(baked), "--data-dir", str(data), "--config", str(config)]
    assert P.run_command(prog, data, config, 18123) == [
        "hub.exe", "run", "--demo", "--data-dir", str(data), "--config", str(config), "--http-port", "18123"]
    for bad in (8000, 20777, 80, 0, 70000, True, "18000"):
        with pytest.raises(ValueError):
            P.run_command(prog, data, config, bad)


def test_the_hub_accepts_these_flags():
    """The real CLI has every flag the preview passes (no --http-port surprise)."""
    from simtelemetry.__main__ import build_parser
    args = build_parser().parse_args(["run", "--demo", "--data-dir", "d", "--config", "c.toml", "--http-port", "18123"])
    assert args.demo and args.http_port == 18123 and str(args.config) == "c.toml"
    args = build_parser().parse_args(["provision", "b", "--data-dir", "d", "--config", "c.toml"])
    assert args.command == "provision"


def test_preview_hub_toml_keeps_pages_on_this_pc():
    import tomllib
    data = tomllib.loads(P.hub_toml())
    assert data["network"] == {"http_host": "127.0.0.1", "udp_host": "127.0.0.1"}


# --- ports -----------------------------------------------------------------------------------------

def test_port_never_8000_or_the_telemetry_port():
    offered = iter([8000, 20777, 8000, 18123])
    assert P.pick_port(lambda: next(offered)) == 18123
    with pytest.raises(PreviewError) as exc:
        P.pick_port(lambda: 8000)
    assert str(exc.value) == P.NO_PORT

    def busy():
        raise OSError("no ports")
    with pytest.raises(PreviewError):
        P.pick_port(busy)


def test_free_port_is_free_and_allowed():
    for _ in range(5):
        port = P.free_port()
        assert port not in P.FORBIDDEN_PORTS and P.check_port(port) == port


def test_a_picker_offering_8000_never_reaches_the_hub(trusted, monkeypatch):
    p = cafe(trusted)
    offered = iter([8000, 18124])
    popen = FakePopen()
    prev = start(trusted, p, popen=popen, port_picker=lambda: next(offered))
    try:
        assert prev.port == 18124 and popen.hub.args[-1] == "18124"
        assert all(a != "8000" and ":8000/" not in a for proc in popen.procs for a in proc.args)
    finally:
        prev.stop()


# --- start, windows and stop -------------------------------------------------------------------------

def test_preview_happy_path(trusted):
    p = cafe(trusted)
    saved_before = trusted.store.find(p.cafe_id).read_bytes()
    popen, run, hub = FakePopen(), FakeProvision(), FakeHub()
    prev = start(trusted, p, popen=popen, run=run, get=hub)
    root = prev.root
    try:
        assert root.parent == trusted.tmp / "temp" and root.name.startswith(P.TEMP_PREFIX)
        data, config = root / "data", root / "config" / "hub.toml"
        # provision ran with the temporary folders only, and the hub's home is the temporary folder
        (args, kwargs), = run.calls
        assert args == ["python", "-m", "simtelemetry", "provision", str(root / "baked"), "--data-dir", str(data),
                        "--config", str(config)]
        assert kwargs["env"][brand.HOME_ENV] == str(root) and kwargs["cwd"] == root
        assert kwargs["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(ROOT / "hub")
        # the cafe's details went in, with its preview licence
        settings = json.loads((data / "settings.json").read_text(encoding="utf-8"))
        assert settings["name"] == "Apex Lounge" and settings["owner_pin"] == ""
        lic = licence.read_file(data)
        assert lic.payload.cafe_id == p.cafe_id and lic.payload.seq == 0 and is_preview(lic.payload)
        assert lic.payload.licence_id.startswith(PREVIEW_PREFIX) and lic.payload.rigs == 6
        assert prev.licensed and P.NOTE_NO_LICENCE not in prev.notes and P.NOTE_PIN in prev.notes
        assert P.NOTE_NO_TV in prev.notes                       # the fake repo has no dashboard/dist
        assert "udp_host" in config.read_text(encoding="utf-8")
        # the hub: demo, the temporary data folder, the picked port
        assert popen.hub.args == ["python", "-m", "simtelemetry", "run", "--demo", "--data-dir", str(data),
                                  "--config", str(config), "--http-port", "18123"]
        assert popen.hub.kwargs["env"][brand.HOME_ENV] == str(root)
        assert prev.base_url == "http://127.0.0.1:18123"
        # the windows: TV, staff, phone check-in of the free rig, in a throwaway Edge profile
        assert prev.urls == {"tv": "http://127.0.0.1:18123/", "staff": "http://127.0.0.1:18123/staff",
                             "checkin": "http://127.0.0.1:18123/checkin/BBB"}
        edges = popen.edges
        assert len(edges) == 3
        for proc, url in zip(edges, prev.urls.values()):
            assert proc.args[0] == str(trusted.settings.edge)
            assert f"--app={url}" in proc.args and f"--user-data-dir={root / 'edge'}" in proc.args
            assert "--no-first-run" in proc.args
        assert "--window-size=430,900" in edges[2].args
        assert "--window-size=1280,760" in edges[0].args
        # nothing recorded: the profile's history and file are untouched
        assert p.history == [] and load(trusted.store.find(p.cafe_id)).history == []
        assert trusted.store.find(p.cafe_id).read_bytes() == saved_before
        assert prev.running
    finally:
        prev.stop()
    assert not root.exists()
    assert all(proc.killed for proc in popen.procs)
    assert not prev.running
    prev.stop()                                    # again: nothing happens
    assert not list((trusted.tmp / "temp").iterdir())


def test_no_trusted_key_previews_on_the_demo_licence(env, monkeypatch):  # noqa: F811
    """The hub doesn't know the factory key: the preview still runs, on the demo's own licence, and says so."""
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", ())
    (env.repo / "hub" / "simtelemetry" / "licence_pubkey.py").write_text("TRUSTED_KEYS = ()\n", encoding="utf-8")
    p = cafe(env)
    prev = start(env, p)
    try:
        baked = (prev.root / "baked" / "licence.txt").read_text(encoding="utf-8").strip()
        parsed = licence.parse(baked)
        payload = licence.check_payload(parsed.payload)
        assert is_preview(payload) and payload.seq == 0
        with pytest.raises(licence.LicenceError):          # a throwaway key, not the factory's
            licence.verify(baked, keys=(env.keys.public,))
        assert not (prev.root / "data" / "licence.txt").exists()
        assert not prev.licensed and P.NOTE_NO_LICENCE in prev.notes
        assert (prev.root / "data" / "settings.json").exists()     # the cafe's details are still shown
    finally:
        prev.stop()


def test_no_keys_at_all(env, monkeypatch):  # noqa: F811
    """Keys not set up yet: a throwaway key, the demo's licence and the note."""
    p = cafe(env)
    env.settings.keys_dir = env.tmp / "no-keys"
    prev = start(env, p, keys=None)
    try:
        assert not prev.licensed and P.NOTE_NO_LICENCE in prev.notes
        assert "throwaway" in prev.details
    finally:
        prev.stop()


def test_unbranded_preview_licence(trusted):
    p = cafe(trusted, name="Quiet Laps", variant="unbranded", rigs=4)
    prev = start(trusted, p)
    try:
        lic = licence.read_file(prev.data_dir)
        assert lic.payload.variant == "unbranded" and lic.payload.rigs == 4 and prev.licensed
    finally:
        prev.stop()


def test_profile_problems_start_nothing(trusted):
    p = cafe(trusted)
    p.name = ""
    popen, run = FakePopen(), FakeProvision()
    with pytest.raises(PreviewError) as exc:
        start(trusted, p, popen=popen, run=run)
    assert str(exc.value).startswith("Fix these first:")
    assert not popen.procs and not run.calls and not list((trusted.tmp / "temp").iterdir())


def test_provision_failure_cleans_up(trusted):
    p = cafe(trusted)
    popen = FakePopen()
    with pytest.raises(PreviewError) as exc:
        start(trusted, p, popen=popen, run=FakeProvision(rc=2))
    assert str(exc.value) == P.PROVISION_FAILED and "bad files" in exc.value.details
    assert not popen.procs and not list((trusted.tmp / "temp").iterdir())


def test_hub_that_never_answers_is_stopped(trusted):
    p = cafe(trusted)
    popen = FakePopen()
    with pytest.raises(PreviewError) as exc:
        start(trusted, p, popen=popen, get=FakeHub(health=False), health_timeout=0.3)
    assert str(exc.value) == P.START_SLOW
    assert popen.hub.killed and not popen.edges
    assert not list((trusted.tmp / "temp").iterdir())


def test_hub_that_stops_at_once(trusted):
    p = cafe(trusted)
    popen = FakePopen(hub_exit=2)
    with pytest.raises(PreviewError) as exc:
        start(trusted, p, popen=popen, get=FakeHub(health=False))
    assert str(exc.value) == P.START_FAILED and "exit code 2" in exc.value.details
    assert not list((trusted.tmp / "temp").iterdir())


def test_hub_that_cant_start(trusted):
    p = cafe(trusted)

    def popen(args, **kw):
        raise FileNotFoundError("no python")
    with pytest.raises(PreviewError) as exc:
        start(trusted, p, popen=popen)
    assert str(exc.value) == P.START_FAILED and "no python" in exc.value.details
    assert not list((trusted.tmp / "temp").iterdir())


def test_without_edge_the_usual_browser_opens(trusted):
    p = cafe(trusted)
    trusted.settings.edge = None
    opened = []
    popen = FakePopen()
    import factory.docs as D
    orig = D.edge_candidates
    try:
        D.edge_candidates = lambda env=None: [trusted.tmp / "nowhere" / "msedge.exe"]
        prev = start(trusted, p, popen=popen, opener=opened.append)
    finally:
        D.edge_candidates = orig
    try:
        assert opened == list(prev.urls.values()) and len(opened) == 3
        assert not popen.edges and P.NOTE_NO_EDGE in prev.notes
    finally:
        prev.stop()


def test_no_checkin_window_without_checkin(trusted):
    p = cafe(trusted)
    popen = FakePopen()
    prev = start(trusted, p, popen=popen, get=FakeHub(checkin=False))
    try:
        assert set(prev.urls) == {"tv", "staff"} and len(popen.edges) == 2
        assert P.NOTE_NO_CHECKIN in prev.notes
    finally:
        prev.stop()


def test_job_object_gets_every_program(trusted, monkeypatch):
    """On Windows the hub and its Edge windows go into one job, ended by Stop preview."""
    class Job:
        def __init__(self):
            self.added, self.terminated, self.closed = [], False, False

        def add(self, proc):
            self.added.append(proc)
            return True

        def terminate(self):
            self.terminated = True

        def close(self):
            self.closed = True

    job = Job()
    monkeypatch.setattr(P, "_join_job", lambda j, proc: j.add(proc) if j is not None else None)
    p = cafe(trusted)
    popen = FakePopen()
    prev = start(trusted, p, popen=popen, job_factory=lambda: job)
    assert job.added == popen.procs and len(job.added) == 4
    prev.stop()
    assert job.terminated and job.closed


def test_stale_preview_folders_are_removed(tmp_path):
    old, new, other = tmp_path / (P.TEMP_PREFIX + "old"), tmp_path / (P.TEMP_PREFIX + "new"), tmp_path / "pitwall-x"
    for d in (old, new, other):
        d.mkdir()
        (d / P.MARKER).write_text("x")
    os.utime(old / P.MARKER, (1, 1))
    (tmp_path / (P.TEMP_PREFIX + "nomarker")).mkdir()
    P.remove_stale(tmp_path)
    assert not old.exists() and new.exists() and other.exists() and (tmp_path / (P.TEMP_PREFIX + "nomarker")).exists()


# --- the health wait against a real (fake) HTTP server -------------------------------------------------

class _Health(http.server.BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):
        body = b'{"ok": true}'
        self.send_response(self.status if self.path == "/api/health" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.HTTPServer(("127.0.0.1", P.free_port()), _Health)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_health_wait_succeeds(server):
    _Health.status = 200
    assert P.wait_for_health(f"http://127.0.0.1:{server.server_address[1]}", timeout=5) == {"ok": True}


def test_health_wait_times_out_on_errors(server):
    _Health.status = 503
    try:
        with pytest.raises(PreviewError) as exc:
            P.wait_for_health(f"http://127.0.0.1:{server.server_address[1]}", timeout=0.5, poll=0.1)
        assert str(exc.value) == P.START_SLOW
    finally:
        _Health.status = 200


def test_health_wait_times_out_when_nothing_listens():
    with pytest.raises(PreviewError):
        P.wait_for_health(f"http://127.0.0.1:{P.free_port()}", timeout=0.5, poll=0.1)


# --- the real thing ------------------------------------------------------------------------------------

def test_real_preview_runs_the_demo_with_the_cafe(env, monkeypatch):  # noqa: F811
    """`python -m simtelemetry provision` and `run --demo` for real on a spare port: the hub answers, shows the
    provisioned cafe, and Stop preview ends it and deletes everything. (No Edge here: open_windows=False.)"""
    p = cafe(env, name="Chai & Laps")
    program = P.HubProgram((sys.executable, "-m", "simtelemetry"), "python", str(ROOT / "hub"))
    try:
        prev = P.start_preview(p, env.settings, env.keys, store=env.store, program=program,
                               temp_root=env.tmp, open_windows=False, health_timeout=60)
    except PreviewError as exc:
        if str(exc) == P.START_SLOW:
            pytest.skip("the demo hub took too long to start on this machine")
        raise AssertionError(f"{exc}\n{exc.details}")
    try:
        assert prev.port not in P.FORBIDDEN_PORTS
        status, body = P.http_get(prev.base_url + "/api/health")
        assert status == 200
        status, body = P.http_get(prev.base_url + "/api/staff/rigs", headers={P.PIN_HEADER: P.DEMO_PIN})
        assert status == 200 and json.loads(body)["cafe"] == "Chai & Laps"
        assert json.loads(body)["demo"] is True
        assert "checkin" in prev.urls
        # this source's hub doesn't trust the test key: the preview says so and runs on the demo's licence
        assert not prev.licensed and P.NOTE_NO_LICENCE in prev.notes
        proc = prev.process
    finally:
        prev.stop()
    assert proc.poll() is not None
    assert not prev.root.exists()
    assert load(env.store.find(p.cafe_id)).history == []


def test_no_tv_note_when_the_dashboard_is_built(trusted):
    p = cafe(trusted)
    (trusted.repo / "dashboard" / "dist").mkdir(parents=True)
    (trusted.repo / "dashboard" / "dist" / "index.html").write_text("<html></html>")
    prev = start(trusted, p)
    try:
        assert P.NOTE_NO_TV not in prev.notes
    finally:
        prev.stop()
