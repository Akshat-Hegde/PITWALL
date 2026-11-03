"""The package pipeline (spec 2.5, F7, 3): one cafe's ready-to-ship folder, Rebuild all, and Issue upgrade.

`build_package(profile, settings, runner, keys)` makes `<Shipments>/<Cafe> (<date>)/` holding exactly:

    <exe>-Setup-<slug>.exe          the cafe's installer (build.ps1 -InstallerOnly with the baked profile)
    Setup guide - <Cafe>.pdf        docs.render_html("guide") printed by Edge
    Licence certificate - <Cafe>.pdf
    <product> guide video.mp4       copied from factory/assets/video/{9t7,unbranded}.mp4
    README.txt

Steps (BUILD_STEPS): 1 check everything first (profile problems, settings, signing key trusted by this build, Edge,
the variant's video), so nothing is issued or compiled for a build that can't finish; 2 look at the program build
(dist/<exe>/build-stamp.json); 3 issue the licence (seq = profile.next_seq()); 4 bake profile.json, the logo and
licence.txt into a staging folder and run build.ps1, which rebuilds the program first if it is stale; 5 the PDFs;
6 the video and README; 7 verify the package; 8 rename the staging package into place; 9 record the history.

Atomic: everything is written under `<Shipments>/.staging-<random>/` (same drive, so the final rename is atomic)
and only the finished, verified `package` folder is renamed into place. Any failure or cancel removes the staging
folder; the history is appended only after the rename, and if the profile can't be saved the package is taken back
out, so "a package exists" and "its licence is in the history" are always true together. A licence issued for a
build that then failed is simply discarded: no code left the PC, so its seq is used again by the next build.

The private key never leaves the key folder: it is only used in memory to sign, the key folder may not be inside
the Shipments folder, and verification refuses a package holding the key's bytes.

Errors are `BuildError(message, details)`: a plain-English message for the window and the step log for
"Show details". `BuildCancelled` is a BuildError for a cancel.

Subprocesses go through a `Runner` (build.ps1 via PowerShell; Edge via docs.html_to_pdf's runner) so tests use
fakes. `FactorySettings` is the factory app's settings file (not in the repo, not in Shipments).
"""

from __future__ import annotations

import base64
import ctypes
import datetime as dt
import json
import locale
import logging
import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from simtelemetry import __version__, brand, licence
from simtelemetry.provision import PROFILE_FILE, ProvisionError, load_baked, write_atomic

from . import docs, pricing
from . import keys as keys_mod
from .docs import DocsError
from .keys import Keys, KeysError
from .licence_issue import IssueError, Issued, issue
from .profile import SAFETY_FLAGS, CafeProfile, HistoryEntry, ProfileError, ProfileStore, safe_file_name

log = logging.getLogger(__name__)

FACTORY_DIR = Path(__file__).resolve().parent
REPO_ROOT = keys_mod.REPO_ROOT
VIDEO_DIR = FACTORY_DIR / "assets" / "video"
VIDEO_FILES = {"9t7": "9t7.mp4", "unbranded": "unbranded.mp4"}
BUILD_SCRIPT = Path("packaging") / "build.ps1"
STAMP_FILE = "build-stamp.json"
SETTINGS_FILE = "settings.json"
CONFIG_ENV = f"{brand.EXE_NAME.upper()}_FACTORY_CONFIG"          # PITWALL_FACTORY_CONFIG: the settings folder
SHIPMENTS_NAME = f"{brand.PRODUCT_NAME} Shipments"
STAGING_PREFIX = ".staging-"
STALE_STAGING_S = 12 * 3600          # a staging folder left by a crash or power cut is removed by a later build
BUILD_TIMEOUT_S = 60 * 60            # a full program build (dashboard, PyInstaller, smoke test) plus the installer
LICENCE_TXT = licence.LICENCE_FILE
UNBRANDED_VENDOR = "none"            # build.ps1 -Vendor none = no publisher (an empty argument can be dropped)

BUILD_STEPS = (
    "Checking the cafe's details",
    "Checking the program",
    "Making the licence",
    "Making the installer",
    "Making the guide and certificate",
    "Copying the guide video",
    "Checking the package",
    "Saving the package",
    "Recording the build",
)
UPGRADE_STEPS = (
    "Checking the cafe's details",
    "Making the new licence code",
    "Making the upgrade certificate",
    "Checking the upgrade",
    "Saving the upgrade",
    "Recording the upgrade",
)

VIDEO_MISSING = "Guide video for this variant is missing. Copy it into factory\\assets\\video (see the README there)."
KEY_NOT_TRUSTED = (f"This copy of {brand.PRODUCT_NAME} doesn't know your signing key yet, so a cafe's hub would "
                   "refuse its licences. Finish Set up keys (it adds your key to the program), then build again.")
CANCELLED = "The build was cancelled. Nothing was saved."
UPGRADE_CANCELLED = "Cancelled. No upgrade code was saved."
WRITE_FAILED = ("The package couldn't be written. Check the Shipments folder is there, has free space and isn't "
                "read-only, then try again.")
UNEXPECTED = "Something went wrong, so nothing was saved. Try again; Show details has what happened."
NOT_RECORDED = ("The cafe's history couldn't be saved, so the new package was taken out again. Check the Shipments "
                "folder isn't read-only, then build again.")

Progress = Callable[[int, int, str], None]          # (steps done, steps in all, what is happening now)


class BuildError(Exception):
    """A build, rebuild or upgrade stopped. `message` is plain English for the window; `details` is the step log
    for "Show details"."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class BuildCancelled(BuildError):
    """The seller pressed Cancel; everything written so far was removed."""


# --- settings -----------------------------------------------------------------------------------

def config_dir(env: dict[str, str] | None = None) -> Path:
    """The factory's own folder: `%USERPROFILE%\\<Product>Factory` (the keys folder's parent), or $<PRODUCT>_FACTORY_CONFIG.
    A keys folder moved with <PRODUCT>_FACTORY_KEYS doesn't move the settings."""
    env = dict(os.environ if env is None else env)
    if env.get(CONFIG_ENV):
        return Path(env[CONFIG_ENV])
    env.pop(keys_mod.KEYS_ENV, None)
    return keys_mod.default_dir(env).parent


def settings_path(env: dict[str, str] | None = None) -> Path:
    return config_dir(env) / SETTINGS_FILE


def default_shipments() -> Path:
    """Documents\\<Product> Shipments, outside the repo (spec 2.8)."""
    return Path.home() / "Documents" / SHIPMENTS_NAME


@dataclass
class FactorySettings:
    """The factory's settings (spec 2.8). Saved: `shipments`, `edge`, `keys_dir`. Not saved: `repo_root` (the
    factory builds the source it runs from) and `video_dir` (factory/assets/video); tests change both."""

    shipments: Path = field(default_factory=default_shipments)
    edge: Path | None = None                     # None: find Edge in the standard places
    keys_dir: Path | None = None                 # None: keys.default_dir()
    repo_root: Path = REPO_ROOT
    video_dir: Path = VIDEO_DIR
    load_problem: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        self.shipments = Path(self.shipments)
        self.edge = Path(self.edge) if self.edge else None
        self.keys_dir = Path(self.keys_dir) if self.keys_dir else None
        self.repo_root = Path(self.repo_root)
        self.video_dir = Path(self.video_dir)

    @property
    def key_folder(self) -> Path:
        return keys_mod.keys_dir(self.keys_dir)

    @property
    def store(self) -> ProfileStore:
        return ProfileStore(self.shipments)

    def to_json(self) -> dict[str, Any]:
        return {"v": 1, "shipments": str(self.shipments), "edge": str(self.edge) if self.edge else None,
                "keys_dir": str(self.keys_dir) if self.keys_dir else None}

    @classmethod
    def load(cls, path: Path | None = None) -> "FactorySettings":
        """The saved settings; the defaults when there is no file. A damaged file gives the defaults and a plain
        `load_problem` for the window (the file is replaced on the next save)."""
        path = Path(path) if path is not None else settings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return cls()
        except (OSError, UnicodeDecodeError, ValueError):
            return cls(load_problem="The factory's settings couldn't be read, so the usual ones are used. "
                                    "Check them in Settings.")
        if not isinstance(data, dict):
            return cls(load_problem="The factory's settings couldn't be read, so the usual ones are used. "
                                    "Check them in Settings.")
        out = cls()
        for key in ("shipments", "edge", "keys_dir"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                setattr(out, key, Path(value.strip()))
        return out

    def save(self, path: Path | None = None) -> Path:
        """Atomic. Never inside the repo or the Shipments folder. Raises BuildError with a plain message."""
        path = Path(path) if path is not None else settings_path()
        for root in (self.repo_root, self.shipments):
            if keys_mod.is_inside(path, root):
                raise BuildError("The factory's settings can't be kept in the program's folder or the Shipments "
                                 "folder.")
        text = json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n"
        try:
            write_atomic(path, text.encode("utf-8"))
        except OSError:
            raise BuildError("The settings couldn't be saved. Try again; if it keeps happening, restart the PC.") \
                from None
        return path

    def problems(self) -> list[str]:
        """What stops any build, in plain English ([] = fine)."""
        out = []
        if keys_mod.is_inside(self.shipments, self.repo_root):
            out.append("Choose a Shipments folder outside the program's source folder (for example in Documents).")
        if any(c in str(self.shipments) for c in '{}"'):
            out.append("The Shipments folder's location can't contain { or }. Choose another folder in Settings.")
        if keys_mod.is_inside(self.key_folder, self.shipments):
            out.append("Your signing key is inside the Shipments folder, which is shared and shipped. Choose "
                       "another Shipments folder in Settings.")
        elif keys_mod.is_inside(self.shipments, self.key_folder):
            out.append("The Shipments folder can't be inside the signing key's folder. Choose another one in "
                       "Settings.")
        return out


# --- running programs ---------------------------------------------------------------------------

@dataclass
class RunResult:
    returncode: int
    output: str = ""
    stopped: Literal["cancelled", "timeout"] | None = None


def _fallback_encoding() -> str:
    """What a line that isn't UTF-8 is read as: on Windows the console's OEM code page (PowerShell writes to a pipe
    in it), else the locale's; never fails."""
    names = []
    if os.name == "nt":
        try:
            names.append(f"cp{ctypes.windll.kernel32.GetOEMCP()}")          # type: ignore[attr-defined]
        except Exception:
            pass
    names += [locale.getpreferredencoding(False) or "", "latin-1"]
    for name in names:
        try:
            if name and "".encode(name) == b"":
                return name
        except LookupError:
            continue
    return "latin-1"


def _decode(data: bytes, fallback: str | None = None) -> str:
    """The captured output for "Show details", line by line: UTF-8 where it is (Python, npm), else the console's
    code page (PowerShell, ISCC), with anything unreadable replaced, so mixed output never fails or garbles it all."""
    fallback = fallback or _fallback_encoding()
    out = []
    for line in data.splitlines(keepends=True):
        try:
            out.append(line.decode("utf-8"))
        except UnicodeDecodeError:
            out.append(line.decode(fallback, errors="replace"))
    return "".join(out)


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount",
                                                      "OtherOperationCount", "ReadTransferCount",
                                                      "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class WinJob:
    """A Windows Job Object holding a command and every program it starts (PowerShell, npm, PyInstaller, ISCC), so
    Cancel or a timeout ends the whole tree without taskkill. KILL_ON_JOB_CLOSE also ends them when the job is
    closed: after the command, or if the factory itself closes. `kernel32` is injectable for tests."""

    EXTENDED_LIMIT_INFORMATION = 9
    KILL_ON_JOB_CLOSE = 0x2000

    def __init__(self, kernel32: Any = None) -> None:
        if kernel32 is None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)          # type: ignore[attr-defined]
            kernel32.CreateJobObjectW.restype = ctypes.c_void_p
            kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
            for fn in ("SetInformationJobObject", "AssignProcessToJobObject", "TerminateJobObject", "CloseHandle"):
                getattr(kernel32, fn).restype = ctypes.c_int
            kernel32.SetInformationJobObject.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                                         ctypes.c_uint32)
            kernel32.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
            kernel32.TerminateJobObject.argtypes = (ctypes.c_void_p, ctypes.c_uint)
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        self.k = kernel32
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObject failed")
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = self.KILL_ON_JOB_CLOSE
        if not self.k.SetInformationJobObject(self.handle, self.EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                              ctypes.sizeof(info)):
            self.close()
            raise OSError("SetInformationJobObject failed")

    def add(self, proc: subprocess.Popen) -> bool:
        """Put a just-started process in the job (programs it starts from now on join it too)."""
        return bool(self.k.AssignProcessToJobObject(self.handle, int(proc._handle)))   # type: ignore[attr-defined]

    def terminate(self) -> None:
        self.k.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


class Runner:
    """Runs the real programs. Tests pass a fake with the same two methods.

    `run(args, cwd, timeout, cancel)` runs a command with its output captured (for "Show details"), and stops it
    when `cancel` is set or the time is up. `edge` is the runner docs.html_to_pdf calls (subprocess.run's shape).
    """

    poll_s = 0.2
    windows = os.name == "nt"
    job_factory: Callable[[], Any] = WinJob

    def _job_for(self, proc: subprocess.Popen) -> Any:
        """On Windows, a job holding the process tree (None if Windows refuses: then only PowerShell is stopped)."""
        if not self.windows:
            return None
        try:
            job = self.job_factory()
        except Exception:
            log.warning("no job object for the build; Cancel stops only PowerShell", exc_info=True)
            return None
        try:
            if job.add(proc):
                return job
        except Exception:
            pass
        log.warning("couldn't put the build in a job object; Cancel stops only PowerShell")
        job.close()
        return None

    def run(self, args: list[str], *, cwd: Path | None = None, timeout: float = BUILD_TIMEOUT_S,
            cancel: threading.Event | None = None) -> RunResult:
        kwargs: dict[str, Any] = {"cwd": cwd, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
                                  "stderr": subprocess.STDOUT}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True              # so a cancel stops the whole group
        proc = subprocess.Popen(args, **kwargs)              # OSError: the caller says it couldn't start
        job = self._job_for(proc)
        chunks: list[bytes] = []
        reader = threading.Thread(target=lambda: chunks.extend(iter(lambda: proc.stdout.read(65536), b"")),
                                  daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        stopped: Literal["cancelled", "timeout"] | None = None
        while True:
            try:
                proc.wait(timeout=self.poll_s)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancel is not None and cancel.is_set():
                stopped = "cancelled"
            elif time.monotonic() > deadline:
                stopped = "timeout"
            if stopped:
                _stop(proc, job)
                break
        if job is not None:
            job.close()                                      # KILL_ON_JOB_CLOSE: nothing it started outlives it
        reader.join(timeout=10)
        if not reader.is_alive():
            try:
                proc.stdout.close()
            except OSError:
                pass
        # else a program it started still holds the pipe: closing it now could block this thread for good, so the
        # daemon reader is left to end with that program.
        return RunResult(proc.returncode if proc.returncode is not None else -1, _decode(b"".join(list(chunks))),
                         stopped)

    def edge(self, args: list[str], **kwargs: Any) -> Any:
        return subprocess.run(args, **kwargs)


def _stop(proc: subprocess.Popen, job: Any = None) -> None:
    """Stop a command we started and everything it started: on Windows by ending its job object (no taskkill), or
    PowerShell alone when there is no job; elsewhere its process group."""
    try:
        if job is not None:
            job.terminate()
        elif os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def powershell_exe(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    if os.name == "nt":
        root = env.get("SystemRoot") or r"C:\Windows"
        return str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    return "powershell"


def build_command(settings: FactorySettings, profile_dir: Path, slug: str, variant: str) -> list[str]:
    """build.ps1 for one cafe's installer: reuses the program when its stamp matches, else builds it first."""
    vendor = brand.COMPANY if variant == "9t7" else UNBRANDED_VENDOR
    return [powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(settings.repo_root / BUILD_SCRIPT), "-InstallerOnly",
            "-ProfileDir", str(profile_dir), "-CafeSlug", slug, "-Vendor", vendor]


# --- the program build's stamp ----------------------------------------------------------------------

def stamp_path(settings: FactorySettings) -> Path:
    return settings.repo_root / "dist" / brand.EXE_NAME / STAMP_FILE


def read_stamp(settings: FactorySettings) -> dict[str, Any] | None:
    """dist/<exe>/build-stamp.json ({version, commit, dirty, signed, built}), or None."""
    try:
        data = json.loads(stamp_path(settings).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("version"), str) else None


# --- the job: log, progress, cancel ------------------------------------------------------------------

class BuildLog:
    """The "Show details" text. Never holds key material (nothing secret is ever passed to it)."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, text: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        for line in str(text).splitlines() or [""]:
            self.lines.append(f"{stamp}  {line}")
        log.info("%s", text)

    def output(self, title: str, text: str) -> None:
        self.lines.append(f"----- {title} -----")
        self.lines.extend(text.rstrip().splitlines())
        self.lines.append(f"----- end of {title} -----")

    def text(self) -> str:
        return "\n".join(self.lines) + ("\n" if self.lines else "")


class _Job:
    def __init__(self, steps: tuple[str, ...], cancel: threading.Event | None, progress: Progress | None,
                 log_: BuildLog, cancelled: str, offset: int = 0, total: int | None = None, prefix: str = "") -> None:
        self.steps, self.cancel, self.progress, self.log = steps, cancel, progress, log_
        self.cancelled_text = cancelled
        self.offset, self.total, self.prefix = offset, total or len(steps), prefix

    def check(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            self.log.add("Cancelled.")
            raise BuildCancelled(self.cancelled_text, self.log.text())

    def step(self, n: int, *, cancellable: bool = True) -> None:
        if cancellable:
            self.check()
        text = self.steps[n - 1]
        self.log.add(f"Step {n} of {len(self.steps)}: {text}")
        if self.progress is not None:
            try:
                self.progress(self.offset + n - 1, self.total, self.prefix + text)
            except Exception:                                 # the window's problem must never break a build
                log.exception("progress callback failed")

    def done(self) -> None:
        if self.progress is not None:
            try:
                self.progress(self.offset + len(self.steps), self.total, self.prefix + "Done")
            except Exception:
                log.exception("progress callback failed")


def _error(job: _Job, message: str) -> BuildError:
    job.log.add("Stopped: " + message)
    return BuildError(message, job.log.text())


# --- staging and publishing -------------------------------------------------------------------------

def _new_staging(shipments: Path) -> Path:
    shipments.mkdir(parents=True, exist_ok=True)
    _remove_stale_staging(shipments)
    while True:
        path = shipments / (STAGING_PREFIX + secrets.token_hex(6))
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue


def _remove_stale_staging(shipments: Path, older_than: float = STALE_STAGING_S) -> None:
    """Remove staging folders a crash or power cut left behind (they can hold a Wi-Fi password and a licence)."""
    now = time.time()
    for path in shipments.glob(STAGING_PREFIX + "*"):
        try:
            if path.is_dir() and not path.is_symlink() and now - path.stat().st_mtime > older_than:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def _remove(path: Path | None) -> None:
    if path is not None and path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _publish(src: Path, shipments: Path, base_name: str, tries: int = 6) -> Path:
    """Rename the finished folder to `<Shipments>/<base_name>`, or `<base_name> (2)`, `(3)`... when taken. A rename
    on one drive is atomic: the folder appears complete or not at all. A busy file (antivirus scanning the new
    installer) gets a few retries."""
    for n in range(1, 1000):
        dest = shipments / (base_name if n == 1 else f"{base_name} ({n})")
        if dest.exists() or dest.is_symlink():
            continue
        for attempt in range(tries):
            try:
                os.rename(src, dest)
                return dest
            except OSError as exc:
                if dest.exists() or dest.is_symlink():
                    break                                   # taken meanwhile: the next name
                if not isinstance(exc, PermissionError) or attempt == tries - 1:
                    raise
                time.sleep(0.5)
    raise OSError("no free package folder name")


def _unpublish(final: Path, staging: Path) -> None:
    """Take a published folder back out (rename into staging, removed with it), so no half package is left."""
    try:
        os.rename(final, staging / "taken-back")
    except OSError:
        shutil.rmtree(final, ignore_errors=True)


def _copy(src: Path, dest: Path, cancel: threading.Event | None, chunk: int = 4 * 1024 * 1024) -> None:
    with open(src, "rb") as fin, open(dest, "wb") as fout:
        while True:
            if cancel is not None and cancel.is_set():
                break
            data = fin.read(chunk)
            if not data:
                break
            fout.write(data)


def _record(profile: CafeProfile, store: ProfileStore, entry: HistoryEntry, final: Path, staging: Path,
            job: _Job) -> None:
    """Append the history entry and save the profile; if the save fails, take the package back out."""
    updated = profile.model_copy(deep=True)
    updated.history.append(entry)
    try:
        store.save(updated)
    except Exception as exc:
        if not isinstance(exc, (ProfileError, OSError)):
            job.log.add(traceback.format_exc())
        if not _recorded(store, profile.cafe_id, entry.licence_id):
            _unpublish(final, staging)
            raise _error(job, NOT_RECORDED) from None
        # the new file was written (only removing a renamed cafe's old file failed): the package stays with it
        job.log.add(f"Note: {type(exc).__name__}: {exc}")
    profile.history.append(entry)
    job.log.add(f"Recorded in the history: licence {entry.licence_id}, number {entry.seq}, folder {entry.package}")


def _recorded(store: ProfileStore, cafe_id: str, licence_id: str) -> bool:
    """True when a saved profile of this cafe already holds that licence in its history."""
    try:
        return any(e.profile is not None and e.profile.cafe_id == cafe_id
                   and any(h.licence_id == licence_id for h in e.profile.history) for e in store.list())
    except Exception:
        return False


# --- checks ------------------------------------------------------------------------------------------

def _private_needles(keys: Keys) -> list[bytes]:
    """The private key as it could appear in a file: raw bytes and the PEM body."""
    raw = keys.private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pem = keys.private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    body = b"".join(line for line in pem.splitlines() if line and not line.startswith(b"-----"))
    b64 = base64.b64encode(raw)[:43]                       # 43 characters: the same with or without "="
    return [raw, raw.hex().encode(), raw.hex().upper().encode(), body, b64, base64.urlsafe_b64encode(raw)[:43]]


def _file_contains(path: Path, needles: list[bytes], chunk: int = 4 * 1024 * 1024) -> bool:
    overlap = max(len(n) for n in needles) - 1
    tail = b""
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                return False
            window = tail + data
            if any(n in window for n in needles):
                return True
            tail = window[-overlap:] if overlap > 0 else b""


def _trusted(settings: FactorySettings) -> tuple[bytes, ...]:
    """The keys the program built from this source will trust (the file build.ps1 compiles, read now)."""
    return keys_mod.read_trusted_keys(settings.repo_root / keys_mod.PUBKEY_MODULE)


def _load_keys(settings: FactorySettings, keys: Keys | None) -> Keys:
    return keys if keys is not None else keys_mod.load_private(settings.keys_dir)


def video_source(settings: FactorySettings, variant: str) -> Path:
    return settings.video_dir / VIDEO_FILES[variant]


def video_problem(settings: FactorySettings, variant: str) -> str | None:
    """VIDEO_MISSING when the variant's guide video isn't there (or is empty), else None."""
    try:
        path = video_source(settings, variant)
        if path.is_file() and path.stat().st_size > 0:
            return None
    except OSError:
        pass
    return VIDEO_MISSING


def _check_common(profile: CafeProfile, settings: FactorySettings, store: ProfileStore, keys: Keys | None,
                  job: _Job) -> Keys:
    problems = settings.problems() + [m for _, m in store.problems(profile)]
    if problems:
        raise _error(job, "Fix these first:\n" + "\n".join(f"- {m}" for m in dict.fromkeys(problems)))
    keys = _load_keys(settings, keys)
    if keys_mod.is_inside(keys.folder, settings.shipments):
        raise _error(job, "Your signing key is inside the Shipments folder, which is shared and shipped. Choose "
                          "another Shipments folder in Settings.")
    if not keys_mod.is_trusted(keys, _trusted(settings)):
        raise _error(job, KEY_NOT_TRUSTED)
    job.log.add(f"Signing key {keys.fingerprint} is known to this build.")
    docs.find_edge(settings.edge)
    return keys


def _scan_unbranded(texts: dict[str, str], names: Iterable[str], code: str, job: _Job) -> None:
    """Spec 2.5: an unbranded package names the company nowhere in its generated files or file names."""
    hits: list[str] = []
    for name in names:
        hits += [f"{name} (file name)" for _ in docs.vendor_mark_hits(name)[:1]]
    for name, text in texts.items():
        hits += [f"{name}: ...{h}..." for h in docs.vendor_mark_hits(text, ignore=[code])]
    if hits:
        job.log.add("Company name found in the unbranded package:\n" + "\n".join(hits))
        raise _error(job, f"This unbranded package still mentions {brand.COMPANY}, so it wasn't saved. Show "
                          "details says where.")


def _check_files(folder: Path, expected: dict[str, bytes | None], keys: Keys, job: _Job) -> None:
    """Exactly the expected files, each non-empty (and starting with the given bytes), none holding the key."""
    present = {p.name for p in folder.iterdir()}
    if present != set(expected):
        missing, extra = set(expected) - present, present - set(expected)
        job.log.add(f"Missing: {sorted(missing)}; not expected: {sorted(extra)}")
        raise _error(job, "The package isn't complete, so it wasn't saved. Build again.")
    needles = _private_needles(keys)
    for name, magic in expected.items():
        path = folder / name
        try:
            size = path.stat().st_size if path.is_file() else 0
            with open(path, "rb") as f:
                head = f.read(8)
        except OSError:
            size, head = 0, b""
        if size == 0 or (magic is not None and not head.startswith(magic)):
            raise _error(job, f'"{name}" in the package is empty or damaged, so the package wasn\'t saved. '
                              "Build again.")
        if _file_contains(path, needles):
            raise _error(job, "The package held part of the signing key, so it was deleted. Nothing was saved.")


def _check_code(code: str, issued: Issued, profile: CafeProfile, keys: Keys, trusted: tuple[bytes, ...],
                job: _Job) -> licence.Licence:
    try:
        lic = licence.verify(code, keys=(keys.public,))
    except licence.LicenceError:
        raise _error(job, "The licence in the package didn't pass its check, so the package wasn't saved. "
                          "Build again.") from None
    p = lic.payload
    if (p != issued.payload or p.cafe_id != profile.cafe_id or p.rigs != profile.rigs
            or p.variant != profile.variant):
        job.log.add(f"Licence read back: cafe {p.cafe_id}, {p.rigs} rigs, {p.variant}; expected cafe "
                    f"{profile.cafe_id}, {profile.rigs} rigs, {profile.variant}.")
        raise _error(job, "The licence in the package doesn't match this cafe, so the package wasn't saved. "
                          "Build again.")
    if not keys_mod.is_trusted(keys, trusted):
        raise _error(job, KEY_NOT_TRUSTED)
    return lic


# --- results -------------------------------------------------------------------------------------------

@dataclass
class BuildResult:
    path: Path                       # the package folder: the app opens it
    code: str
    licence_id: str
    seq: int
    pitwall_version: str
    entry: HistoryEntry
    details: str = ""


@dataclass
class RebuildRow:
    cafe: str
    status: Literal["ok", "failed", "skipped"]
    message: str
    package: Path | None = None
    details: str = ""


@dataclass
class UpgradeResult:
    code: str
    pdf_path: Path
    folder: Path
    licence_id: str
    seq: int
    price_inr: int
    entry: HistoryEntry
    details: str = ""


# --- build -----------------------------------------------------------------------------------------------

def build_package(profile: CafeProfile, settings: FactorySettings, runner: Runner | None = None,
                  keys: Keys | None = None, cancel: threading.Event | None = None, progress: Progress | None = None,
                  *, store: ProfileStore | None = None, today: dt.date | None = None,
                  kind: Literal["build", "rebuild"] = "build", _job: _Job | None = None) -> BuildResult:
    """Build one cafe's package (spec 2.5). Returns the package folder; raises BuildError / BuildCancelled with
    nothing left behind and no history appended. On success the history entry is appended to `profile` and the
    profile is saved in the store."""
    runner = runner or Runner()
    store = store or settings.store
    day = today or dt.date.today()
    job = _job or _Job(BUILD_STEPS, cancel, progress, BuildLog(), CANCELLED)
    staging: Path | None = None
    try:
        # 1. Everything that can be checked first, so nothing is issued or compiled for a build that can't finish.
        job.step(1)
        job.log.add(f"Cafe {profile.name.strip()!r} ({profile.cafe_id}), {profile.rigs} rigs, {profile.variant}.")
        keys = _check_common(profile, settings, store, keys, job)
        video = video_problem(settings, profile.variant)
        if video:
            raise _error(job, video)
        if not (settings.repo_root / BUILD_SCRIPT).is_file():
            raise _error(job, f"The program's build files aren't next to this factory ({BUILD_SCRIPT} is "
                              "missing), so no installer can be made.")

        # 2. The program (build.ps1 -InstallerOnly reuses it when its stamp matches, else builds it first).
        job.step(2)
        before = read_stamp(settings)
        if before and before.get("version") == __version__:
            job.log.add(f"The program for version {__version__} is built (commit {before.get('commit')}); "
                        "the installer script rebuilds it if the source changed since.")
        else:
            job.log.add(f"The program for version {__version__} isn't built yet: it is built first, which takes "
                        "several minutes.")

        # 3. The licence.
        job.step(3)
        staging = _new_staging(settings.shipments)
        issued = issue(profile, keys, issued=day, logo_dir=store.logo_dir)
        job.log.add(f"Licence {issued.payload.licence_id}, number {issued.payload.seq}.")

        # 4. Bake the profile and compile the installer.
        job.step(4)
        baked, package, work = staging / "profile", staging / "package", staging / "work"
        for folder in (baked, package, work):
            folder.mkdir()
        bake(profile, issued, store, baked)
        try:
            load_baked(baked)                     # the hub's own check, before a minute of compiling
        except ProvisionError as exc:
            job.log.add(f"Baked files refused: {exc}")
            raise _error(job, "The cafe's details for the installer didn't pass their check. Check every tab "
                              "and build again.") from None
        installer_name = profile.installer_name()
        version = compile_installer(profile, settings, runner, baked, package / installer_name, job)

        # 5. The PDFs.
        job.step(5)
        guide = docs.render_html("guide", profile, issued, logo_dir=store.logo_dir, installer_name=installer_name)
        cert = docs.render_html("certificate", profile, issued, logo_dir=store.logo_dir)
        pages = {"guide.html": guide, "certificate.html": cert}
        for (page, text), pdf in zip(pages.items(), (profile.guide_pdf_name(), profile.certificate_pdf_name())):
            job.check()
            (work / page).write_text(text, encoding="utf-8")
            docs.html_to_pdf(work / page, package / pdf, edge=settings.edge, runner=runner.edge)
            job.log.add(f"Made {pdf}.")

        # 6. The video and README.
        job.step(6)
        _copy(video_source(settings, profile.variant), package / docs.VIDEO_NAME, cancel)
        job.check()
        readme = docs.render_readme(profile, issued, installer_name=installer_name)
        with open(package / docs.README_NAME, "w", encoding="utf-8", newline="") as f:
            f.write(readme)

        # 7. Verify.
        job.step(7)
        verify_package(profile, issued, keys, _trusted(settings), baked, package, work, job)

        # 8. Into place, atomically.
        job.step(8)
        final = _publish(package, settings.shipments, profile.package_folder_name(day))
        job.log.add(f"Saved as {final}.")

        # 9. History (no cancel from here: the package is in place and must be recorded, or taken back out).
        job.step(9, cancellable=False)
        p = issued.payload
        entry = HistoryEntry(kind=kind, pitwall_version=version, licence_id=p.licence_id, seq=p.seq, date=day,
                             price_inr=profile.price_inr, package=final.name, rigs=p.rigs, games=list(p.games),
                             features=list(p.features), variant=p.variant)
        _record(profile, store, entry, final, staging, job)
        if _job is None:
            job.done()
        return BuildResult(path=final, code=issued.code, licence_id=p.licence_id, seq=p.seq,
                           pitwall_version=version, entry=entry, details=job.log.text())
    except BuildError:
        raise
    except (IssueError, DocsError, ProfileError, KeysError) as exc:
        raise _error(job, str(exc)) from None
    except OSError as exc:
        job.log.add(f"{type(exc).__name__}: {exc}")
        raise _error(job, WRITE_FAILED) from None
    except Exception:
        job.log.add(traceback.format_exc())
        raise _error(job, UNEXPECTED) from None
    finally:
        _remove(staging)


def bake(profile: CafeProfile, issued: Issued, store: ProfileStore, folder: Path) -> None:
    """The installer's profile folder (spec 2.4): profile.json, the logo and licence.txt."""
    text = json.dumps(profile.baked_profile(), indent=2, ensure_ascii=False) + "\n"
    (folder / PROFILE_FILE).write_bytes(text.encode("utf-8"))
    store.copy_logo(profile, folder)
    with open(folder / LICENCE_TXT, "w", encoding="utf-8", newline="\n") as f:
        f.write(issued.code + "\n")


_HINTS = (
    ("Inno Setup 6 not found", "Inno Setup isn't installed on this PC. Install Inno Setup 6, then build again."),
    (".venv-build", "The build tools aren't set up on this PC. Follow \"Building the installer\" in the README, "
                    "then build again."),
    ("npm", "The TV screen couldn't be built. Check Node.js is installed, then build again."),
)


def compile_installer(profile: CafeProfile, settings: FactorySettings, runner: Runner, baked: Path, dest: Path,
                      job: _Job) -> str:
    """Run build.ps1 for this cafe and move the installer it makes to `dest`. Returns the program's version."""
    produced = settings.repo_root / "dist" / profile.installer_name()
    produced.unlink(missing_ok=True)                 # never mistake an older build's installer for this one
    args = build_command(settings, baked, profile.slug(), profile.variant)
    job.log.add("Running the installer build (" + " ".join(args[4:6]) + " ...).")
    try:
        try:
            result = runner.run(args, cwd=settings.repo_root, timeout=BUILD_TIMEOUT_S, cancel=job.cancel)
        except OSError as exc:
            job.log.add(f"{type(exc).__name__}: {exc}")
            raise _error(job, "Windows PowerShell couldn't be started, so no installer was made.") from None
        job.log.output("installer build", result.output)
        if result.stopped == "cancelled":
            job.check()
            raise BuildCancelled(job.cancelled_text, job.log.text())
        if result.stopped == "timeout":
            raise _error(job, "Making the installer took too long, so it was stopped. Try again.")
        if result.returncode != 0:
            for needle, message in _HINTS:
                if needle in result.output:
                    raise _error(job, message)
            raise _error(job, "The installer couldn't be made. Show details has what went wrong.")
        if not produced.is_file():
            raise _error(job, "The installer build finished but no installer was made. Show details has what "
                              "happened.")
        stamp = read_stamp(settings)
        if stamp is None or stamp.get("version") != __version__:
            job.log.add(f"Program stamp after the build: {stamp!r}")
            raise _error(job, f"The program wasn't built for version {__version__}, so no package was made. Build "
                              "again.")
        shutil.copyfile(produced, dest)
    finally:
        produced.unlink(missing_ok=True)     # the only copy holding the licence is the package's
    job.log.add(f"Installer made with the program version {stamp['version']} (commit {stamp.get('commit')}).")
    return str(stamp["version"])


def verify_package(profile: CafeProfile, issued: Issued, keys: Keys, trusted: tuple[bytes, ...], baked: Path,
                   package: Path, work: Path, job: _Job) -> None:
    """Spec 2.5 step 7: the baked licence re-read and verified, the cafe, rigs and variant compared, every file
    there and non-empty, nothing holding the key, and an unbranded package free of the company's name."""
    try:
        read_back = load_baked(baked)
    except ProvisionError as exc:
        job.log.add(f"Baked files refused: {exc}")
        raise _error(job, "The cafe's details in the installer didn't pass their check, so the package wasn't "
                          "saved. Build again.") from None
    bp = read_back.profile
    if bp.cafe_id != profile.cafe_id or bp.rigs != profile.rigs or bp.variant != profile.variant:
        raise _error(job, "The cafe's details in the installer don't match this cafe, so the package wasn't "
                          "saved. Build again.")
    try:
        code = (baked / LICENCE_TXT).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        code = ""
    _check_code(code, issued, profile, keys, trusted, job)

    expected: dict[str, bytes | None] = {
        profile.installer_name(): b"MZ",
        profile.guide_pdf_name(): b"%PDF-",
        profile.certificate_pdf_name(): b"%PDF-",
        docs.VIDEO_NAME: None,
        docs.README_NAME: None,
    }
    _check_files(package, expected, keys, job)
    for name in os.listdir(baked):
        if _file_contains(baked / name, _private_needles(keys)):
            raise _error(job, "The installer's files held part of the signing key, so nothing was saved.")

    if profile.variant == "unbranded":
        texts = {docs.README_NAME: (package / docs.README_NAME).read_text(encoding="utf-8"),
                 PROFILE_FILE: (baked / PROFILE_FILE).read_text(encoding="utf-8")}
        texts.update({p.name: p.read_text(encoding="utf-8") for p in sorted(work.glob("*.html"))})
        _scan_unbranded(texts, list(expected), issued.code, job)
    job.log.add("The package passed every check.")


# --- rebuild all -------------------------------------------------------------------------------------------

def _licensed(features: Iterable[str]) -> set[str]:
    return set(features) - set(SAFETY_FLAGS)


def changed_since(profile: CafeProfile, entry: HistoryEntry) -> bool:
    """True when the profile's rigs, games, features or variant differ from what `entry`'s licence covered."""
    if entry.rigs is None:
        return False                                  # an old entry that didn't record them: nothing to compare
    return (profile.rigs != entry.rigs or set(profile.games) != set(entry.games)
            or _licensed(profile.features_on()) != _licensed(entry.features)
            or (entry.variant is not None and entry.variant != profile.variant))


def latest_entry(profile: CafeProfile) -> HistoryEntry | None:
    return max(profile.history, key=lambda h: h.seq) if profile.history else None


def rebuild_all(store: ProfileStore, settings: FactorySettings, runner: Runner | None = None,
                keys: Keys | None = None, cancel: threading.Event | None = None, progress: Progress | None = None,
                *, today: dt.date | None = None) -> list[RebuildRow]:
    """Rebuild every built cafe's package against the current version (spec 2.5): a new licence with the same
    entitlements and seq + 1 each. Goes on past a failing cafe; returns one row per profile for the summary.
    A cafe never built is skipped; one whose rigs, games, features or branding changed since its last licence
    fails (an upgrade or a new build is a sale, not a rebuild)."""
    runner = runner or Runner()
    try:
        keys = _load_keys(settings, keys)
    except KeysError as exc:
        raise BuildError(str(exc)) from None
    entries = store.list()
    total = max(1, len(entries)) * len(BUILD_STEPS)
    rows: list[RebuildRow] = []
    for i, entry in enumerate(entries):
        title = entry.title
        if cancel is not None and cancel.is_set():
            rows.append(RebuildRow(title, "skipped", "Cancelled."))
            continue
        p = entry.profile
        if p is None:
            rows.append(RebuildRow(title, "failed", entry.error or "This cafe's file can't be opened."))
            continue
        last = latest_entry(p)
        if last is None:
            rows.append(RebuildRow(title, "skipped", "Not built yet. Use Build package for this cafe."))
            continue
        if changed_since(p, last):
            rows.append(RebuildRow(title, "failed", "This cafe's rigs, games, features or branding changed since "
                                                    "its last licence. Use Issue upgrade or Build package for it."))
            continue
        job = _Job(BUILD_STEPS, cancel, progress, BuildLog(), CANCELLED, offset=i * len(BUILD_STEPS),
                   total=total, prefix=f"{title}: ")
        try:
            result = build_package(p, settings, runner, keys, cancel, progress, store=store, today=today,
                                   kind="rebuild", _job=job)
        except BuildCancelled as exc:
            rows.append(RebuildRow(title, "skipped", "Cancelled.", details=exc.details))
        except BuildError as exc:
            rows.append(RebuildRow(title, "failed", exc.message, details=exc.details))
        else:
            rows.append(RebuildRow(title, "ok", "Built.", result.path, result.details))
    if progress is not None:
        try:
            progress(total, total, "Done")
        except Exception:
            log.exception("progress callback failed")
    return rows


# --- issue upgrade -----------------------------------------------------------------------------------------

def upgrade_pdf_name(profile: CafeProfile) -> str:
    return f"Upgrade certificate - {safe_file_name(profile.name, profile.slug())}.pdf"


def code_file_name(profile: CafeProfile) -> str:
    return f"Licence code - {safe_file_name(profile.name, profile.slug())}.txt"


def code_text(profile: CafeProfile, code: str) -> str:
    """The small text file with the new code, for copying into a message to the cafe (Windows line endings)."""
    lines = [f"New licence code for {' '.join(profile.name.split())}", "",
             "On the owner page, find the Licence card, paste this code into the \"Enter new code\" box and press",
             "\"Use this code\". There is no reinstall.", "", code]
    return "\r\n".join(lines) + "\r\n"


def upgrade_plan(profile: CafeProfile, price_inr: int | None) -> tuple[HistoryEntry, int]:
    """(the licence it upgrades from, the price) or ProfileError with a plain message."""
    prev = docs.previous_entry(profile, profile.next_seq())
    if prev is None:
        raise ProfileError("This cafe has no earlier licence on record, so there is nothing to upgrade from. "
                           "Build a package instead.")
    if prev.variant is not None and prev.variant != profile.variant:
        raise ProfileError("The branding changed since the last licence. Build a new package instead.")
    old_games, old_features = set(prev.games), _licensed(prev.features)
    new_features = _licensed(profile.features_on())
    if profile.rigs < prev.rigs or old_games - set(profile.games) or old_features - new_features:
        raise ProfileError("This change also takes away rigs, games or features the cafe already has. A licence "
                           "is forever, so put them back first.")
    more_rigs = profile.rigs - prev.rigs
    more = set(profile.games) - old_games or new_features - old_features
    if not more_rigs and not more:
        raise ProfileError("Nothing was added since the last licence. Change the rigs, games or features first.")
    if price_inr is None:
        if profile.variant != "9t7" or more:
            raise ProfileError("Enter the price of the add-ons.")
        price_inr = pricing.upgrade_price(prev.rigs, profile.rigs)
    if isinstance(price_inr, bool) or not isinstance(price_inr, int) or price_inr < 0:
        raise ProfileError("The price must be a whole number of rupees, 0 or more.")
    return prev, price_inr


def issue_upgrade(profile: CafeProfile, settings: FactorySettings, keys: Keys | None = None,
                  runner: Runner | None = None, price_inr: int | None = None, cancel: threading.Event | None = None,
                  progress: Progress | None = None, *, store: ProfileStore | None = None,
                  today: dt.date | None = None) -> UpgradeResult:
    """A new licence code (seq + 1) for the add-ons in the profile, with an upgrade certificate listing only those
    (spec 2.5). Written atomically to `<Shipments>/<Cafe> (<date>) upgrade/` (the PDF and a text file with the
    code); the installer isn't rebuilt. `price_inr` None = the rigs' list price (9t7, rigs only)."""
    runner = runner or Runner()
    store = store or settings.store
    day = today or dt.date.today()
    job = _Job(UPGRADE_STEPS, cancel, progress, BuildLog(), UPGRADE_CANCELLED)
    staging: Path | None = None
    try:
        job.step(1)
        keys = _check_common(profile, settings, store, keys, job)
        prev, price = upgrade_plan(profile, price_inr)
        job.log.add(f"Upgrade from licence number {prev.seq} ({prev.rigs} rigs) for ₹{price}.")

        job.step(2)
        staging = _new_staging(settings.shipments)
        issued = issue(profile, keys, issued=day, logo_dir=store.logo_dir)
        job.log.add(f"Licence {issued.payload.licence_id}, number {issued.payload.seq}.")

        job.step(3)
        package, work = staging / "package", staging / "work"
        package.mkdir()
        work.mkdir()
        page = docs.render_html("upgrade_certificate", profile, issued, logo_dir=store.logo_dir, previous=prev,
                                price_inr=price)
        (work / "upgrade_certificate.html").write_text(page, encoding="utf-8")
        pdf_name, txt_name = upgrade_pdf_name(profile), code_file_name(profile)
        docs.html_to_pdf(work / "upgrade_certificate.html", package / pdf_name, edge=settings.edge,
                         runner=runner.edge)
        txt = code_text(profile, issued.code)
        with open(package / txt_name, "w", encoding="utf-8", newline="") as f:
            f.write(txt)

        job.step(4)
        _check_code(issued.code, issued, profile, keys, _trusted(settings), job)
        _check_files(package, {pdf_name: b"%PDF-", txt_name: None}, keys, job)
        if profile.variant == "unbranded":
            _scan_unbranded({"upgrade_certificate.html": page, txt_name: txt}, [pdf_name, txt_name], issued.code,
                            job)

        job.step(5)
        final = _publish(package, settings.shipments, f"{profile.package_folder_name(day)} upgrade")
        job.log.add(f"Saved as {final}.")

        job.step(6, cancellable=False)
        p = issued.payload
        entry = HistoryEntry(kind="upgrade", pitwall_version=__version__, licence_id=p.licence_id, seq=p.seq,
                             date=day, price_inr=price, package=final.name, rigs=p.rigs, games=list(p.games),
                             features=list(p.features), variant=p.variant)
        _record(profile, store, entry, final, staging, job)
        job.done()
        return UpgradeResult(code=issued.code, pdf_path=final / pdf_name, folder=final, licence_id=p.licence_id,
                             seq=p.seq, price_inr=price, entry=entry, details=job.log.text())
    except BuildError:
        raise
    except (IssueError, DocsError, ProfileError, KeysError) as exc:
        raise _error(job, str(exc)) from None
    except OSError as exc:
        job.log.add(f"{type(exc).__name__}: {exc}")
        raise _error(job, WRITE_FAILED) from None
    except Exception:
        job.log.add(traceback.format_exc())
        raise _error(job, UNEXPECTED) from None
    finally:
        _remove(staging)
