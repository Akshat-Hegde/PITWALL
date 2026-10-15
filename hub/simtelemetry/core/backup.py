"""Backups: laps.db copied with SQLite's online backup (safe while the hub writes), plus settings.json, rigs.json,
tv.json, checkin.json, branding/, logos/ and hub.toml, zipped as pitwall-YYYYMMDD-HHMM.zip. Restore puts them back
(hub stopped).

setup-code.txt is deliberately left out: it is a secret that must die after setup.

The owner chooses the backup folder on the owner page (a USB stick is best); it is kept in settings.json, and
hub.toml's [backup] directory is only the fallback. Problems are told in plain English (the raw error goes to the
log), and <data>/backup-status.json remembers the last good backup so the owner page and staff Health can warn
when backups have stopped.
"""

from __future__ import annotations

import datetime as dt
import errno
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from .. import __version__, brand

log = logging.getLogger(__name__)

PATTERN = f"{brand.SLUG}-*.zip"            # pitwall-20261013-0400.zip with the current name
BACKED_UP_FILES = ("settings.json", "rigs.json", "tv.json", "checkin.json")
BACKED_UP_FOLDERS = ("branding", "logos")
STATUS_FILE = "backup-status.json"
WARN_AFTER = dt.timedelta(days=2)

USB_MISSING = "The USB stick isn't plugged in (drive {drive} not found)."
NO_PERMISSION = "Windows won't let the hub write to that folder. Choose another folder."
DISK_FULL = "The backup drive is full."
GENERIC_FAILURE = "The backup couldn't be saved. Check the backup folder, then try again."
NOT_A_FOLDER = "That is a file, not a folder. Choose a folder."
WHOLE_PATH = r"Type the whole folder path, like E:\Backups."
CHECK_FOLDER = "Check the backup folder or USB stick."

_WIN_DISK_FULL = (39, 112)                 # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
_WIN_NO_DEVICE = (15, 21)                  # ERROR_INVALID_DRIVE, ERROR_NOT_READY (card reader without a card)
_WIN_DENIED = (5, 19)                      # ERROR_ACCESS_DENIED, ERROR_WRITE_PROTECT


class BackupFailed(Exception):
    """A backup (or a chosen folder) didn't work; `text` is the plain-English sentence for the owner."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


def _drive(folder: Path) -> str | None:
    """"E:" for a drive-letter path, else None (a network path, or not Windows)."""
    drive = folder.drive
    return drive.upper() if len(drive) == 2 and drive[1] == ":" else None


def drive_missing(folder: Path, exists=os.path.exists) -> str | None:
    """The drive letter when the folder is on a drive that isn't there (a USB stick that is unplugged)."""
    drive = _drive(folder)
    return drive if drive is not None and not exists(drive + "\\") else None


def plain_backup_error(exc: BaseException, folder: Path, exists=os.path.exists) -> str:
    """One plain sentence for the owner; the raw error only goes to the log."""
    drive = drive_missing(folder, exists)
    winerror = getattr(exc, "winerror", None)
    if drive is not None or winerror in _WIN_NO_DEVICE:
        return USB_MISSING.format(drive=drive or _drive(folder) or "?")
    code = getattr(exc, "errno", None)
    if (isinstance(exc, OSError) and (code == errno.ENOSPC or winerror in _WIN_DISK_FULL)) \
            or (isinstance(exc, sqlite3.Error) and "full" in str(exc).lower()):
        return DISK_FULL
    if isinstance(exc, PermissionError) or code in (errno.EACCES, errno.EPERM, errno.EROFS) \
            or winerror in _WIN_DENIED:
        return NO_PERMISSION
    if isinstance(exc, (NotADirectoryError, FileExistsError)):
        return NOT_A_FOLDER
    return GENERIC_FAILURE


def clean_folder_text(text: Any) -> str:
    """What the owner typed or pasted: trimmed, and without the quotes Explorer's "Copy as path" adds."""
    value = str(text or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def check_folder(text: Any, exists=os.path.exists) -> Path | None:
    """The folder the owner chose, created if needed and checked by writing a small file; None for "the
    default". Raises BackupFailed with a plain sentence when it can't be used."""
    value = clean_folder_text(text)
    if not value:
        return None
    if len(value) == 2 and value[1] == ":":
        value += "\\"                                      # "E:" means the top of the stick
    folder = Path(value)
    if not folder.is_absolute():
        raise BackupFailed(WHOLE_PATH)
    drive = drive_missing(folder, exists)
    if drive is not None:
        raise BackupFailed(USB_MISSING.format(drive=drive))
    probe = folder / f".{brand.SLUG}-write-test"
    try:
        if folder.exists() and not folder.is_dir():
            raise NotADirectoryError(str(folder))
        folder.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        log.warning("Can't use %s as the backup folder: %r", folder, exc)
        raise BackupFailed(plain_backup_error(exc, folder, exists)) from None
    return folder


def _days(age: dt.timedelta) -> str:
    n = age.days
    return "1 day" if n == 1 else f"{n} days"


class BackupStatus:
    """The last good backup and the last failure, kept in <data>/backup-status.json (None: in memory only)."""

    def __init__(self, path: Path | None, first_use: float | None = None, seed_last_ok: float | None = None,
                 clock=time.time) -> None:
        self._path = path
        self._clock = clock
        self.first_use: float = first_use if first_use is not None else clock()    # Unix seconds
        self.last_ok: float | None = seed_last_ok
        self.last_ok_folder: str | None = None
        self.last_error: str | None = None
        self.last_error_at: float | None = None
        data: dict[str, Any] = {}
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as exc:
                log.warning("Ignoring unreadable %s: %s", path, exc)
        if isinstance(data, dict):
            try:
                if data.get("first_use"):
                    self.first_use = min(self.first_use, float(data["first_use"]) / 1000)
                if data.get("last_ok"):
                    self.last_ok = max(self.last_ok or 0.0, float(data["last_ok"]) / 1000)
                self.last_ok_folder = data.get("last_ok_folder") or None
                if data.get("last_error"):
                    self.last_error = str(data["last_error"])
                    self.last_error_at = float(data.get("last_error_at") or 0) / 1000 or None
            except (TypeError, ValueError) as exc:
                log.warning("Ignoring bad values in %s: %s", path, exc)
        if path is not None and not path.exists():
            self._save()                                  # remember when this hub started being used

    def ok(self, folder: Path) -> None:
        self.last_ok = self._clock()
        self.last_ok_folder = str(folder)
        self.last_error = self.last_error_at = None
        self._save()

    def failed(self, text: str) -> None:
        self.last_error, self.last_error_at = text, self._clock()
        self._save()

    def warning(self) -> str | None:
        """"Last backup: 5 days ago. ..." once the last good backup is over 2 days old, or none after 2 days of
        use; else None. For the owner page and staff Health, never the TV."""
        now = dt.datetime.fromtimestamp(self._clock())
        if self.last_ok is not None:
            age = now - dt.datetime.fromtimestamp(self.last_ok)
            return f"Last backup: {_days(age)} ago. {CHECK_FOLDER}" if age > WARN_AFTER else None
        if now - dt.datetime.fromtimestamp(self.first_use) > WARN_AFTER:
            return f"No backup has been made yet. {CHECK_FOLDER}"
        return None

    def to_json(self) -> dict[str, Any]:
        ms = (lambda t: round(t * 1000) if t is not None else None)
        return {"last_ok_at": ms(self.last_ok), "last_error": self.last_error, "last_error_at": ms(self.last_error_at)}

    def _save(self) -> None:
        if self._path is None:
            return
        ms = (lambda t: round(t * 1000) if t is not None else None)
        body = {"first_use": ms(self.first_use), "last_ok": ms(self.last_ok), "last_ok_folder": self.last_ok_folder,
                "last_error": self.last_error, "last_error_at": ms(self.last_error_at)}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(body) + "\n", encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.exception("Could not save %s", self._path)


def first_use_time(data_dir: Path, now: float) -> float:
    """When this hub started being used, for a hub that has no backup-status.json yet: the lap database's
    creation time (an existing install), else now."""
    try:
        st = (data_dir / "laps.db").stat()
    except OSError:
        return now
    created = getattr(st, "st_birthtime", None) or st.st_ctime
    return min(now, created)


def last_backup_folder(data_dir: Path) -> tuple[Path, ...]:
    """The folder the last good backup went to, from backup-status.json (empty when unknown)."""
    try:
        folder = json.loads((data_dir / STATUS_FILE).read_text(encoding="utf-8")).get("last_ok_folder")
    except (OSError, ValueError, AttributeError):
        return ()
    return (Path(folder),) if isinstance(folder, str) and folder else ()


def record_backup(data_dir: Path, folder: Path, error: str | None = None) -> None:
    """For the `backup` command (another process than the hub): note the result in backup-status.json."""
    status = BackupStatus(data_dir / STATUS_FILE, first_use=first_use_time(data_dir, time.time()))
    if error is None:
        status.ok(folder)
    else:
        status.failed(error)


def make_backup(data_dir: Path, config_path: Path | None, target_dir: Path, now: dt.datetime) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / f"{brand.SLUG}-{now:%Y%m%d-%H%M}.zip"
    partial = out.with_suffix(".part")
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "laps.db"
        db = data_dir / "laps.db"
        if db.exists():
            src = sqlite3.connect(db)
            dst = sqlite3.connect(snap)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
                src.close()
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
                if snap.exists():
                    z.write(snap, "laps.db")
                for name in BACKED_UP_FILES:
                    if (data_dir / name).exists():
                        z.write(data_dir / name, name)
                for folder in BACKED_UP_FOLDERS:
                    if (data_dir / folder).is_dir():
                        for f in sorted((data_dir / folder).iterdir()):
                            if f.is_file():
                                z.write(f, f"{folder}/{f.name}")
                if config_path is not None and config_path.exists():
                    z.write(config_path, "hub.toml")
                z.writestr("manifest.json", json.dumps({"version": __version__, "at": now.isoformat()}))
            partial.replace(out)
        finally:
            partial.unlink(missing_ok=True)
    return out


def prune(target_dir: Path, keep: int) -> list[Path]:
    files = sorted(target_dir.glob(PATTERN))
    old = files[:-keep] if keep > 0 else []
    for f in old:
        f.unlink()
    return old


def restore(zip_path: Path, data_dir: Path, config_path: Path | None) -> None:
    """All or nothing: every name is checked and every file extracted to a staging folder first; only then
    are files moved into place. The previous laps.db and hub.toml are kept as *.before-restore."""
    data_dir.mkdir(parents=True, exist_ok=True)
    root = data_dir.resolve()
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n != "manifest.json" and not n.endswith("/")]
        for name in names:
            if name != "hub.toml" and not (data_dir / name).resolve().is_relative_to(root):
                raise ValueError(f"Unsafe path in backup: {name}")
        staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=data_dir.parent))
        try:
            for name in names:
                dest = staging / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
            for name in names:
                staged = staging / name
                if name == "hub.toml":
                    if config_path is not None:
                        config_path.parent.mkdir(parents=True, exist_ok=True)
                        if config_path.exists():
                            os.replace(config_path, config_path.with_name(config_path.name + ".before-restore"))
                        shutil.move(str(staged), str(config_path))
                    continue
                dest = data_dir / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if name == "laps.db":
                    if dest.exists():
                        os.replace(dest, dest.with_name("laps.db.before-restore"))
                    for stale in ("laps.db-wal", "laps.db-shm"):   # left by a crash; must not replay onto the restored file
                        (data_dir / stale).unlink(missing_ok=True)
                os.replace(staged, dest)
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def last_backup(target_dir: Path) -> dict[str, Any] | None:
    files = sorted(target_dir.glob(PATTERN)) if target_dir.is_dir() else []
    if not files:
        return None
    f = files[-1]
    return {"file": f.name, "at": round(f.stat().st_mtime * 1000), "bytes": f.stat().st_size}
