"""C13: the whole chain on Linux, with only build.ps1 and Edge faked.

factory profile -> build_package (licence issued, profile baked) -> the hub's `provision` of exactly the baked folder
into a fresh data folder -> a Hub started from that data folder and hub.toml -> licence entitlements, the TV feed,
the supplier's mark per variant, the soft rig limit -> add-on codes on the owner page after a build, a Rebuild all
and an Issue upgrade (seq rules, another cafe's code refused).
"""

import datetime as dt
import json
import shutil
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factory import build as B
from factory import docs
from factory import keys as K
from factory.build import FactorySettings, RunResult
from factory.profile import CafeProfile, ProfileStore, load
from simtelemetry import __version__, brand, licence, licence_pubkey
from simtelemetry.__main__ import apply_saved_settings
from simtelemetry.adapters.f1.adapter import F1Adapter
from simtelemetry.api.app import create_app
from simtelemetry.config import load_config_safe
from simtelemetry.core.feed import FeedBuilder, FeedConnection
from simtelemetry.core.rigs import RigRegistry
from simtelemetry.core.settings import CafeSettings, SettingsStore
from simtelemetry.core.store import LapStore
from simtelemetry.hub import Hub
from simtelemetry.provision import provision

HUB_TESTS = Path(__file__).resolve().parents[2] / "hub" / "tests"
if str(HUB_TESTS) not in sys.path:
    sys.path.insert(0, str(HUB_TESTS))
from test_feed import driving_rig, feed, last_seen  # noqa: E402  (the hub tests' packet helpers)

DAY = dt.date(2026, 11, 3)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
OWNER = {"X-Owner-Pin": "2468"}
STAFF = {"X-Staff-Pin": "1357"}
RIGS = [f"192.168.1.{20 + n}" for n in range(1, 9)]          # rig n (1-based) sends from RIGS[n - 1]


class BakingRunner:
    """build.ps1 (writes the installer and the program stamp, keeps a copy of each baked profile folder it was
    given, as the installer would carry it) and Edge (writes a PDF)."""

    def __init__(self, repo: Path, keep: Path) -> None:
        self.repo, self.keep = repo, keep
        self.baked: list[Path] = []

    def run(self, args, *, cwd=None, timeout=None, cancel=None):
        src = Path(args[args.index("-ProfileDir") + 1])
        slug = args[args.index("-CafeSlug") + 1]
        copy = self.keep / f"{len(self.baked) + 1}-{slug}"
        shutil.copytree(src, copy)
        self.baked.append(copy)
        dist = self.repo / "dist"
        (dist / brand.EXE_NAME).mkdir(parents=True, exist_ok=True)
        (dist / brand.EXE_NAME / B.STAMP_FILE).write_text(json.dumps(
            {"version": __version__, "commit": "abc1234", "dirty": False, "signed": False, "built": "now"}))
        (dist / f"{brand.EXE_NAME}-Setup-{slug}.exe").write_bytes(b"MZ" + b"\x90" * 500)
        return RunResult(0, "Installer done")

    def edge(self, args, **kwargs):
        out = next(a for a in args if a.startswith("--print-to-pdf=")).split("=", 1)[1]
        Path(out).write_bytes(b"%PDF-1.7 fake")
        import subprocess
        return subprocess.CompletedProcess(args, 0)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    keys = K.create_keys(tmp_path / "keys")
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", (keys.public,))   # the cafe's program knows the key (L1)
    repo = tmp_path / "repo"
    (repo / "hub" / "simtelemetry").mkdir(parents=True)
    (repo / K.PUBKEY_MODULE).write_text(K.public_key_py(keys.public), encoding="utf-8")
    (repo / "packaging").mkdir()
    (repo / B.BUILD_SCRIPT).write_text("# fake", encoding="utf-8")
    video = tmp_path / "video"
    video.mkdir()
    for name in B.VIDEO_FILES.values():
        (video / name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + name.encode() * 50)
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"MZ")
    settings = FactorySettings(shipments=tmp_path / "Shipments", edge=edge, keys_dir=keys.folder, repo_root=repo,
                               video_dir=video)
    (tmp_path / "baked").mkdir()
    f = types.SimpleNamespace(tmp=tmp_path, keys=keys, settings=settings, store=ProfileStore(settings.shipments),
                              runner=BakingRunner(repo, tmp_path / "baked"))
    return f


def new_cafe(f, name, variant, rigs, price=None, rig_names=()):
    p = CafeProfile.new(name, variant=variant, rigs=rigs, preset="full")
    if price is not None:
        p.set_price(price)
    p.rig_names = list(rig_names)
    src = f.tmp / f"logo-{p.cafe_id}.png"
    src.write_bytes(PNG)
    f.store.import_logo(p, src)
    f.store.save(p)
    return p


def build(f, p):
    return B.build_package(p, f.settings, f.runner, f.keys, store=f.store, today=DAY)


def reload(f, p):
    return load(f.store.find(p.cafe_id))


def install(f, baked: Path, pc: Path):
    """What the installer does on the cafe PC: `provision <tmp>\\profile` with the PC's data folder and hub.toml."""
    data, config = pc / "data", pc / "config" / "hub.toml"
    if not config.exists():
        config.parent.mkdir(parents=True)
        config.write_text(f'data_dir = "{data.as_posix()}"\n', encoding="utf-8")
    return provision(baked, data, config)


def owner_sets_pins(pc: Path):
    """The owner's first visit to /setup: PINs chosen, everything pre-filled kept."""
    store = SettingsStore(pc / "data")
    s = store.load()
    store.save(CafeSettings.model_validate({**s.model_dump(), "owner_pin": "2468", "staff_pin": "1357",
                                            "setup_done": True}))


def start_hub(pc: Path) -> Hub:
    """The hub as `run` starts it (minus sockets): hub.toml, the saved settings, the rig list, then the licence."""
    config, problems = load_config_safe(pc / "config" / "hub.toml")
    assert problems == [] and config.data_dir == pc / "data"
    apply_saved_settings(config, types.SimpleNamespace(owner_pin=None))
    hub = Hub(config, F1Adapter(config.track_names), RigRegistry(config, config.data_dir / "rigs.json"),
              store=LapStore(config.data_dir / "laps.db"), config_path=pc / "config" / "hub.toml")
    hub.load_licence()
    return hub


async def drive(hub: Hub, rigs: int):
    packets = []
    for n in range(1, rigs + 1):
        packets += driving_rig(RIGS[n - 1], uid=0x10 + n, name=f"Driver{n}".encode())
    await feed(hub, packets)
    assert [hub.registry.get(RIGS[n - 1]).number for n in range(1, rigs + 1)] == list(range(1, rigs + 1))


def snapshot(hub: Hub) -> dict:
    return FeedConnection(FeedBuilder(hub)).start(last_seen(hub))


def post_code(client, code):
    return client.post("/api/owner/licence", json={"code": code}, headers=OWNER)


# --- 9T7 Racing, 6 rigs ----------------------------------------------------------------------------------

async def test_9t7_cafe_from_profile_to_tv_and_add_on_codes(factory):
    f = factory
    p = new_cafe(f, "Apex Lounge", "9t7", 6, rig_names=["Senna", "", "Prost"])
    other = new_cafe(f, "Kart Hub", "unbranded", 4, price=45_000)
    first = build(f, p)
    other_build = build(f, other)
    assert first.seq == 1 and (first.path / p.installer_name()).is_file()
    baked = f.runner.baked[0]
    assert sorted(x.name for x in baked.iterdir()) == ["licence.txt", "logo.png", "profile.json"]

    # A fresh cafe PC: the installer provisions it, the owner chooses PINs, the hub starts.
    pc = f.tmp / "apex-pc"
    result = install(f, baked, pc)
    assert result.code == 0 and result.mode == "fresh", result.lines
    assert json.loads((pc / "data" / "cafe.json").read_text(encoding="utf-8"))["cafe_id"] == p.cafe_id
    owner_sets_pins(pc)
    hub = start_hub(pc)
    ent = hub.entitlements
    assert (ent.cafe_id, ent.rigs, ent.variant, ent.seq) == (p.cafe_id, 6, "9t7", 1)
    assert ent.vendor_mark is True and ent.supplier == brand.COMPANY and hub.licence_problem is None
    assert hub.config.cafe.name == "Apex Lounge"
    on = set(p.features_on())
    assert {k for k, v in hub.features.model_dump().items() if v} == on      # hub.toml AND licence = the profile

    await drive(hub, 7)                                                        # a 7th rig beyond the licence
    assert hub.registry.get(RIGS[0]).name == "Senna" and hub.registry.get(RIGS[2]).name == "Prost"
    assert hub.tv_hidden_rigs() == {RIGS[6]}
    snap = snapshot(hub)
    assert snap["hub"]["vendor_mark"] is True
    assert {r["rig_id"] for r in snap["rigs"]} == set(RIGS[:6])
    assert "Rig 7 and up" in hub.licence_rigs_warning() and brand.COMPANY in hub.licence_rigs_warning()

    client = TestClient(create_app(hub, dashboard_dir=f.tmp / "none"))
    rows = {r["rig_id"]: r for r in client.get("/api/staff/rigs", headers=STAFF).json()["rigs"]}
    assert rows[RIGS[6]]["licensed"] is False and rows[RIGS[0]]["licensed"] is True

    # Rebuild all (a new version): seq 2, same entitlements; the cafe runs the new installer over its PC.
    rows = B.rebuild_all(f.store, f.settings, f.runner, f.keys, today=DAY)
    assert [r.status for r in rows] == ["ok", "ok"], [r.message for r in rows]
    p = reload(f, p)
    assert [h.seq for h in p.history] == [1, 2]
    rebuilt = next(b for b in f.runner.baked[2:] if json.loads((b / "profile.json").read_text())["cafe_id"]
                   == p.cafe_id)
    before = {x.name: x.read_bytes() for x in (pc / "data").iterdir() if x.is_file() and x.name != "licence.txt"}
    result = install(f, rebuilt, pc)
    assert result.code == 0 and result.mode == "upgrade", result.lines
    after = {x.name: x.read_bytes() for x in (pc / "data").iterdir() if x.is_file() and x.name != "licence.txt"}
    assert after == before                                                    # settings, PINs, rig names kept
    hub.load_licence()
    assert hub.entitlements.seq == 2 and hub.entitlements.rigs == 6

    # Issue upgrade: 8 rigs, seq 3. The owner pastes the code; the TV shows rigs 7 and 8 at once.
    p.rigs = 8
    f.store.save(p)
    up = B.issue_upgrade(p, f.settings, f.keys, f.runner, store=f.store, today=DAY)
    assert up.seq == 3 and up.price_inr == 10_000
    r = post_code(client, up.code)
    assert r.status_code == 200, r.text
    assert r.json()["rigs"] == 8 and r.json()["seq"] == 3
    assert hub.tv_hidden_rigs() == frozenset() and hub.licence_rigs_warning() is None
    assert len(snapshot(hub)["rigs"]) == 7

    # Older codes (the first build's and the rebuild's) and another cafe's code are refused, plainly.
    for old in (first.code, (rebuilt / "licence.txt").read_text(encoding="utf-8")):
        r = post_code(client, old)
        assert r.status_code == 400 and r.json()["detail"] == licence.OLDER
    r = post_code(client, other_build.code)
    assert r.status_code == 400 and r.json()["detail"] == "This code is for Kart Hub. This PC belongs to Apex Lounge."
    r = post_code(client, up.code)
    assert r.status_code == 400 and r.json()["detail"] == licence.ALREADY_INSTALLED
    assert hub.entitlements.seq == 3

    # Running the rebuilt (seq 2) installer again later never takes the add-on away.
    result = install(f, rebuilt, pc)
    assert result.code == 0 and "already up to date" in " ".join(result.lines)
    assert licence.read_file(pc / "data").payload.seq == 3

    # Kart Hub's installer on Apex Lounge's PC is refused before anything changes.
    kart_baked = f.runner.baked[1]
    check = provision(kart_baked, pc / "data", pc / "config" / "hub.toml", check=True)
    assert check.code == 3 and "This PC belongs to Apex Lounge" in check.lines[0]


# --- unbranded, 4 rigs, custom price ----------------------------------------------------------------------

async def test_unbranded_cafe_hides_the_mark_and_a_fifth_rig(factory):
    f = factory
    p = new_cafe(f, "Kart Hub", "unbranded", 4, price=45_000)
    res = build(f, p)
    assert res.entry.price_inr == 45_000 and res.entry.variant == "unbranded"
    for name in (x.name for x in res.path.iterdir()):
        assert "9t7" not in name.lower()
    assert "9t7" not in (res.path / "README.txt").read_text(encoding="utf-8").lower()
    baked = f.runner.baked[0]
    assert "9t7" not in (baked / "profile.json").read_text(encoding="utf-8").lower()
    assert (res.path / docs.VIDEO_NAME).read_bytes() == (f.settings.video_dir / "unbranded.mp4").read_bytes()

    pc = f.tmp / "kart-pc"
    assert install(f, baked, pc).code == 0
    owner_sets_pins(pc)
    hub = start_hub(pc)
    ent = hub.entitlements
    assert (ent.rigs, ent.variant, ent.vendor_mark, ent.supplier) == (4, "unbranded", False, "your supplier")

    await drive(hub, 5)                                                        # a 5th rig on a 4-rig licence
    assert hub.tv_hidden_rigs() == {RIGS[4]}
    snap = snapshot(hub)
    assert snap["hub"]["vendor_mark"] is False
    assert {r["rig_id"] for r in snap["rigs"]} == set(RIGS[:4])
    assert RIGS[4] not in json.dumps(snap)                                     # nothing about rig 5 reaches the TV
    assert hub.health.get(RIGS[4]) is not None                                 # ...but it is still received
    warning = hub.licence_rigs_warning()
    assert warning.startswith("This licence covers 4 rigs. Rig 5 and up") and "your supplier" in warning
    assert brand.COMPANY not in warning

    client = TestClient(create_app(hub, dashboard_dir=f.tmp / "none"))
    card = client.get("/api/owner/licence", headers=OWNER).json()
    assert card["summary"] == "Licensed to Kart Hub · 4 rigs · F1 25" and card["variant"] == "unbranded"
    assert "9t7" not in json.dumps(card).lower() and "9T7" not in json.dumps(
        client.get("/api/staff/health", headers=STAFF).json())


# --- the seams between the factory, build.ps1, the installer and provision -----------------------------------

ROOT = Path(__file__).resolve().parents[2]


def test_build_command_uses_only_build_ps1_parameters(factory):
    """Every switch the factory passes is one build.ps1 declares (a typo would make PowerShell refuse the build)."""
    import re
    script = (ROOT / B.BUILD_SCRIPT).read_text(encoding="utf-8")
    params = re.search(r"param\((.*?)\n\)", script, re.S).group(1)
    declared = {m.lower() for m in re.findall(r"\$(\w+)", params)}
    for variant in ("9t7", "unbranded"):
        args = B.build_command(factory.settings, factory.tmp / "profile", "Apex-Lounge", variant)
        script_args = args[args.index("-File") + 2:]
        switches = {a[1:].lower() for a in script_args if a.startswith("-")}
        assert switches <= declared and {"profiledir", "cafeslug", "vendor", "installeronly"} <= switches
        vendor = script_args[script_args.index("-Vendor") + 1]
        assert vendor == (brand.COMPANY if variant == "9t7" else "none")
    assert '$Vendor -eq "none"' in script                      # build.ps1 reads "none" as unbranded


def test_installer_refuses_on_provisions_other_cafe_exit_code():
    import re
    from simtelemetry import provision as P
    iss = (ROOT / "packaging" / "pitwall.iss").read_text(encoding="utf-8")
    assert int(re.search(r"PROVISION_OTHER_CAFE\s*=\s*(\d+);", iss).group(1)) == P.EXIT_OTHER_CAFE
    assert "provision" in iss and "--check" in iss and "--force-other-cafe" in iss
