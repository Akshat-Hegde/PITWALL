"""C2: the licence on the cafe PC (<data>/licence.txt), the owner page's Licence card and code entry, backups."""

from __future__ import annotations

import datetime as dt
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from simtelemetry import licence
from simtelemetry.api.app import create_app
from simtelemetry.core.backup import BACKED_UP_FILES, make_backup, restore
from simtelemetry.core.feed import FeedBuilder, FeedConnection
from simtelemetry.licence import (ALREADY_INSTALLED, DAMAGED, FALLBACK, INVALID, LICENCE_FILE, NO_LICENCE, OLDER,
                                  OTHER_CAFE, LicenceError, read_file, write_file)

from licence_helpers import CAFE_ID, Signer, trust
from test_drivers import make_hub

OWNER = {"X-Owner-Pin": "2468"}


@pytest.fixture
def signer(monkeypatch):
    return trust(monkeypatch)


def owner_client(tmp_path, **cfg):
    hub = make_hub(tmp_path, owner={"pin": "2468"}, **cfg)
    return hub, TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))


# --- the file ------------------------------------------------------------------------------------

def test_file_round_trip_is_atomic_and_tolerates_notepad(tmp_path, signer):
    code = signer.code()
    write_file(tmp_path, licence.verify(code))
    assert (tmp_path / LICENCE_FILE).read_text(encoding="utf-8") == code + "\n"
    assert not list(tmp_path.glob("*.tmp"))
    assert read_file(tmp_path).payload.cafe_id == CAFE_ID
    # Saved by hand in Notepad: a BOM, CRLF and the code wrapped over two lines still read.
    (tmp_path / LICENCE_FILE).write_bytes(b"\xef\xbb\xbf" + (code[:40] + "\r\n" + code[40:] + "\r\n").encode())
    assert read_file(tmp_path).payload.seq == 1


def test_missing_file_is_none_and_damaged_file_raises(tmp_path, signer):
    assert read_file(tmp_path) is None
    for body in (b"", b"\xff\xfe\x00garbage", signer.code()[:-5].encode(), Signer().code().encode()):
        (tmp_path / LICENCE_FILE).write_bytes(body)
        with pytest.raises(LicenceError):
            read_file(tmp_path)


# --- loading at start ----------------------------------------------------------------------------

def test_no_licence_runs_on_the_fallback_and_warns_staff_not_the_tv(tmp_path, signer):
    hub = make_hub(tmp_path)
    assert hub.entitlements is FALLBACK and hub.admin_warnings() == []      # tests and replays: quiet fallback
    assert hub.load_licence() is FALLBACK
    assert hub.admin_warnings() == [{"code": "licence_missing", "rig_id": None, "message": NO_LICENCE}]
    assert hub.licence_summary() == NO_LICENCE
    status = FeedBuilder(hub).status(time.monotonic())
    assert all("licence" not in w["code"] for w in status["warnings"])       # the TV is unaffected
    hub.load_licence(warn_missing=False)                                       # the demo
    assert hub.entitlements is FALLBACK and hub.admin_warnings() == []


def test_damaged_licence_runs_on_the_fallback_with_its_own_warning(tmp_path, signer):
    (tmp_path / LICENCE_FILE).write_text("PW1-this.is-not-a-licence", encoding="utf-8")
    hub = make_hub(tmp_path)
    assert hub.load_licence(warn_missing=False) is FALLBACK                   # damaged is said even in the demo
    assert [w["message"] for w in hub.admin_warnings()] == [DAMAGED]
    assert hub.admin_warnings()[0]["code"] == "licence_damaged"
    assert hub.licence_info()["summary"] == DAMAGED


def test_valid_licence_is_loaded_and_hooks_run(tmp_path, signer):
    write_file(tmp_path, licence.verify(signer.code(rigs=8)))
    hub = make_hub(tmp_path)
    seen = []
    hub.entitlement_hooks.append(seen.append)
    ent = hub.load_licence()
    assert ent.source == "licence" and ent.rigs == 8 and ent.cafe_id == CAFE_ID
    assert hub.entitlements is ent and seen == [ent] and hub.admin_warnings() == []
    assert hub.licence_summary() == "Licensed to Apex Lounge · 8 rigs · F1 25"


def test_one_rig_and_unknown_games_read_plainly(signer):
    ent = licence.entitlements_from(licence.verify(signer.code(rigs=1, games=["f1_25", "ac_evo"])))
    assert licence.summary(ent) == "Licensed to Apex Lounge · 1 rig · F1 25, ac_evo"


# --- applying a new code live --------------------------------------------------------------------

def test_new_code_applies_at_once_and_every_tv_gets_a_fresh_snapshot(tmp_path, signer):
    hub = make_hub(tmp_path)
    hub.load_licence()
    seen = []
    hub.entitlement_hooks.append(seen.append)
    conn = FeedConnection(FeedBuilder(hub))
    now = time.monotonic()
    assert conn.start(now)["seq"] == 0
    assert [m["type"] for m in conn.tick(now)][-1] == "frame"
    ent = hub.apply_licence("  " + signer.code(rigs=6) + "\n")             # pasted with spaces around it
    assert hub.entitlements is ent and ent.rigs == 6 and seen == [ent]
    assert hub.admin_warnings() == []                                       # "No licence found" is gone
    assert read_file(tmp_path).payload.rigs == 6
    msgs = conn.tick(now)
    assert [m["type"] for m in msgs] == ["snapshot"] and msgs[0]["seq"] == 2  # seq carries on
    assert [m["type"] for m in conn.tick(now)][-1] == "frame"                # then live again


def test_a_failing_hook_never_stops_the_licence_applying(tmp_path, signer):
    hub = make_hub(tmp_path)

    def broken(_):
        raise RuntimeError("boom")
    hub.entitlement_hooks.append(broken)
    assert hub.apply_licence(signer.code()).rigs == 6 and hub.feed_epoch == 1


def test_damaged_file_counts_as_no_licence_yet_so_the_owner_can_recover(tmp_path, signer):
    (tmp_path / LICENCE_FILE).write_text("rubbish", encoding="utf-8")
    hub = make_hub(tmp_path)
    hub.load_licence()
    ent = hub.apply_licence(signer.code(cafe_id="another-cafe", seq=1))
    assert ent.cafe_id == "another-cafe" and hub.licence_problem is None


def test_rules_against_the_current_licence(tmp_path, signer):
    hub = make_hub(tmp_path)
    hub.apply_licence(signer.code(seq=3, licence_id="lic-3"))
    with pytest.raises(LicenceError, match=OTHER_CAFE):
        hub.apply_licence(signer.code(cafe_id="cafe-other", seq=9))
    with pytest.raises(LicenceError, match=OLDER):
        hub.apply_licence(signer.code(seq=2, licence_id="lic-2"))
    with pytest.raises(LicenceError, match=ALREADY_INSTALLED):
        hub.apply_licence(signer.code(seq=3, licence_id="lic-3"))
    assert hub.entitlements.seq == 3 and read_file(tmp_path).payload.seq == 3   # nothing changed


def test_a_code_that_cant_be_saved_is_not_applied(tmp_path, signer, monkeypatch):
    hub = make_hub(tmp_path)

    def full_disk(*_):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(licence, "write_file", full_disk)
    with pytest.raises(LicenceError, match="couldn't be saved"):
        hub.apply_licence(signer.code())
    assert hub.entitlements is FALLBACK and hub.feed_epoch == 0


# --- the owner page API --------------------------------------------------------------------------

def test_owner_licence_api_happy_path(tmp_path, signer):
    hub, client = owner_client(tmp_path)
    hub.load_licence()
    got = client.get("/api/owner/licence", headers=OWNER).json()
    assert got["source"] == "fallback" and got["summary"] == NO_LICENCE and got["warning"] == NO_LICENCE
    assert got["rigs"] == 4 and got["games"] == ["F1 25"] and got["licence_id"] is None
    r = client.post("/api/owner/licence", json={"code": signer.code(rigs=7, licence_id="lic-7")}, headers=OWNER)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["summary"] == "Licensed to Apex Lounge · 7 rigs · F1 25"
    assert (got["licence_id"], got["seq"], got["variant"], got["warning"]) == ("lic-7", 1, "9t7", None)
    assert got["cafe_name"] == "Apex Lounge" and got["game_ids"] == ["f1_25"] and "owner" in got["features"]
    assert "code" not in got                                               # the code is never sent back
    assert client.get("/api/owner/licence", headers=OWNER).json() == got
    assert hub.entitlements.rigs == 7


@pytest.mark.parametrize("make, message", [
    (lambda s: "PW1-nonsense.nonsense", INVALID),
    (lambda s: Signer().code(seq=5), INVALID),                              # signed by someone else
    (lambda s: "", INVALID),
    (lambda s: 12345, INVALID),
    (lambda s: s.code(cafe_id="cafe-other", seq=5), OTHER_CAFE),
    (lambda s: s.code(seq=1, licence_id="lic-1"), OLDER),
    (lambda s: s.code(seq=2), ALREADY_INSTALLED),
])
def test_owner_licence_api_errors_are_plain(tmp_path, signer, make, message):
    hub, client = owner_client(tmp_path)
    hub.apply_licence(signer.code(seq=2))
    r = client.post("/api/owner/licence", json={"code": make(signer)}, headers=OWNER)
    assert r.status_code == 400 and r.json()["detail"] == message
    assert hub.entitlements.seq == 2


def test_owner_licence_api_needs_the_owner_pin_and_shares_the_lock_out(tmp_path, signer):
    hub, client = owner_client(tmp_path)
    code = signer.code()
    assert client.get("/api/owner/licence").status_code == 401
    assert client.post("/api/owner/licence", json={"code": code}).status_code == 401
    assert client.post("/api/owner/licence", json={"code": code}, headers={"X-Staff-Pin": "2468"}).status_code == 401
    for _ in range(5):
        r = client.post("/api/owner/licence", json={"code": code}, headers={"X-Owner-Pin": "0000"})
        assert r.status_code == 401
    r = client.post("/api/owner/licence", json={"code": code}, headers=OWNER)     # locked, even with the right PIN
    assert r.status_code == 429 and "Too many wrong PINs" in r.json()["detail"]
    assert client.get("/api/owner/report", headers=OWNER).status_code == 429      # the same, shared lock-out
    assert hub.entitlements is FALLBACK and not (tmp_path / LICENCE_FILE).exists()


def test_owner_licence_api_follows_the_owner_page_rules(tmp_path, signer):
    hub = make_hub(tmp_path)                                                      # no owner PIN yet
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    assert client.get("/api/owner/licence", headers=OWNER).status_code == 403
    _, off = owner_client(tmp_path / "off", features={"owner": False})
    assert off.get("/api/owner/licence", headers=OWNER).status_code == 404


def test_owner_page_has_the_licence_card_and_sets_text_safely(tmp_path):
    _, client = owner_client(tmp_path)
    html = client.get("/owner").text
    assert 'id="licence-card"' in html and "Enter new code" in html and 'id="licence-code"' in html
    script = html[html.index("function showLicence"):html.index("async function load()")]
    assert "innerHTML" not in script and "textContent" in script


# --- the setup page ------------------------------------------------------------------------------

def test_setup_page_shows_one_read_only_licence_line(tmp_path, signer):
    hub, client = owner_client(tmp_path)
    code = signer.code()
    hub.apply_licence(code)
    state = client.get("/api/setup").json()                                  # no PIN or code: still the line
    assert state["licence"] == "Licensed to Apex Lounge · 6 rigs · F1 25"
    assert code not in client.get("/api/setup").text and "lic-0001" not in client.get("/api/setup").text
    assert 'id="licence-line"' in client.get("/setup").text


# --- backups ---------------------------------------------------------------------------------------

def test_licence_is_backed_up_and_restored(tmp_path, signer):
    assert LICENCE_FILE in BACKED_UP_FILES
    data = tmp_path / "data"
    code = signer.code(rigs=6)
    write_file(data, licence.verify(code))
    z = make_backup(data, None, tmp_path / "bk", dt.datetime(2026, 11, 3, 4, 0))
    assert zipfile.ZipFile(z).read(LICENCE_FILE).decode() == code + "\n"
    (data / LICENCE_FILE).unlink()
    restore(z, data, None)
    assert read_file(data).payload.rigs == 6
    hub = make_hub(data)                                                      # the hub reads it when it starts
    assert hub.load_licence().rigs == 6


def test_restore_never_downgrades_this_cafes_licence(tmp_path, signer):
    data = tmp_path / "data"
    write_file(data, licence.verify(signer.code(seq=1, rigs=4)))
    z = make_backup(data, None, tmp_path / "bk", dt.datetime(2026, 11, 3, 4, 0))
    write_file(data, licence.verify(signer.code(seq=2, rigs=8)))             # add-on bought after the backup
    restore(z, data, None)
    assert read_file(data).payload.rigs == 8
    (data / LICENCE_FILE).write_text("rubbish", encoding="utf-8")            # damaged: the backup's is better
    restore(z, data, None)
    assert read_file(data).payload.rigs == 4
    write_file(data, licence.verify(signer.code(cafe_id="cafe-other", seq=7)))   # another cafe's: the backup wins
    restore(z, data, None)
    assert read_file(data).payload.cafe_id == CAFE_ID


# --- a real start ----------------------------------------------------------------------------------

def test_run_loads_the_licence_at_start(tmp_path, signer):
    from test_startup import ports, run_hub_briefly
    data = tmp_path / "data"
    write_file(data, licence.verify(signer.code(rigs=6)))
    code, got = run_hub_briefly(["run", "--data-dir", str(data), *ports()], ["/api/setup", "/api/staff/health"],
                                duration="10")
    assert code == 0
    assert got["/api/setup"]["licence"] == "Licensed to Apex Lounge · 6 rigs · F1 25"
    assert not [w for w in got["/api/staff/health"]["warnings"] if w["code"].startswith("licence")]
    log_text = (data / "logs" / "hub.log").read_text(encoding="utf-8")
    assert "Licence lic-0001: Licensed to Apex Lounge" in log_text and signer.code(rigs=6) not in log_text
