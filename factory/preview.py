"""Preview (spec 2.7, F9): a cafe's TV, staff page and phone check-in on the seller's PC, before building.

`start_preview(profile, settings)` does, in a new temporary folder (`<temp>/<exe>-preview-<random>/`):

    baked/          profile.json, the logo and a *preview* licence.txt (as the installer would carry them)
    config/hub.toml the hub's settings for the preview only: pages on this PC alone (127.0.0.1)
    data/           the hub's data folder: provisioned from baked/, then the demo's history and six cars
    edge/           the Edge profile the preview's windows use (so the seller's own Edge is never touched)
    hub-output.txt  what the hub printed, for "Show details"

1. bakes the profile (`CafeProfile.baked_profile()`, `ProfileStore.copy_logo`) with a preview licence;
2. runs the hub's own `provision <baked> --data-dir <data> --config <hub.toml>` into it;
3. picks a free port, never 8000 (the live hub) or 20777 (the game's telemetry);
4. starts `run --demo --data-dir <data> --config <hub.toml> --http-port <port>` with the built program
   (dist/<exe>/<exe>.exe, when its build stamp is this source's version) or else this Python with hub/ on its path;
   the demo opens no telemetry port, and the hub's home folder is the temporary folder, so nothing it writes lands
   in the developer's real data, config or backups;
5. waits for /api/health;
6. opens Edge app windows: the TV (/), the staff page (/staff) and a 430x900 phone check-in window (/checkin/<code>
   of a free rig). Without Edge, the usual browser opens the pages instead.

`Preview.stop()` ends the hub and the Edge windows it started (the whole process tree: a Windows job object, or the
process group elsewhere; never taskkill) and deletes the temporary folder. It is safe to call twice and runs at exit.

**The preview licence** (`licence_issue.issue_preview`): licence number 0 and a `preview-` id, never added to the
cafe's history. It is signed with the factory key only when this source's hub trusts that key; otherwise with a
throwaway key the hub refuses, so the preview runs on the demo's own licence (six rigs, every feature, the 9T7 mark)
and `Preview.notes` says so. Whether the hub took the licence is read from the data folder after provisioning, so a
built program that doesn't know the key yet is noticed too.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from simtelemetry import __version__, brand, licence
from simtelemetry.provision import PROFILE_FILE

from . import build, docs
from . import keys as keys_mod
from .docs import DocsError
from .keys import Keys, KeysError
from .licence_issue import Issued, IssueError, issue_preview
from .profile import CafeProfile, ProfileStore

log = logging.getLogger(__name__)

FORBIDDEN_PORTS = frozenset({8000, 20777})     # the live hub's pages and the game's telemetry: never the preview's
PORT_TRIES = 20
HEALTH_TIMEOUT_S = 90.0                        # the demo seeds 60 days of history first (a few seconds)
PROVISION_TIMEOUT_S = 120.0
CHECKIN_WAIT_S = 10.0                          # for the demo's rigs to appear (they get their check-in codes then)
DEMO_PIN = "0000"                              # the demo's owner and staff PIN (a provisioned folder has none)
PIN_HEADER = "X-Staff-Pin"
TEMP_PREFIX = f"{brand.EXE_NAME.lower()}-preview-"
MARKER = ".factory-preview"
STALE_S = 12 * 3600
HOST = "127.0.0.1"                             # the preview's pages are for this PC only, never the cafe LAN
_running_roots: set[Path] = set()              # this factory's previews still running: never swept as stale

TV_WINDOW = (1280, 760)
STAFF_WINDOW = (1100, 860)
CHECKIN_WINDOW = (430, 900)

PROVISION_FAILED = "The cafe's details couldn't be set up for the preview. Show details has what happened."
START_FAILED = "The preview couldn't start. Show details has what happened."
START_SLOW = "The preview took too long to start, so it was stopped. Try again."
NO_PORT = "The preview couldn't find a free connection on this PC. Close some programs and try again."
WRITE_FAILED = "The preview's temporary files couldn't be written. Check the PC has free space and try again."
NOTE_PIN = f"The staff and owner PIN in the preview is {DEMO_PIN}."
NOTE_NO_LICENCE = (f"This copy of {brand.PRODUCT_NAME} doesn't know your signing key yet (Set up keys), so the "
                   f"preview shows six rigs, every feature and the {brand.COMPANY} mark, not this cafe's licence.")
NOTE_NO_EDGE = ("Microsoft Edge wasn't found, so the pages opened in your usual browser. Close them yourself after "
                "Stop preview.")
NOTE_NO_CHECKIN = "Phone check-in isn't part of this cafe's licence, so there is no check-in window."
NOTE_NO_TV = ("The TV screen isn't built on this PC yet, so the TV window shows a placeholder. Build any package "
              "once (or run npm run build in the dashboard folder), then preview again.")
NOTE_CHECKIN_LATE = "The check-in window couldn't be opened. Open the staff page's check-in codes to try it."


class PreviewError(Exception):
    """The preview couldn't start; `str(exc)` is plain English for the window, `details` for "Show details"."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


# --- the hub program -----------------------------------------------------------------------------

@dataclass(frozen=True)
class HubProgram:
    """How to start the hub: the built program, or this Python with hub/ on its path."""

    args: tuple[str, ...]
    kind: Literal["exe", "python"]
    pythonpath: str | None = None

    def env(self, home: Path, base: dict[str, str] | None = None) -> dict[str, str]:
        """The child's environment: the hub's home folder is the preview's temporary folder (its default config,
        data and demo backups all land there), and for Python, hub/ first on its path."""
        env = dict(os.environ if base is None else base)
        env[brand.HOME_ENV] = str(home)
        if self.pythonpath:
            env["PYTHONPATH"] = os.pathsep.join(p for p in (self.pythonpath, env.get("PYTHONPATH")) if p)
        return env


def exe_path(settings: build.FactorySettings) -> Path:
    return settings.repo_root / "dist" / brand.EXE_NAME / f"{brand.EXE_NAME}.exe"


def hub_program(settings: build.FactorySettings, python: str | None = None) -> HubProgram:
    """The built program when it is there and its build stamp is this source's version (spec 2.7), else
    `python -m simtelemetry` from this source."""
    exe = exe_path(settings)
    stamp = build.read_stamp(settings)
    try:
        built = exe.is_file()
    except OSError:
        built = False
    if built and stamp is not None and stamp.get("version") == __version__:
        return HubProgram((str(exe),), "exe")
    return HubProgram((python or console_python(), "-m", "simtelemetry"), "python",
                      str(settings.repo_root / "hub"))


def console_python(executable: str | None = None) -> str:
    """This Python; python.exe instead of pythonw.exe (the factory's launcher), so the hub's output can be read
    for "Show details" (no console window opens: CREATE_NO_WINDOW)."""
    exe = Path(executable or sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").is_file():
        return str(exe.parent / "python.exe")
    return str(exe)


def tv_built(settings: build.FactorySettings) -> bool:
    """The TV dashboard a source hub serves (dashboard/dist); the built program carries its own."""
    try:
        return (settings.repo_root / "dashboard" / "dist" / "index.html").is_file()
    except OSError:
        return False


def provision_command(program: HubProgram, baked: Path, data: Path, config: Path) -> list[str]:
    return [*program.args, "provision", str(baked), "--data-dir", str(data), "--config", str(config)]


def run_command(program: HubProgram, data: Path, config: Path, port: int) -> list[str]:
    check_port(port)
    return [*program.args, "run", "--demo", "--data-dir", str(data), "--config", str(config),
            "--http-port", str(port)]


# --- ports ---------------------------------------------------------------------------------------

def check_port(port: Any) -> int:
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535 or port in FORBIDDEN_PORTS:
        raise ValueError(f"the preview can't use port {port!r}")
    return port


def free_port() -> int:
    """A port nothing listens on, on every address and on 127.0.0.1 (Windows lets a program take 127.0.0.1:N next
    to another's 0.0.0.0:N, so both are tried)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        port = s.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, port))
    return port


def pick_port(port_picker: Callable[[], int] = free_port, tries: int = PORT_TRIES) -> int:
    """A free port from `port_picker`, never 8000 or 20777 (asked again when it offers one)."""
    for _ in range(tries):
        try:
            return check_port(port_picker())
        except (OSError, ValueError):
            continue
    raise PreviewError(NO_PORT)


# --- the temporary folder ------------------------------------------------------------------------

def hub_toml() -> str:
    """The preview's own hub.toml: its pages on this PC only. `provision` adds the cafe's [features]."""
    return ("# The factory's preview only. Deleted when the preview stops.\n"
            "[network]\n"
            f'http_host = "{HOST}"\n'
            f'udp_host = "{HOST}"\n')


def remove_stale(temp_root: Path | None = None, older_than: float = STALE_S, now: float | None = None) -> None:
    """Preview folders left by a crash or power cut (only folders holding the preview's marker)."""
    temp_root = Path(temp_root or tempfile.gettempdir())
    now = time.time() if now is None else now
    try:
        candidates = list(temp_root.glob(TEMP_PREFIX + "*"))
    except OSError:
        return
    active = {os.path.normcase(str(r)) for r in _running_roots}
    for folder in candidates:
        if os.path.normcase(str(folder)) in active:
            continue
        try:
            if (folder / MARKER).is_file() and now - (folder / MARKER).stat().st_mtime > older_than:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


def preview_licence(profile: CafeProfile, settings: build.FactorySettings, keys: Keys | None,
                    store: ProfileStore) -> tuple[Issued, bool]:
    """(the preview licence, signed with the factory key). The factory key is used only when this source's hub
    trusts it; otherwise a throwaway key the hub refuses (the preview then runs on the demo's own licence)."""
    if keys is None:
        try:
            keys = keys_mod.load_private(settings.keys_dir)
        except KeysError:
            keys = None
    trusted = False
    if keys is not None:
        try:
            trusted = keys_mod.is_trusted(keys, build._trusted(settings))
        except (KeysError, OSError):
            trusted = False
    signer: Keys | Ed25519PrivateKey = keys if trusted and keys is not None else Ed25519PrivateKey.generate()
    return issue_preview(profile, signer, logo_dir=store.logo_dir), trusted


def bake(profile: CafeProfile, issued: Issued, store: ProfileStore, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(profile.baked_profile(), indent=2, ensure_ascii=False) + "\n"
    (folder / PROFILE_FILE).write_bytes(text.encode("utf-8"))
    store.copy_logo(profile, folder)
    with open(folder / licence.LICENCE_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(issued.code + "\n")


# --- processes -----------------------------------------------------------------------------------

def _popen_kwargs(stdout: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": stdout, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True              # its own process group, so stop() ends everything it started
    return kwargs


def _kill(proc: Any) -> None:
    """End a process and everything it started (POSIX: its process group). On Windows the job does the tree."""
    try:
        if proc.poll() is not None:
            return
        if isinstance(proc, subprocess.Popen) and os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


def _wait(proc: Any, timeout: float = 10) -> None:
    try:
        proc.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        pass


_no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # 127.0.0.1 never goes via a proxy


def http_get(url: str, headers: dict[str, str] | None = None, timeout: float = 2.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with _no_proxy.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def wait_for_health(base_url: str, proc: Any = None, timeout: float = HEALTH_TIMEOUT_S, poll: float = 0.25,
                    get: Callable[..., tuple[int, bytes]] = http_get) -> dict[str, Any]:
    """/api/health's answer once the hub serves it. PreviewError when the hub stops first or it takes too long."""
    deadline = time.monotonic() + timeout
    while True:
        if proc is not None and proc.poll() is not None:
            raise PreviewError(START_FAILED, f"The hub stopped with exit code {proc.poll()}.")
        try:
            status, body = get(base_url + "/api/health", timeout=2.0)
            if status == 200:
                data = json.loads(body)
                if proc is not None and proc.poll() is not None:     # another hub answered on the port; ours stopped
                    raise PreviewError(START_FAILED, f"The hub stopped with exit code {proc.poll()}.")
                if isinstance(data, dict):
                    return data
        except (OSError, ValueError):
            pass
        if time.monotonic() > deadline:
            raise PreviewError(START_SLOW, f"No answer from {base_url}/api/health within {timeout:g} s.")
        time.sleep(poll)


def checkin_url(base_url: str, get: Callable[..., tuple[int, bytes]] = http_get, wait: float = CHECKIN_WAIT_S,
                poll: float = 0.5) -> tuple[str | None, str | None]:
    """(the check-in page of a rig nobody is driving (else the first rig), None) or (None, a note)."""
    headers = {PIN_HEADER: DEMO_PIN}
    deadline = time.monotonic() + wait
    while True:
        try:
            status, body = get(base_url + "/api/staff/checkin/codes", headers=headers)
            codes = json.loads(body) if status == 200 else None
            if isinstance(codes, dict) and codes.get("enabled") is False:
                return None, NOTE_NO_CHECKIN
            rows = codes.get("rigs") if isinstance(codes, dict) else None
            if rows:
                by_rig = {r["rig_id"]: r["code"] for r in rows}
                free: list[str] = []
                status, body = get(base_url + "/api/staff/rigs", headers=headers)
                if status == 200:
                    free = [r["rig_id"] for r in json.loads(body).get("rigs", []) if r.get("session") is None]
                rig = next((r for r in free if r in by_rig), rows[0]["rig_id"])
                return f"{base_url}/checkin/{by_rig[rig]}", None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        if time.monotonic() > deadline:
            return None, NOTE_CHECKIN_LATE
        time.sleep(poll)


def edge_command(edge: Path, profile_dir: Path, url: str, size: tuple[int, int],
                 position: tuple[int, int] = (0, 0)) -> list[str]:
    """One Edge app window (no tabs or address bar) in the preview's own throwaway Edge profile."""
    return [str(edge), f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check",
            f"--app={url}", f"--window-size={size[0]},{size[1]}", f"--window-position={position[0]},{position[1]}"]


# --- the preview -----------------------------------------------------------------------------------

@dataclass
class Preview:
    root: Path
    data_dir: Path
    port: int
    program: HubProgram
    process: Any
    licensed: bool = False                       # the cafe's (preview) licence is what the hub runs on
    urls: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    details: str = ""
    edge_processes: list[Any] = field(default_factory=list)
    job: Any = None
    _stopped: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def base_url(self) -> str:
        return f"http://{HOST}:{self.port}"

    @property
    def running(self) -> bool:
        return not self._stopped and self.process is not None and self.process.poll() is None

    def output(self) -> str:
        """What the hub printed (for "Show details")."""
        try:
            return (self.root / "hub-output.txt").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def stop(self) -> None:
        """End the hub and the preview's Edge windows, and delete the temporary folder. Safe to call again."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
        procs = [*self.edge_processes, *([self.process] if self.process is not None else [])]
        if self.job is not None:
            try:
                self.job.terminate()
            except Exception:
                log.warning("couldn't end the preview's job", exc_info=True)
        for proc in procs:
            _kill(proc)
        for proc in procs:
            _wait(proc)
        if self.job is not None:
            try:
                self.job.close()
            except Exception:
                pass
        for proc in procs:
            stdout = getattr(proc, "stdout", None)
            if stdout is not None and hasattr(stdout, "close"):
                try:
                    stdout.close()
                except OSError:
                    pass
        _remove_tree(self.root)
        _running_roots.discard(self.root)
        try:
            atexit.unregister(self.stop)
        except Exception:
            pass
        log.info("Preview stopped")


def _remove_tree(root: Path, tries: int = 20, pause: float = 0.25) -> None:
    """Delete the temporary folder; Windows may hold a file for a moment after its program ended."""
    for _ in range(tries):
        shutil.rmtree(root, ignore_errors=True)
        if not root.exists():
            return
        time.sleep(pause)
    log.warning("Couldn't delete the preview folder %s", root)


def _new_job() -> Any:
    if os.name != "nt":
        return None
    try:
        return build.WinJob()
    except Exception:
        log.warning("no job object for the preview; Stop preview ends only the programs it started", exc_info=True)
        return None


def _join_job(job: Any, proc: Any) -> None:
    if job is None or not isinstance(proc, subprocess.Popen):
        return
    try:
        if not job.add(proc):
            log.warning("couldn't put a preview program in its job object")
    except Exception:
        log.warning("couldn't put a preview program in its job object", exc_info=True)


def start_preview(profile: CafeProfile, settings: build.FactorySettings, keys: Keys | None = None, *,
                  store: ProfileStore | None = None, popen: Callable[..., Any] = subprocess.Popen,
                  run: Callable[..., Any] = subprocess.run, opener: Callable[[str], Any] = webbrowser.open,
                  port_picker: Callable[[], int] = free_port, program: HubProgram | None = None,
                  temp_root: Path | None = None, health_timeout: float = HEALTH_TIMEOUT_S,
                  get: Callable[..., tuple[int, bytes]] = http_get, checkin_wait: float = CHECKIN_WAIT_S,
                  job_factory: Callable[[], Any] = _new_job, open_windows: bool = True) -> Preview:
    """Start the cafe's preview (see the module docstring). PreviewError (plain message + details) when it can't;
    nothing is left running and the temporary folder is gone then."""
    store = store or settings.store
    problems = [m for _, m in store.problems(profile)]
    if problems:
        raise PreviewError("Fix these first:\n" + "\n".join(f"- {m}" for m in dict.fromkeys(problems)))
    try:
        issued, signed = preview_licence(profile, settings, keys, store)
    except IssueError as exc:
        raise PreviewError(str(exc)) from None
    program = program or hub_program(settings)
    remove_stale(temp_root)
    try:
        root = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=temp_root))
    except OSError:
        raise PreviewError(WRITE_FAILED) from None
    data, config, baked = root / "data", root / "config" / "hub.toml", root / "baked"
    preview: Preview | None = None
    try:
        try:
            (root / MARKER).write_text("The factory's preview. Safe to delete.\n", encoding="utf-8")
            bake(profile, issued, store, baked)
            config.parent.mkdir()
            config.write_text(hub_toml(), encoding="utf-8")
            data.mkdir()
            from simtelemetry.tools.seed_demo import MARKER as DEMO_MARKER
            (data / DEMO_MARKER).write_text("The factory's preview (demo data). Safe to delete.\n", encoding="utf-8")
        except OSError:
            raise PreviewError(WRITE_FAILED) from None

        env = program.env(root)
        details = [f"Preview folder: {root}", f"Hub: {program.kind} ({' '.join(program.args)})",
                   f"Preview licence {issued.payload.licence_id} "
                   + ("signed with your key." if signed else "signed with a throwaway key (your key isn't known).")]
        args = provision_command(program, baked, data, config)
        kwargs: dict[str, Any] = {"cwd": root, "env": env, "stdin": subprocess.DEVNULL, "capture_output": True,
                                  "timeout": PROVISION_TIMEOUT_S, "check": False}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = run(args, **kwargs)
        except subprocess.TimeoutExpired:
            raise PreviewError(PROVISION_FAILED, "\n".join(details + ["Setting up the cafe took too long."])) \
                from None
        except OSError as exc:
            raise PreviewError(PROVISION_FAILED, "\n".join(details + [f"Couldn't start the hub: {exc}"])) from None
        out = build._decode((result.stdout or b"") + (result.stderr or b""))
        details.append(f"provision (exit {result.returncode}):\n{out.strip()}")
        if result.returncode != 0:
            raise PreviewError(PROVISION_FAILED, "\n".join(details))
        licensed = signed and (data / licence.LICENCE_FILE).is_file()

        port = pick_port(port_picker)
        args = run_command(program, data, config, port)
        job = job_factory()
        try:
            out_file = open(root / "hub-output.txt", "wb")
        except OSError:
            if job is not None:
                job.close()
            raise PreviewError(WRITE_FAILED) from None
        try:
            proc = popen(args, cwd=root, env=env, **_popen_kwargs(out_file))
        except OSError as exc:
            out_file.close()
            if job is not None:
                job.close()
            raise PreviewError(START_FAILED, "\n".join(details + [f"Couldn't start the hub: {exc}"])) from None
        finally:
            if not out_file.closed:
                out_file.close()              # the hub has its own copy of the handle
        _join_job(job, proc)
        preview = Preview(root=root, data_dir=data, port=port, program=program, process=proc, licensed=licensed,
                          job=job)
        _running_roots.add(root)
        atexit.register(preview.stop)
        details.append(f"Hub started on {preview.base_url} (process {getattr(proc, 'pid', '?')}).")
        try:
            wait_for_health(preview.base_url, proc, timeout=health_timeout, get=get)
        except PreviewError as exc:
            raise PreviewError(exc.message, "\n".join(details + [exc.details, preview.output()])) from None

        preview.urls = {"tv": preview.base_url + "/", "staff": preview.base_url + "/staff"}
        notes = [NOTE_PIN] if licensed else [NOTE_NO_LICENCE, NOTE_PIN]
        url, note = checkin_url(preview.base_url, get=get, wait=checkin_wait)
        if url:
            preview.urls["checkin"] = url
        if note:
            notes.append(note)
        if program.kind == "python" and not tv_built(settings):
            notes.append(NOTE_NO_TV)
        preview.notes = notes
        preview.details = "\n".join(details)
        if open_windows:
            _open_windows(preview, settings, popen, opener)
        log.info("Preview of cafe %s on %s", profile.cafe_id, preview.base_url)
        return preview
    except BaseException:
        if preview is not None:
            preview.stop()
        else:
            _remove_tree(root)
        raise


def _open_windows(preview: Preview, settings: build.FactorySettings, popen: Callable[..., Any],
                  opener: Callable[[str], Any]) -> None:
    windows = [("tv", TV_WINDOW, (0, 0)), ("staff", STAFF_WINDOW, (60, 60)), ("checkin", CHECKIN_WINDOW, (880, 40))]
    try:
        edge = docs.find_edge(settings.edge)
    except DocsError:
        edge = None
    if edge is None:
        for name, _, _ in windows:
            if name in preview.urls:
                opener(preview.urls[name])
        preview.notes.append(NOTE_NO_EDGE)
        return
    profile_dir = preview.root / "edge"
    for name, size, position in windows:
        if name not in preview.urls:
            continue
        try:
            proc = popen(edge_command(edge, profile_dir, preview.urls[name], size, position),
                         **_popen_kwargs(subprocess.DEVNULL))
        except OSError:
            opener(preview.urls[name])
            continue
        _join_job(preview.job, proc)
        preview.edge_processes.append(proc)
