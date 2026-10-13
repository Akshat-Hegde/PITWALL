"""Nightly backups: a consistent copy of the lap database, settings, branding and hub.toml; keep the last N."""

from __future__ import annotations

import datetime as dt
import socket
import sqlite3
import zipfile

from fastapi.testclient import TestClient

from simtelemetry.__main__ import main
from simtelemetry.api.app import create_app
from simtelemetry.core.backup import last_backup, make_backup, prune, restore

from test_drivers import make_hub


def _db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE laps (id INTEGER PRIMARY KEY, ms INTEGER)")
    con.execute("INSERT INTO laps (ms) VALUES (88000)")
    con.commit()
    return con


def test_backup_contents_and_restore(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    con = _db(data / "laps.db")                      # left open: the hub is running while it backs up
    (data / "settings.json").write_text('{"name": "Lap Lab"}', encoding="utf-8")
    (data / "setup-code.txt").write_text("SECRET", encoding="utf-8")
    (data / "branding").mkdir()
    (data / "branding" / "logo.png").write_bytes(b"png")
    cfg = tmp_path / "hub.toml"
    cfg.write_text('[cafe]\nname = "Lap Lab"\n', encoding="utf-8")
    z = make_backup(data, cfg, tmp_path / "backups", dt.datetime(2026, 10, 13, 4, 0))
    assert z.name == "pitwall-20261013-0400.zip"
    names = set(zipfile.ZipFile(z).namelist())
    assert {"laps.db", "settings.json", "branding/logo.png", "hub.toml", "manifest.json"} <= names
    assert "setup-code.txt" not in names             # a secret that must die after setup
    con.close()
    (data / "laps.db").unlink()
    (data / "settings.json").unlink()
    restore(z, data, cfg)
    assert sqlite3.connect(data / "laps.db").execute("SELECT ms FROM laps").fetchone() == (88000,)
    assert (data / "settings.json").read_text(encoding="utf-8") == '{"name": "Lap Lab"}'
    assert last_backup(tmp_path / "backups")["file"] == z.name


def test_prune_keeps_newest(tmp_path):
    for day in range(1, 6):
        (tmp_path / f"pitwall-202610{day:02d}-0400.zip").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("keep me")
    removed = prune(tmp_path, keep=2)
    assert [p.name for p in removed] == [f"pitwall-202610{d:02d}-0400.zip" for d in (1, 2, 3)]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.txt", "pitwall-20261004-0400.zip",
                                                          "pitwall-20261005-0400.zip"]


def test_next_backup_at():
    from simtelemetry.hub import next_backup_at
    assert next_backup_at(dt.datetime(2026, 10, 13, 3, 59), 4) == dt.datetime(2026, 10, 13, 4, 0)
    assert next_backup_at(dt.datetime(2026, 10, 13, 4, 0), 4) == dt.datetime(2026, 10, 14, 4, 0)


def test_owner_backup_endpoints(tmp_path):
    bk = tmp_path / "bk"
    hub = make_hub(tmp_path, owner={"pin": "2468"}, backup={"directory": bk})
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    auth = {"X-Owner-Pin": "2468"}
    assert client.get("/api/owner/backup").status_code == 401
    assert client.post("/api/owner/backup").status_code == 401
    first = client.get("/api/owner/backup", headers=auth).json()
    assert first["last"] is None and first["directory"] == str(bk)
    done = client.post("/api/owner/backup", headers=auth)
    assert done.status_code == 200 and done.json()["last"]["file"].endswith(".zip")
    assert client.get("/api/owner/backup", headers=auth).json()["last"]["bytes"] > 0
    assert len(list(bk.glob("*.zip"))) == 1


def test_backup_and_restore_commands(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    _db(data / "laps.db").close()
    bk = tmp_path / "bk"
    toml = tmp_path / "hub.toml"
    toml.write_text(f'data_dir = "{data.as_posix()}"\n[backup]\ndirectory = "{bk.as_posix()}"\n', encoding="utf-8")
    assert main(["backup", "--config", str(toml)]) == 0
    z = next(bk.glob("*.zip"))
    assert str(z) in capsys.readouterr().out
    (data / "laps.db").unlink()
    with socket.socket() as s:                       # something answers on the HTTP port: the hub is running
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert main(["restore", str(z), "--config", str(toml), "--http-port", str(port)]) == 2
    assert not (data / "laps.db").exists()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert main(["restore", str(z), "--config", str(toml), "--http-port", str(free)]) == 0
    assert (data / "laps.db").exists()
