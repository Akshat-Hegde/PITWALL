"""Backups: laps.db copied with SQLite's online backup (safe while the hub writes), plus settings.json,
branding/ and hub.toml, zipped as pitwall-YYYYMMDD-HHMM.zip. Restore puts them back (hub stopped).

setup-code.txt is deliberately left out: it is a secret that must die after setup.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .. import __version__, brand

PATTERN = f"{brand.SLUG}-*.zip"            # pitwall-20261013-0400.zip with the current name


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
                for name in ("settings.json", "rigs.json", "tv.json"):
                    if (data_dir / name).exists():
                        z.write(data_dir / name, name)
                branding = data_dir / "branding"
                if branding.is_dir():
                    for f in sorted(branding.iterdir()):
                        if f.is_file():
                            z.write(f, f"branding/{f.name}")
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
