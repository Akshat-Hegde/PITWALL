"""C3: what the licence decides (spec 2.3): rigs on the TV, features, games and the supplier's mark."""

from __future__ import annotations

import datetime as dt
import time

import pytest
from fastapi.testclient import TestClient

from simtelemetry import adapters, brand, licence
from simtelemetry.adapters.f1.adapter import F1Adapter
from simtelemetry.api.app import create_app
from simtelemetry.config import AppConfig
from simtelemetry.core.feed import FeedBuilder, FeedConnection, tv_message
from simtelemetry.core.laps import LapBook, LapContext
from simtelemetry.core.rigs import RigRegistry
from simtelemetry.core.store import LapStore
from simtelemetry.hub import Hub

from f1_helpers import STAFF, staff_ready
from licence_helpers import trust
from test_feed import RIG_A, RIG_B, RIG_C, driving_rig, feed, last_seen
from test_laps import lap

OWNER = {"X-Owner-Pin": "2468"}
TRACK = "F1:7"


@pytest.fixture
def signer(monkeypatch):
    return trust(monkeypatch)


def make_hub(tmp_path, adapter=None, **cfg) -> Hub:
    config = AppConfig(data_dir=tmp_path, **cfg)
    return Hub(config, adapter or F1Adapter(config.track_names), RigRegistry(config, tmp_path / "rigs.json"),
               store=LapStore(tmp_path / "laps.db"))


async def three_rigs(tmp_path, signer, rigs=2, **payload):
    """Rigs 1, 2 and 3 driving on the same track, with a licence for `rigs` of them."""
    hub = make_hub(tmp_path, owner={"pin": "2468"})
    await feed(hub, driving_rig(RIG_A) + driving_rig(RIG_B, uid=0x12, name=b"Kofi")
               + driving_rig(RIG_C, uid=0x13, name=b"Zed"))
    assert [hub.registry.get(ip).number for ip in (RIG_A, RIG_B, RIG_C)] == [1, 2, 3]
    if rigs is not None:
        hub.apply_licence(signer.code(rigs=rigs, features=list(licence.FALLBACK.features), **payload))
    return hub


def drive_lap(hub, rig, driver, n, ms):
    ctx = LapContext(rig_name=hub.rig_label(rig), driver=driver, track_key=TRACK, track_name="Silverstone",
                     session_id="s1")
    return hub.laps.update(rig, ctx, None, [lap(n, ms)])


def drivers(board):
    return [e["driver"] for e in board["entries"]]


# --- rigs ----------------------------------------------------------------------------------------

async def test_the_first_n_rig_numbers_are_licensed(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer, rigs=None)
    assert hub.tv_hidden_rigs() == frozenset() and hub.licence_rigs_warning() is None    # fallback: 4 rigs
    hub.apply_licence(signer.code(rigs=2))
    assert hub.tv_hidden_rigs() == {RIG_C}
    assert [hub.rig_licensed(ip) for ip in (RIG_A, RIG_B, RIG_C)] == [True, True, False]
    assert hub.rig_licensed("10.9.9.9")             # no rig now (laps of a forgotten rig): history, not hidden
    hub.registry.rename(RIG_A, "Rig 9")             # a name is only a name: the number stays 1
    assert hub.rig_licensed(RIG_A)


async def test_snapshot_leaves_out_rigs_beyond_the_licence(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer)
    drive_lap(hub, RIG_A, "Akshat", 2, 90_000)
    drive_lap(hub, RIG_C, "Zed", 2, 85_000)               # the fastest lap, on the unlicensed rig
    snap = FeedConnection(FeedBuilder(hub)).start(last_seen(hub))
    assert [r["rig_id"] for r in snap["rigs"]] == [RIG_A, RIG_B]
    assert [r["rig_id"] for r in snap["frame"]["rigs"]] == [RIG_A, RIG_B]
    assert {r["rig_id"] for r in snap["frame"]["comparison"]["rigs"]} == {RIG_A, RIG_B}
    assert snap["leaderboards"] and all(RIG_C not in [e["rig_id"] for e in b["entries"]]
                                        for b in snap["leaderboards"])
    assert drivers(snap["leaderboards"][0]) == ["Akshat"]
    assert [lap_["rig_id"] for lap_ in snap["recent_laps"]] == [RIG_A]
    assert [s["rig_id"] for s in snap["session_story"]] == [RIG_A]
    assert RIG_C not in snap["status"]["formats"]
    # Racing is never interrupted: the lap is recorded, the staff-side board and staff page still have it.
    assert drivers(hub.laps.board(TRACK, "today", None)) == ["Zed", "Akshat"]
    assert RIG_C in FeedBuilder(hub).status(last_seen(hub))["formats"]


async def test_deltas_and_moments_leave_out_rigs_beyond_the_licence(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer)
    conn = FeedConnection(FeedBuilder(hub))
    conn.start(last_seen(hub))
    drive_lap(hub, RIG_A, "Akshat", 2, 90_000)
    drive_lap(hub, RIG_C, "Zed", 2, 85_000)                 # its record moment is not for the TV
    drive_lap(hub, RIG_B, "Kofi", 2, 89_000)                # beats Akshat on the TV's boards: a record moment
    hub.drivers.assign(RIG_C, "Zed")
    hub.announce_driver(RIG_C)                               # "now driving" on rig 3: not for the TV
    hub.podium("staff")
    msgs = conn.tick(last_seen(hub))
    laps = [m["lap"]["rig_id"] for m in msgs if m["type"] == "lap_completed"]
    assert laps == [RIG_A, RIG_B]
    moments = [m["moment"] for m in msgs if m["type"] == "moment"]
    assert [(m["kind"], m.get("rig_id")) for m in moments] == [("record", RIG_B), ("podium", None)]
    assert [e["driver"] for e in moments[1]["entries"]] == ["Kofi", "Akshat"]
    assert moments[0]["records"][0]["previous_driver"] == "Akshat"
    boards = [m["leaderboard"] for m in msgs if m["type"] == "leaderboard"]
    assert boards and all(RIG_C not in [e["rig_id"] for e in b["entries"]] for b in boards)
    assert all(r["rig_id"] != RIG_C for m in msgs if m["type"] == "frame" for r in m["rigs"])
    assert not [m for m in msgs if m["type"] == "rig_info"]
    # Everything is still in the lap book for the staff page and the database.
    assert [(b["moment"]["kind"], b["moment"].get("rig_id")) for _, t, b in hub.laps.messages if t == "moment"] == \
        [("record", RIG_C), ("record", RIG_B), ("now_driving", RIG_C), ("podium", None)]


def test_tv_message_trims_moments_about_several_rigs():
    hidden = frozenset({"c"})
    podium = {"moment": {"kind": "race_podium", "drivers": [{"rig_id": "a"}, {"rig_id": "c"}, {"rig_id": "b"}]}}
    assert tv_message("moment", podium, hidden)["moment"]["drivers"] == [{"rig_id": "a"}, {"rig_id": "b"}]
    assert podium["moment"]["drivers"][1] == {"rig_id": "c"}                   # the lap book's copy is untouched
    assert tv_message("moment", {"moment": {"kind": "battle", "rig_ids": ["a", "c"]}}, hidden) is None
    assert tv_message("moment", {"moment": {"kind": "card", "rig_id": "c"}}, hidden) is None
    assert tv_message("moment", {"moment": {"kind": "podium", "entries": [{"rig_id": "c"}]}}, hidden) is None
    assert tv_message("lap_completed", {"lap": {"rig_id": "c"}}, hidden) is None
    body = {"outline": {"track_key": TRACK}}
    assert tv_message("track_outline", body, hidden) is body
    assert tv_message("lap_completed", {"lap": {"rig_id": "c"}}, frozenset()) == {"lap": {"rig_id": "c"}}


async def test_race_podium_on_the_tv_has_only_licensed_rigs(tmp_path, signer):
    from simtelemetry.core.adapter import RaceFinished
    hub = await three_rigs(tmp_path, signer)
    now = time.monotonic()
    for i, rig in enumerate((RIG_C, RIG_A, RIG_B), 1):
        hub.races.add(rig, RaceFinished(track_key=TRACK, session_type="Race", session_uid="u", position=i,
                                        grid_position=i, laps=5, best_lap_ms=90_000 + i, total_time_s=450.0 + i,
                                        penalties_s=0, status="finished", num_cars=20), now)
    (done,) = hub.settle_races(now + 3600)
    assert len(done["cards"]) == 3                                            # every guest still gets a card
    assert [d["rig_id"] for d in done["moment"]["drivers"]] == [RIG_A, RIG_B]


async def test_head_to_head_and_mini_sectors_leave_out_hidden_rigs():
    book = LapBook()
    day = book._today()
    for rig, driver, ms in (("a", "Akshat", 90_000), ("c", "Zed", 90_010), ("b", "Kofi", 91_000)):
        book._analyses[(TRACK, day, driver)] = {
            "rig_id": rig, "driver": driver, "lap_ms": ms, "lap_number": 2, "lap_class": "open",
            "minis": [ms // 24] * 24, "speed": None, "share": None, "completed_at": ms, "track_name": "Silverstone"}
    assert book.head_to_head(TRACK)["b"]["rig_id"] == "c"
    h2h = book.head_to_head(TRACK, exclude={"c"})
    assert (h2h["a"]["rig_id"], h2h["b"]["rig_id"]) == ("a", "b")
    assert "c" not in book._mini_owners(TRACK, {"c"})


async def test_challenge_board_on_the_tv_leaves_out_hidden_rigs(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer)
    drive_lap(hub, RIG_A, "Akshat", 2, 90_000)
    drive_lap(hub, RIG_C, "Zed", 2, 85_000)
    today = dt.date.today().isoformat()
    hub.competitions.create_challenge({"track_key": TRACK, "starts": today, "ends": today})
    assert [e["driver"] for e in hub.competitions.challenges()[0]["entries"]] == ["Zed", "Akshat"]   # staff
    comp = FeedBuilder(hub).competition(TRACK)
    assert [e["driver"] for e in comp["challenge"]["entries"]] == ["Akshat"]


async def test_pinned_rig_beyond_the_licence_reads_as_automatic(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer)
    hub.tv.set(pinned_rig=RIG_C)
    assert FeedBuilder(hub).tv()["pinned_rig"] is None
    hub.tv.set(pinned_rig=RIG_B)
    assert FeedBuilder(hub).tv()["pinned_rig"] == RIG_B


async def test_a_rig_the_tv_has_that_falls_outside_the_licence_gets_a_fresh_snapshot(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer, rigs=3)
    conn = FeedConnection(FeedBuilder(hub))
    assert len(conn.start(last_seen(hub))["rigs"]) == 3
    assert conn.tick(last_seen(hub))[-1]["type"] == "frame"
    hub.registry.get(RIG_B).auto_name = "Rig 7"           # e.g. "same rig as…" moved a number
    (snap,) = conn.tick(last_seen(hub))
    assert snap["type"] == "snapshot" and [r["rig_id"] for r in snap["rigs"]] == [RIG_A, RIG_C]
    # New rigs: number 2 (free again) is sent; number 4, beyond the licence, is simply never sent (no snapshot).
    await feed(hub, driving_rig("192.168.1.24", uid=0x14) + driving_rig("192.168.1.25", uid=0x15))
    assert [hub.registry.get(ip).number for ip in ("192.168.1.24", "192.168.1.25")] == [2, 4]
    msgs = conn.tick(last_seen(hub))
    assert "snapshot" not in [m["type"] for m in msgs]
    assert [m["rig"]["rig_id"] for m in msgs if m["type"] == "rig_info"] == ["192.168.1.24"]


async def test_new_code_applies_live(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer)
    conn = FeedConnection(FeedBuilder(hub))
    assert len(conn.start(last_seen(hub))["rigs"]) == 2
    hub.apply_licence(signer.code(rigs=3, seq=2, variant="unbranded"))
    (snap,) = conn.tick(last_seen(hub))
    assert snap["type"] == "snapshot" and len(snap["rigs"]) == 3 and snap["hub"]["vendor_mark"] is False
    assert hub.licence_rigs_warning() is None


# --- staff page and warnings -------------------------------------------------------------------

async def test_staff_rig_card_says_not_licensed(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer)
    client = TestClient(create_app(staff_ready(hub), dashboard_dir=tmp_path / "none"), headers=STAFF)
    rows = {r["rig_id"]: r for r in client.get("/api/staff/rigs").json()["rigs"]}
    assert [rows[ip]["licence_note"] for ip in (RIG_A, RIG_B, RIG_C)] == [None, None, "Not licensed"]
    assert rows[RIG_C]["licensed"] is False and rows[RIG_C]["state"] == "driving"   # still racing
    page = client.get("/staff").text
    assert 'class="rig__licence"' in page and "rig.licence_note" in page
    # A session can still be started on it.
    assert client.put(f"/api/staff/rigs/{RIG_C}/driver", json={"name": "Zed"}).status_code == 200


@pytest.mark.parametrize("variant, supplier", [("9t7", brand.COMPANY), ("unbranded", "your supplier")])
async def test_rigs_warning_wording_on_health_and_owner_page(tmp_path, signer, variant, supplier):
    hub = await three_rigs(tmp_path, signer, variant=variant)
    text = f"This licence covers 2 rigs. Rig 3 and up aren't shown on the TV. Contact {supplier} to add rigs."
    assert hub.licence_rigs_warning() == text
    client = TestClient(create_app(staff_ready(hub), dashboard_dir=tmp_path / "none"))
    health = client.get("/api/staff/health", headers=STAFF).json()["warnings"]
    assert {"code": "licence_rigs", "rig_id": None, "message": text} in health
    assert client.get("/api/owner/licence", headers=OWNER).json()["rigs_warning"] == text
    snap = FeedConnection(FeedBuilder(hub)).start(last_seen(hub))
    assert "licence" not in str(snap["status"])                                # never on the TV
    if variant == "unbranded":
        assert brand.COMPANY not in str(client.get("/api/owner/licence", headers=OWNER).json())


async def test_rigs_warning_only_when_a_rig_beyond_the_licence_exists(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer, rigs=3)
    assert hub.licence_rigs_warning() is None
    assert "licence_rigs" not in [w["code"] for w in hub.admin_warnings()]
    hub.apply_licence(signer.code(rigs=1, seq=2))
    assert hub.licence_rigs_warning().startswith("This licence covers 1 rig. Rig 2 and up")


# --- features ------------------------------------------------------------------------------------

async def test_effective_features_are_hub_toml_and_the_licence(tmp_path, signer):
    hub = make_hub(tmp_path, features={"moments": False}, owner={"pin": "2468"})
    assert hub.features == hub.config.features                                  # fallback: every feature
    hub.apply_licence(signer.code(features=["moments", "podium", "sharing", "owner"]))
    f = hub.features
    assert f.moments is False                     # licensed, but switched off in hub.toml: off
    assert f.podium is True and f.sharing is True
    assert f.battles is False and f.self_checkin is False and f.challenges is False   # not licensed: off
    assert f.backup_warning is True and f.auto_end_sessions is True    # safety switches: hub.toml only
    hub.config.features.battles = True            # the owner switches it on in hub.toml: still off
    assert hub.features.battles is False
    assert hub.config.features.battles is True    # hub.toml's own flag is left as the owner set it
    snap = FeedConnection(FeedBuilder(hub)).start(time.monotonic())
    assert snap["hub"]["features"]["battles"] is False and snap["hub"]["features"]["podium"] is True
    hub.apply_licence(signer.code(features=["moments", "podium", "sharing", "owner", "battles"], seq=2))
    assert hub.features.battles is True           # an add-on code switches it on at once


async def test_unlicensed_features_behave_like_switched_off_flags(tmp_path, signer):
    hub = await three_rigs(tmp_path, signer, rigs=None)
    hub.config.owner.pin = "2468"
    hub.apply_licence(signer.code(features=["sharing"]))
    client = TestClient(create_app(staff_ready(hub), dashboard_dir=tmp_path / "none"))
    hub.drivers.assign(RIG_A, "Maya")
    assert hub.announce_driver(RIG_A) is None                                    # moments: off
    assert client.get("/api/staff/checkin/codes", headers=STAFF).json()["enabled"] is False
    assert client.get("/api/checkin/whatever").status_code == 403               # self check-in: off
    assert client.put("/api/staff/tv", json={"overlay": "head_to_head"}, headers=STAFF).status_code == 400
    assert client.get("/api/staff/rigs", headers=STAFF).json()["features"]["self_checkin"] is False


async def test_owner_figures_need_the_licence_but_the_licence_card_never_does(tmp_path, signer):
    hub = make_hub(tmp_path, owner={"pin": "2468"})
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    assert client.get("/api/owner/report", headers=OWNER).status_code == 200
    hub.apply_licence(signer.code(features=["moments"], variant="unbranded"))
    r = client.get("/api/owner/report", headers=OWNER)
    assert r.status_code == 403
    assert r.json()["detail"] == "Business figures aren't included in this licence. Contact your supplier to add them."
    assert client.get("/api/owner/export.csv", headers=OWNER).status_code == 403
    body = client.get("/api/owner/licence", headers=OWNER).json()
    assert body["figures"] is False and body["figures_note"] == r.json()["detail"]
    assert client.get("/api/owner/backup", headers=OWNER).status_code == 200
    r = client.post("/api/owner/licence", headers=OWNER, json={"code": signer.code(features=["owner"], seq=2)})
    assert r.status_code == 200 and r.json()["figures"] is True                 # the add-on code went in
    assert client.get("/api/owner/report", headers=OWNER).status_code == 200
    page = client.get("/owner").text
    assert "data-figures" in page and "figures-note" in page


# --- games ---------------------------------------------------------------------------------------

class FakeRacer(F1Adapter):
    """A second game for the test: reads F1 packets, but the licence calls it something else."""
    game_id = "fake_racer"


def test_registry_lists_the_games_this_build_reads():
    assert adapters.registry() == {"f1_25": F1Adapter}
    assert adapters.game_id(F1Adapter()) == "f1_25" and adapters.game_id(object()) is None


async def test_packets_of_an_unlicensed_game_are_dropped_with_a_health_line(tmp_path, signer, monkeypatch):
    monkeypatch.setattr(adapters, "registry", lambda: {"f1_25": F1Adapter, "fake_racer": FakeRacer})
    monkeypatch.setitem(licence.GAME_NAMES, "fake_racer", "Fake Racer")
    hub = make_hub(tmp_path, adapter=adapters.registry()["fake_racer"]())
    hub.apply_licence(signer.code(games=["f1_25"]))
    await feed(hub, driving_rig(RIG_A))
    assert hub.adapter.live_summary(RIG_A) is None                                # nothing was decoded
    assert hub.health.get(RIG_A).drops["game_not_licensed"] == 5
    assert hub.registry.get(RIG_A) is not None                                    # the rig is listed
    line = {"code": "game_not_licensed", "rig_id": RIG_A, "message": "Rig 1: This licence doesn't include Fake Racer."}
    assert line in hub.admin_warnings()
    assert hub.state_text(RIG_A, time.monotonic()) == "Game not licensed"
    snap = FeedConnection(FeedBuilder(hub)).start(time.monotonic())
    assert "licence" not in str(snap["status"])                                   # not for the TV
    # An add-on code with the game: packets are read at once and the line goes.
    hub.apply_licence(signer.code(games=["f1_25", "fake_racer"], seq=2))
    await feed(hub, driving_rig(RIG_A))
    assert hub.adapter.live_summary(RIG_A) is not None
    assert "game_not_licensed" not in [w["code"] for w in hub.admin_warnings()]


async def test_the_licensed_game_is_read_in_every_format(tmp_path, signer):
    hub = make_hub(tmp_path)
    hub.apply_licence(signer.code(games=["f1_25"]))
    await feed(hub, driving_rig(RIG_A, fmt=2026))
    assert hub.adapter.live_summary(RIG_A) is not None and not hub.game_warnings()


# --- the supplier's mark -------------------------------------------------------------------------

async def test_vendor_mark_follows_the_variant(tmp_path, signer):
    hub = make_hub(tmp_path)
    conn = FeedConnection(FeedBuilder(hub))
    assert conn.start(time.monotonic())["hub"]["vendor_mark"] is True              # fallback: 9T7
    hub.apply_licence(signer.code(variant="unbranded"))
    (snap,) = conn.tick(time.monotonic())
    assert snap["type"] == "snapshot" and snap["hub"]["vendor_mark"] is False
    hub.apply_licence(signer.code(variant="9t7", seq=2))
    assert conn.tick(time.monotonic())[0]["hub"]["vendor_mark"] is True


def test_hub_pages_carry_no_supplier_mark(tmp_path):
    """The unbranded variant must show no 9T7 mark: the pages have none of their own (only text the hub sends,
    like the rigs warning, names the supplier, and that follows the variant)."""
    hub = make_hub(tmp_path, owner={"pin": "2468"})
    client = TestClient(create_app(staff_ready(hub), dashboard_dir=tmp_path / "none"))
    for path in ("/staff", "/owner", "/setup", "/hello", "/staff/checkin-print", "/checkin/ABCD"):
        text = client.get(path).text
        assert brand.COMPANY not in text and "9T7" not in text, path
