"""Renaming the product is a one-line change in brand.py."""

from __future__ import annotations

import importlib

from simtelemetry import brand, paths


def test_derived_names():
    assert brand.as_dict() == {"PRODUCT_NAME": "Pitwall", "SLUG": "pitwall", "EXE_NAME": "Pitwall",
                               "TASK_NAME": "Pitwall Hub", "MDNS_HOST": "pitwall.local", "HOME_ENV": "PITWALL_HOME"}


def test_rename_flows_into_paths(monkeypatch, tmp_path):
    import sys
    monkeypatch.setattr(brand, "PRODUCT_NAME", "Lap Line")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "PD"))
    monkeypatch.delenv(brand.HOME_ENV, raising=False)
    assert paths.home() == tmp_path / "PD" / "Lap Line"


def test_name_is_written_once():
    """No packaging file or path code spells the product name; they all read brand.py."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for rel in ["hub/simtelemetry/paths.py", "packaging/pitwall.spec", "packaging/build.ps1",
                "packaging/pitwall.iss", "packaging/pitwall-task.xml"]:
        f = root / rel
        if f.exists():                                   # later tasks create the packaging files
            body = "\n".join(l for l in f.read_text(encoding="utf-8").splitlines()
                             if not l.lstrip().startswith(("#", ";", "//")))
            assert brand.PRODUCT_NAME not in body, rel
