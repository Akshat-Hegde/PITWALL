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


def test_hub_pages_fill_in_the_product_name(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from simtelemetry.api.app import create_app
    from test_drivers import make_hub
    monkeypatch.setattr(brand, "PRODUCT_NAME", "Zed Cafe")
    client = TestClient(create_app(make_hub(tmp_path), dashboard_dir=tmp_path / "none"))
    for path in ("/staff", "/owner", "/setup"):
        r = client.get(path)
        assert r.status_code == 200 and "{{PRODUCT_NAME}}" not in r.text
    assert "Staff · Zed Cafe" in client.get("/staff").text
