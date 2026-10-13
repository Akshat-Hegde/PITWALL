"""Backups: laps.db copied with SQLite's online backup (safe while the hub writes), plus settings.json,
branding/ and hub.toml, zipped as pitwall-YYYYMMDD-HHMM.zip. Restore puts them back (hub stopped).

setup-code.txt is deliberately left out: it is a secret that must die after setup.
"""

from __future__ import annotations

import datetime as dt
import json
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
    data_dir.mkdir(parents=True, exist_ok=True)
    root = data_dir.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name == "manifest.json":
                continue
            if name == "hub.toml":
                if config_path is not None:
                    config_path.parent.mkdir(parents=True, exist_ok=True)
                    config_path.write_bytes(z.read(name))
                continue
            dest = data_dir / name
            if not dest.resolve().is_relative_to(root):
                raise ValueError(f"Unsafe path in backup: {name}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)


def last_backup(target_dir: Path) -> dict[str, Any] | None:
    files = sorted(target_dir.glob(PATTERN)) if target_dir.is_dir() else []
    if not files:
        return None
    f = files[-1]
    return {"file": f.name, "at": round(f.stat().st_mtime * 1000), "bytes": f.stat().st_size}
