"""The package pipeline (spec 2.5) with build.ps1 and Edge faked: atomic packages, verification, history, Rebuild
all, Issue upgrade, cancel, settings and the real Runner on Linux."""

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from factory import build as B
from factory import docs
from factory import keys as K
from factory.build import BuildCancelled, BuildError, FactorySettings, RunResult
from factory.profile import CafeProfile, ProfileError, ProfileStore, load
from simtelemetry import __version__, brand, licence

DAY = dt.date(2026, 11, 3)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# --- fakes --------------------------------------------------------------------------------------------

class FakeRunner:
    """build.ps1: writes dist/<exe>-Setup-<slug>.exe and the stamp, like the real script. Edge: writes the PDF."""

    def __init__(self, repo: Path, rc=0, installer=True, version=__version__, hook=None, stopped=None,
                 pdf=b"%PDF-1.7 fake", fail_slugs=()):
        self.repo, self.rc, self.installer, self.version = repo, rc, installer, version
        self.hook, self.stopped, self.pdf, self.fail_slugs = hook, stopped, pdf, set(fail_slugs)
        self.calls: list[list[str]] = []
        self.edge_calls: list[list[str]] = []
        self.seen: dict[str, bytes] = {}

    @staticmethod
    def arg(args, name):
        return args[args.index(name) + 1]

    def run(self, args, *, cwd=None, timeout=None, cancel=None):
        self.calls.append(list(args))
        profile_dir = Path(self.arg(args, "-ProfileDir"))
        slug = self.arg(args, "-CafeSlug")
        self.seen = {p.name: p.read_bytes() for p in profile_dir.iterdir()}
        if self.hook:
            self.hook(profile_dir, cancel)
        if self.stopped:
            return RunResult(-9, "stopped", self.stopped)
        if self.rc or slug in self.fail_slugs:
            return RunResult(1, "ISCC failed (exit 2)")
        dist = self.repo / "dist"
        (dist / brand.EXE_NAME).mkdir(parents=True, exist_ok=True)
        (dist / brand.EXE_NAME / B.STAMP_FILE).write_text(json.dumps(
            {"version": self.version, "commit": "abc1234", "dirty": False, "signed": False, "built": "now"}))
        if self.installer:
            (dist / f"{brand.EXE_NAME}-Setup-{slug}.exe").write_bytes(b"MZ" + b"\x90" * 500)
        return RunResult(0, "Reusing the program\nInstaller done")

    def edge(self, args, **kwargs):
        self.edge_calls.append(list(args))
        out = next(a for a in args if a.startswith("--print-to-pdf=")).split("=", 1)[1]
        if self.pdf is not None:
            Path(out).write_bytes(self.pdf)
        return subprocess.CompletedProcess(args, 0)


@pytest.fixture
def env(tmp_path):
    keys = K.create_keys(tmp_path / "keys")
    repo = tmp_path / "repo"
    (repo / "hub" / "simtelemetry").mkdir(parents=True)
    (repo / K.PUBKEY_MODULE).write_text(K.public_key_py(keys.public), encoding="utf-8")
    (repo / "packaging").mkdir()
    (repo / B.BUILD_SCRIPT).write_text("# fake", encoding="utf-8")
    video = tmp_path / "video"
    video.mkdir()
    for name in B.VIDEO_FILES.values():
        (video / name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + name.encode() * 100)
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"MZ")
    settings = FactorySettings(shipments=tmp_path / "Ship ments", edge=edge, keys_dir=keys.folder, repo_root=repo,
                               video_dir=video)

    class Env:
        pass
    e = Env()
    e.tmp, e.keys, e.repo, e.settings, e.video = tmp_path, keys, repo, settings, video
    e.store = ProfileStore(settings.shipments)
    e.runner = FakeRunner(repo)
    return e


def cafe(env, name="Apex Lounge", variant="9t7", rigs=6, preset="full", logo=True) -> CafeProfile:
    p = CafeProfile.new(name, variant=variant, rigs=rigs, preset=preset)
    if variant == "unbranded":
        p.set_price(45_000)
    if logo:
        src = env.tmp / f"logo-{name}.png"
        src.write_bytes(PNG)
        env.store.import_logo(p, src)
    env.store.save(p)
    return p


def build(env, p, **kw):
    kw.setdefault("today", DAY)
    return B.build_package(p, env.settings, kw.pop("runner", env.runner), env.keys, store=env.store, **kw)


def shipments_content(env) -> set[str]:
    return {p.name for p in env.settings.shipments.iterdir()}


def assert_nothing_left(env, p):
    """No package, no staging, no history (in memory and on disk), and no installer left in dist."""
    assert shipments_content(env) <= {"profiles"}
    assert p.history == []
    saved = load(env.store.find(p.cafe_id))
    assert saved.history == []
    assert not list((env.repo / "dist").glob("*.exe")) if (env.repo / "dist").exists() else True


# --- happy path ---------------------------------------------------------------------------------------

def test_build_happy_path_9t7(env):
    p = cafe(env)
    steps = []
    res = build(env, p, progress=lambda done, total, text: steps.append((done, total, text)))

    assert res.path == env.settings.shipments / "Apex Lounge (2026-11-03)"
    assert shipments_content(env) == {"profiles", "Apex Lounge (2026-11-03)"}           # no staging left
    files = {f.name for f in res.path.iterdir()}
    assert files == {f"{brand.EXE_NAME}-Setup-Apex-Lounge.exe",
                     "Setup guide - Apex Lounge.pdf", "Licence certificate - Apex Lounge.pdf",
                     docs.VIDEO_NAME, "README.txt"}
    assert (res.path / docs.VIDEO_NAME).read_bytes() == (env.video / "9t7.mp4").read_bytes()
    readme = (res.path / "README.txt").read_bytes()
    assert b"\r\n" in readme and b"\r\r\n" not in readme
    assert not (env.repo / "dist" / p.installer_name()).exists()                      # moved, not left in dist

    (args,) = env.runner.calls
    assert args[1:5] == ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert args[5] == str(env.repo / "packaging" / "build.ps1") and "-InstallerOnly" in args
    assert FakeRunner.arg(args, "-CafeSlug") == "Apex-Lounge"
    assert FakeRunner.arg(args, "-Vendor") == brand.COMPANY
    pdir = Path(FakeRunner.arg(args, "-ProfileDir"))
    assert pdir.parent.parent == env.settings.shipments and pdir.parent.name.startswith(".staging-")
    assert set(env.runner.seen) == {"profile.json", "licence.txt", "logo.png"}
    baked = json.loads(env.runner.seen["profile.json"])
    assert baked["cafe_id"] == p.cafe_id and baked["rigs"] == 6 and "contact" not in baked
    assert env.runner.seen["licence.txt"].decode().strip() == res.code
    assert len(env.runner.edge_calls) == 2

    lic = licence.verify(res.code, keys=(env.keys.public,))
    assert lic.payload.seq == 1 and lic.payload.cafe_id == p.cafe_id and lic.payload.issued == DAY

    (h,) = p.history
    assert h.kind == "build" and h.seq == 1 and h.licence_id == res.licence_id == lic.payload.licence_id
    assert h.pitwall_version == __version__ == res.pitwall_version and h.date == DAY
    assert h.price_inr == 30_000 and h.package == res.path.name and h.rigs == 6 and h.variant == "9t7"
    assert h.games == ["f1_25"] and h.features == list(lic.payload.features)
    assert load(env.store.find(p.cafe_id)).history == [h]                                # saved

    assert [s[0] for s in steps] == list(range(10)) and all(s[1] == 9 for s in steps)
    assert steps[0][2] == B.BUILD_STEPS[0] and steps[-1][2] == "Done"
    assert "Step 9 of 9" in res.details


def test_build_unbranded(env):
    p = cafe(env, "Kart Hub", variant="unbranded", rigs=4)
    res = build(env, p)
    assert FakeRunner.arg(env.runner.calls[0], "-Vendor") == "none"
    readme = (res.path / "README.txt").read_text(encoding="utf-8")
    assert "9t7" not in readme.lower() and "your supplier" in readme
    assert (res.path / docs.VIDEO_NAME).read_bytes() == (env.video / "unbranded.mp4").read_bytes()
    assert p.history[0].variant == "unbranded" and p.history[0].price_inr == 45_000


def test_second_build_same_day_gets_a_suffix_and_next_seq(env):
    p = cafe(env)
    first = build(env, p)
    second = build(env, p)
    third = build(env, p)
    assert second.path.name == "Apex Lounge (2026-11-03) (2)" and third.path.name == "Apex Lounge (2026-11-03) (3)"
    assert first.path.is_dir() and [h.seq for h in p.history] == [1, 2, 3]
    assert licence.verify(second.code, keys=(env.keys.public,)).payload.seq == 2


def test_cafe_without_logo_builds(env):
    p = cafe(env, logo=False)
    build(env, p)
    assert set(env.runner.seen) == {"profile.json", "licence.txt"}


def test_private_key_bytes_never_in_package(env):
    p = cafe(env)
    res = build(env, p)
    k = env.keys.private
    raw = k.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pem = k.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    body = b"".join(l for l in pem.splitlines() if not l.startswith(b"-----"))
    for f in res.path.rglob("*"):
        data = f.read_bytes()
        assert raw not in data and raw.hex().encode() not in data and body not in data and pem not in data
    assert raw.hex() not in res.details and body.decode() not in res.details
    for data in env.runner.seen.values():
        assert raw not in data and body not in data


# --- failures leave nothing ------------------------------------------------------------------------------

def test_profile_problems_stop_before_anything(env):
    p = cafe(env)
    p.name = ""
    env.store.save(p)
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert "Enter the cafe's name." in e.value.message and env.runner.calls == []
    assert e.value.details
    assert_nothing_left(env, p)


def test_missing_video_is_a_plain_problem_before_issuing(env):
    p = cafe(env, variant="unbranded")
    (env.video / "unbranded.mp4").unlink()
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert e.value.message.startswith("Guide video for this variant is missing.")
    assert env.runner.calls == [] and env.runner.edge_calls == []
    assert_nothing_left(env, p)
    assert B.video_problem(env.settings, "9t7") is None
    (env.video / "9t7.mp4").write_bytes(b"")
    assert B.video_problem(env.settings, "9t7") == B.VIDEO_MISSING


def test_key_not_trusted_is_a_plain_error(env):
    p = cafe(env)
    (env.repo / K.PUBKEY_MODULE).write_text("TRUSTED_KEYS = ()\n", encoding="utf-8")
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert e.value.message == B.KEY_NOT_TRUSTED and "Set up keys" in e.value.message
    assert env.runner.calls == []
    assert_nothing_left(env, p)


def test_no_keys_is_a_plain_error(env, tmp_path):
    p = cafe(env)
    env.settings.keys_dir = tmp_path / "nokeys"
    with pytest.raises(BuildError, match="Set up keys"):
        B.build_package(p, env.settings, env.runner, None, store=env.store, today=DAY)
    assert_nothing_left(env, p)


def test_edge_missing_stops_before_anything(env, monkeypatch):
    p = cafe(env)
    env.settings.edge = env.tmp / "nowhere" / "msedge.exe"
    monkeypatch.setattr(docs, "edge_candidates", lambda env=None: [])
    with pytest.raises(BuildError, match="Microsoft Edge wasn't found"):
        build(env, p)
    assert env.runner.calls == []
    assert_nothing_left(env, p)


@pytest.mark.parametrize("runner_kw, message", [
    ({"rc": 1}, "The installer couldn't be made"),
    ({"installer": False}, "no installer was made"),
    ({"version": "0.0.1"}, "wasn't built for version"),
    ({"pdf": None}, "Microsoft Edge didn't make the PDF"),
    ({"pdf": b"not a pdf"}, "Microsoft Edge didn't make the PDF"),
    ({"stopped": "timeout"}, "took too long"),
])
def test_failure_at_each_step_leaves_no_package_and_no_history(env, runner_kw, message):
    p = cafe(env)
    runner = FakeRunner(env.repo, **runner_kw)
    with pytest.raises(BuildError) as e:
        build(env, p, runner=runner)
    assert message in e.value.message and not isinstance(e.value, BuildCancelled)
    assert "Stopped:" in e.value.details
    assert_nothing_left(env, p)
    # and the next build works, with the same licence number (nothing left the PC)
    res = build(env, p)
    assert res.seq == 1 and res.path.name == "Apex Lounge (2026-11-03)"


def test_build_failure_hint_for_missing_inno_setup(env):
    p = cafe(env)
    runner = FakeRunner(env.repo, rc=1)
    runner.run = lambda args, **kw: RunResult(1, "Inno Setup 6 not found. Install it: winget ...")
    with pytest.raises(BuildError, match="Inno Setup isn't installed"):
        build(env, p, runner=runner)
    assert_nothing_left(env, p)


def test_powershell_cannot_start(env):
    p = cafe(env)
    runner = FakeRunner(env.repo)

    def boom(args, **kw):
        raise FileNotFoundError("powershell")
    runner.run = boom
    with pytest.raises(BuildError, match="PowerShell couldn't be started"):
        build(env, p, runner=runner)
    assert_nothing_left(env, p)


def test_disk_error_is_plain(env, monkeypatch):
    p = cafe(env)
    monkeypatch.setattr(B, "_copy", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left")))
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert e.value.message == B.WRITE_FAILED and "No space left" in e.value.details
    assert_nothing_left(env, p)


def test_unexpected_error_is_plain_and_cleans_up(env, monkeypatch):
    p = cafe(env)
    monkeypatch.setattr(docs, "render_readme", lambda *a, **k: 1 / 0)
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert e.value.message == B.UNEXPECTED and "ZeroDivisionError" in e.value.details
    assert_nothing_left(env, p)


def test_history_save_failure_takes_the_package_back_out(env, monkeypatch):
    p = cafe(env)

    def refuse(profile):
        raise ProfileError("no")
    monkeypatch.setattr(env.store, "save", refuse)
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert e.value.message == B.NOT_RECORDED
    monkeypatch.undo()
    assert_nothing_left(env, p)


# --- verification ----------------------------------------------------------------------------------------

def test_verification_catches_a_tampered_licence(env):
    p = cafe(env)

    def tamper(folder, cancel):
        code = (folder / "licence.txt").read_text().strip()
        body, sig = code[4:].split(".")
        flipped = body[:10] + ("A" if body[10] != "A" else "B") + body[11:]
        (folder / "licence.txt").write_text(f"PW1-{flipped}.{sig}\n")
    with pytest.raises(BuildError) as e:
        build(env, p, runner=FakeRunner(env.repo, hook=tamper))
    assert "didn't pass" in e.value.message
    assert_nothing_left(env, p)


def test_verification_catches_a_licence_for_other_rigs(env):
    """A validly signed code that isn't the one issued for this build (other rigs) is refused."""
    p = cafe(env)
    other = p.model_copy(deep=True)
    other.rigs = 8
    from factory.licence_issue import issue
    wrong = issue(other, env.keys, issued=DAY).code

    def swap(folder, cancel):
        (folder / "licence.txt").write_text(wrong + "\n")
    with pytest.raises(BuildError, match="doesn't match this cafe"):
        build(env, p, runner=FakeRunner(env.repo, hook=swap))
    assert_nothing_left(env, p)


def test_verification_catches_a_changed_baked_profile(env):
    p = cafe(env)

    def change(folder, cancel):
        data = json.loads((folder / "profile.json").read_text())
        data["rigs"] = 2
        (folder / "profile.json").write_text(json.dumps(data))
    with pytest.raises(BuildError, match="don't match this cafe"):
        build(env, p, runner=FakeRunner(env.repo, hook=change))
    assert_nothing_left(env, p)


def test_verification_catches_a_stray_vendor_mark_in_unbranded(env, monkeypatch):
    p = cafe(env, variant="unbranded")
    real = docs.render_readme
    monkeypatch.setattr(docs, "render_readme", lambda *a, **k: real(*a, **k) + "Made by 9t7 racing\r\n")
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert brand.COMPANY in e.value.message and "README.txt" in e.value.details
    assert_nothing_left(env, p)


def test_verification_catches_a_vendor_mark_in_an_unbranded_pdf_source(env, monkeypatch):
    p = cafe(env, variant="unbranded")
    real = docs.render_html
    monkeypatch.setattr(docs, "render_html", lambda kind, *a, **k: real(kind, *a, **k).replace(
        "</body>", "<p>9T7</p></body>") if kind == "certificate" else real(kind, *a, **k))
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert "certificate.html" in e.value.details
    assert_nothing_left(env, p)


def test_9t7_package_may_name_the_company(env):
    p = cafe(env)
    res = build(env, p)
    assert brand.COMPANY in (res.path / "README.txt").read_text(encoding="utf-8")


def test_verification_catches_key_bytes_in_a_file(env, monkeypatch):
    p = cafe(env)
    raw = env.keys.private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    real = docs.render_readme
    monkeypatch.setattr(docs, "render_readme", lambda *a, **k: real(*a, **k) + raw.hex())
    with pytest.raises(BuildError, match="signing key"):
        build(env, p)
    assert_nothing_left(env, p)


def test_verification_catches_an_empty_or_extra_file(env, monkeypatch):
    p = cafe(env)
    real_copy = B._copy
    monkeypatch.setattr(B, "_copy", lambda src, dest, cancel: dest.write_bytes(b""))
    with pytest.raises(BuildError, match="empty or damaged"):
        build(env, p)
    assert_nothing_left(env, p)

    def extra(src, dest, cancel):
        real_copy(src, dest, cancel)
        (dest.parent / "stray.txt").write_text("x")
    monkeypatch.setattr(B, "_copy", extra)
    with pytest.raises(BuildError, match="isn't complete"):
        build(env, p)
    assert_nothing_left(env, p)


# --- cancel ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("at", range(1, 8))
def test_cancel_between_steps_cleans_up(env, at):
    p = cafe(env)
    cancel = threading.Event()

    def progress(done, total, text):
        if done == at - 1:
            cancel.set()                         # pressed while step `at` runs: stops before the next step
    with pytest.raises(BuildCancelled) as e:
        build(env, p, cancel=cancel, progress=progress)
    assert e.value.message == B.CANCELLED
    assert_nothing_left(env, p)


def test_cancel_after_the_package_is_saved_still_records_it(env):
    p = cafe(env)
    cancel = threading.Event()
    res = build(env, p, cancel=cancel, progress=lambda done, total, text: done == 7 and cancel.set())
    assert res.path.is_dir() and len(p.history) == 1


def test_cancel_during_the_installer_build(env):
    p = cafe(env)
    cancel = threading.Event()
    runner = FakeRunner(env.repo, hook=lambda folder, c: cancel.set(), stopped="cancelled")
    with pytest.raises(BuildCancelled):
        build(env, p, runner=runner, cancel=cancel)
    assert_nothing_left(env, p)


def test_cancel_before_start(env):
    p = cafe(env)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(BuildCancelled):
        build(env, p, cancel=cancel)
    assert env.runner.calls == []
    assert_nothing_left(env, p)


def test_stale_staging_is_removed(env):
    p = cafe(env)
    old = env.settings.shipments / ".staging-old"
    (old / "profile").mkdir(parents=True)
    os.utime(old, (time.time() - B.STALE_STAGING_S - 60,) * 2)
    fresh = env.settings.shipments / ".staging-busy"
    fresh.mkdir()
    build(env, p)
    assert not old.exists() and fresh.exists()


# --- rebuild all -----------------------------------------------------------------------------------------

def test_rebuild_all_summary_with_one_failing_cafe(env):
    a = cafe(env, "Apex Lounge")
    b = cafe(env, "Bravo Racing", rigs=4)
    c = cafe(env, "Charlie Sims")                       # never built
    d = cafe(env, "Delta Karts", rigs=4)
    for p in (a, b, d):
        build(env, p)
    d.rigs = 8                                          # changed, not yet upgraded
    env.store.save(d)
    (env.store.dir / "broken.json").write_text("{nope")

    runner = FakeRunner(env.repo, fail_slugs={"Bravo-Racing"})
    seen = []
    rows = B.rebuild_all(env.store, env.settings, runner, env.keys,
                         progress=lambda done, total, text: seen.append((done, total, text)), today=DAY)
    by = {r.cafe: r for r in rows}
    assert by["Apex Lounge"].status == "ok" and by["Apex Lounge"].package.name == "Apex Lounge (2026-11-03) (2)"
    assert by["Bravo Racing"].status == "failed" and "installer couldn't be made" in by["Bravo Racing"].message
    assert by["Bravo Racing"].details
    assert by["Charlie Sims"].status == "skipped" and "Not built yet" in by["Charlie Sims"].message
    assert by["Delta Karts"].status == "failed" and "Issue upgrade" in by["Delta Karts"].message
    assert by["broken"].status == "failed" and "damaged" in by["broken"].message

    apex = load(env.store.find(a.cafe_id))
    assert [(h.kind, h.seq) for h in apex.history] == [("build", 1), ("rebuild", 2)]
    assert apex.history[1].rigs == 6 and apex.history[1].features == apex.history[0].features
    assert [h.seq for h in load(env.store.find(b.cafe_id)).history] == [1]          # failed: nothing added
    assert not any(n.startswith("Bravo Racing (2026-11-03) (") for n in shipments_content(env))
    assert not any(n.startswith(".staging") for n in shipments_content(env))
    assert seen[-1][0] == seen[-1][1] and all("Apex Lounge: " in t or "Bravo" in t or t == "Done"
                                             for _, _, t in seen)


def test_rebuild_all_cancel_skips_the_rest(env):
    a = cafe(env, "Apex Lounge")
    b = cafe(env, "Bravo Racing")
    build(env, a)
    build(env, b)
    cancel = threading.Event()
    rows = B.rebuild_all(env.store, env.settings, env.runner, env.keys, cancel,
                         progress=lambda d, t, text: text.startswith("Apex") and "Making the installer" in text
                         and cancel.set(), today=DAY)
    assert [(r.cafe, r.status) for r in rows] == [("Apex Lounge", "skipped"), ("Bravo Racing", "skipped")]
    assert {h.seq for h in load(env.store.find(a.cafe_id)).history} == {1}


def test_rebuild_all_without_keys_is_a_plain_error(env, tmp_path):
    env.settings.keys_dir = tmp_path / "none"
    with pytest.raises(BuildError, match="Set up keys"):
        B.rebuild_all(env.store, env.settings, env.runner)


# --- issue upgrade -----------------------------------------------------------------------------------------

def upgraded(env, variant="9t7"):
    p = cafe(env, "Apex Lounge", variant=variant, rigs=4, preset="basic")
    build(env, p)
    return p


def test_issue_upgrade_rigs_only(env):
    p = upgraded(env)
    p.rigs = 6
    res = B.issue_upgrade(p, env.settings, env.keys, env.runner, store=env.store, today=DAY)
    assert res.folder == env.settings.shipments / "Apex Lounge (2026-11-03) upgrade"
    assert {f.name for f in res.folder.iterdir()} == {"Upgrade certificate - Apex Lounge.pdf",
                                                      "Licence code - Apex Lounge.txt"}
    assert res.pdf_path == res.folder / "Upgrade certificate - Apex Lounge.pdf"
    txt = (res.folder / "Licence code - Apex Lounge.txt").read_text(encoding="utf-8")
    assert res.code in txt and "Use this code" in txt
    lic = licence.verify(res.code, keys=(env.keys.public,))
    assert lic.payload.seq == 2 == res.seq and lic.payload.rigs == 6
    assert res.price_inr == 10_000
    h = p.history[-1]
    assert (h.kind, h.seq, h.price_inr, h.rigs, h.package) == ("upgrade", 2, 10_000, 6, res.folder.name)
    assert load(env.store.find(p.cafe_id)).history[-1] == h
    assert env.runner.calls == [env.runner.calls[0]]                # the installer wasn't rebuilt
    assert not any(n.startswith(".staging") for n in shipments_content(env))


def test_issue_upgrade_certificate_lists_only_addons(env, monkeypatch):
    p = upgraded(env)
    p.features = {**p.features, "events": True}
    pages = {}
    real = docs.render_html

    def spy(kind, *a, **k):
        pages[kind] = real(kind, *a, **k)
        return pages[kind]
    monkeypatch.setattr(docs, "render_html", spy)
    res = B.issue_upgrade(p, env.settings, env.keys, env.runner, price_inr=3_000, store=env.store, today=DAY)
    page = pages["upgrade_certificate"]
    assert "Corporate events" in page and "Weekly challenges" not in page and "Podium screen" not in page
    assert res.entry.price_inr == 3_000


def test_issue_upgrade_refusals(env):
    p = upgraded(env)
    run = lambda **kw: B.issue_upgrade(p, env.settings, env.keys, env.runner, store=env.store, today=DAY, **kw)
    with pytest.raises(BuildError, match="Nothing was added"):
        run()
    p.rigs = 3
    with pytest.raises(BuildError, match="takes away"):
        run()
    p.rigs = 4
    p.features = {**p.features, "events": True}
    with pytest.raises(BuildError, match="Enter the price of the add-ons"):
        run()
    with pytest.raises(BuildError, match="whole number"):
        run(price_inr=-5)
    p.variant = "unbranded"
    p.set_price(50_000)
    with pytest.raises(BuildError, match="branding changed"):
        run(price_inr=100)
    fresh = cafe(env, "Never Built")
    with pytest.raises(BuildError, match="no earlier licence"):
        B.issue_upgrade(fresh, env.settings, env.keys, env.runner, store=env.store, today=DAY)
    assert [h.seq for h in p.history] == [1]
    assert shipments_content(env) == {"profiles", "Apex Lounge (2026-11-03)"}


def test_issue_upgrade_unbranded_needs_a_price_and_has_no_mark(env):
    p = upgraded(env, variant="unbranded")
    p.rigs = 5
    with pytest.raises(BuildError, match="Enter the price"):
        B.issue_upgrade(p, env.settings, env.keys, env.runner, store=env.store, today=DAY)
    res = B.issue_upgrade(p, env.settings, env.keys, env.runner, price_inr=4_000, store=env.store, today=DAY)
    for f in res.folder.iterdir():
        assert "9t7" not in f.name.lower()
    assert "9t7" not in (res.folder / "Licence code - Apex Lounge.txt").read_text(encoding="utf-8").replace(
        res.code, "").lower()


def test_issue_upgrade_twice_same_day_and_failure_leaves_nothing(env):
    p = upgraded(env)
    p.rigs = 5
    B.issue_upgrade(p, env.settings, env.keys, env.runner, store=env.store, today=DAY)
    p.rigs = 6
    with pytest.raises(BuildError, match="PDF"):
        B.issue_upgrade(p, env.settings, env.keys, FakeRunner(env.repo, pdf=None), store=env.store, today=DAY)
    assert [h.seq for h in p.history] == [1, 2]
    res = B.issue_upgrade(p, env.settings, env.keys, env.runner, store=env.store, today=DAY)
    assert res.folder.name == "Apex Lounge (2026-11-03) upgrade (2)" and res.seq == 3
    assert not any(n.startswith(".staging") for n in shipments_content(env))


def test_issue_upgrade_cancel(env):
    p = upgraded(env)
    p.rigs = 6
    cancel = threading.Event()
    with pytest.raises(BuildCancelled):
        B.issue_upgrade(p, env.settings, env.keys, env.runner, cancel=cancel, store=env.store, today=DAY,
                        progress=lambda d, t, text: d == 2 and cancel.set())
    assert [h.seq for h in p.history] == [1]
    assert shipments_content(env) == {"profiles", "Apex Lounge (2026-11-03)"}


def test_issue_upgrade_key_not_trusted(env):
    p = upgraded(env)
    p.rigs = 6
    (env.repo / K.PUBKEY_MODULE).write_text("TRUSTED_KEYS = ()\n", encoding="utf-8")
    with pytest.raises(BuildError) as e:
        B.issue_upgrade(p, env.settings, env.keys, env.runner, store=env.store, today=DAY)
    assert e.value.message == B.KEY_NOT_TRUSTED


# --- settings ----------------------------------------------------------------------------------------------

def test_settings_defaults_and_round_trip(tmp_path):
    s = FactorySettings()
    assert s.shipments.name == f"{brand.PRODUCT_NAME} Shipments" and s.shipments.parent.name == "Documents"
    assert s.edge is None and s.keys_dir is None and s.repo_root == B.REPO_ROOT
    path = tmp_path / "cfg" / "settings.json"
    s2 = FactorySettings(shipments=tmp_path / "S", edge=tmp_path / "edge.exe", keys_dir=tmp_path / "k")
    s2.save(path)
    back = FactorySettings.load(path)
    assert back == s2 and back.load_problem is None
    assert set(json.loads(path.read_text())) == {"v", "shipments", "edge", "keys_dir"}


def test_settings_missing_and_damaged(tmp_path):
    assert FactorySettings.load(tmp_path / "nope.json") == FactorySettings()
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    s = FactorySettings.load(bad)
    assert s == FactorySettings() and "couldn't be read" in s.load_problem
    bad.write_text("[1]")
    assert FactorySettings.load(bad).load_problem


def test_settings_never_saved_in_repo_or_shipments(tmp_path):
    s = FactorySettings(shipments=tmp_path / "S")
    with pytest.raises(BuildError):
        s.save(B.REPO_ROOT / "settings.json")
    with pytest.raises(BuildError):
        s.save(tmp_path / "S" / "settings.json")
    assert not (B.REPO_ROOT / "settings.json").exists()


def test_config_dir_next_to_keys(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path), "APPDATA": str(tmp_path), K.KEYS_ENV: str(tmp_path / "elsewhere")}
    assert B.config_dir(env) == K.default_dir({k: v for k, v in env.items() if k != K.KEYS_ENV}).parent
    assert B.config_dir(env).name == f"{brand.EXE_NAME}Factory"
    assert B.config_dir({B.CONFIG_ENV: str(tmp_path / "c")}) == tmp_path / "c"


def test_settings_problems(tmp_path):
    ok = FactorySettings(shipments=tmp_path / "S", keys_dir=tmp_path / "k")
    assert ok.problems() == []
    assert "outside the program's source" in FactorySettings(shipments=B.REPO_ROOT / "Shipments",
                                                             keys_dir=tmp_path / "k").problems()[0]
    assert "signing key is inside" in FactorySettings(shipments=tmp_path / "S",
                                                      keys_dir=tmp_path / "S" / "keys").problems()[0]
    assert "{" in FactorySettings(shipments=tmp_path / "S{1}", keys_dir=tmp_path / "k").problems()[0]


def test_key_folder_inside_shipments_refuses_build(env):
    p = cafe(env)
    env.settings.shipments = env.keys.folder.parent
    env.store = ProfileStore(env.settings.shipments)
    env.store.save(p)
    with pytest.raises(BuildError, match="signing key is inside"):
        build(env, p)
    assert env.runner.calls == []


def test_build_command(env):
    args = B.build_command(env.settings, Path("X:/s/profile"), "Apex-Lounge", "unbranded")
    assert args[0].lower().endswith("powershell") or args[0].lower().endswith("powershell.exe")
    assert args[1:] == ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(env.repo / "packaging" / "build.ps1"),
                        "-InstallerOnly", "-ProfileDir", str(Path("X:/s/profile")), "-CafeSlug", "Apex-Lounge",
                        "-Vendor", "none"]
    assert B.build_command(env.settings, Path("p"), "a", "9t7")[-1] == brand.COMPANY
    assert B.powershell_exe({"SystemRoot": r"D:\Win"}).endswith("powershell.exe") if os.name == "nt" else True


# --- the real Runner (Linux) -----------------------------------------------------------------------------

def test_runner_captures_output_and_exit_code(tmp_path):
    r = B.Runner().run([sys.executable, "-c", "import sys; print('hello ü'); sys.exit(3)"], cwd=tmp_path)
    assert r.returncode == 3 and "hello ü" in r.output and r.stopped is None


def test_runner_cancel_stops_the_command(tmp_path):
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    r = B.Runner().run([sys.executable, "-c", "import time; print('x', flush=True); time.sleep(30)"],
                       cwd=tmp_path, cancel=cancel)
    assert r.stopped == "cancelled" and time.monotonic() - start < 10 and "x" in r.output


def test_runner_timeout(tmp_path):
    r = B.Runner().run([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path, timeout=0.5)
    assert r.stopped == "timeout"


# --- C10 review: process tree, decoding, recording, key needles ----------------------------------------------

class FakeKernel32:
    def __init__(self, assign=1):
        self.calls, self.assign = [], assign

    def CreateJobObjectW(self, attrs, name):
        self.calls.append("create")
        return 42

    def SetInformationJobObject(self, handle, cls, info, size):
        flags = info._obj.BasicLimitInformation.LimitFlags
        self.calls.append(("set", handle, cls, flags, size))
        return 1

    def AssignProcessToJobObject(self, handle, proc_handle):
        self.calls.append(("assign", handle, proc_handle))
        return self.assign

    def TerminateJobObject(self, handle, code):
        self.calls.append(("terminate", handle))
        return 1

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))
        return 1


def test_win_job_kills_the_tree_on_close_and_terminate():
    k = FakeKernel32()
    job = B.WinJob(k)

    class Proc:
        _handle = 7
    assert job.add(Proc())
    job.terminate()
    job.close()
    job.close()                                           # closing twice is harmless
    size = 144 if sys.maxsize > 2 ** 32 else 112
    assert k.calls == ["create", ("set", 42, 9, 0x2000, size), ("assign", 42, 7), ("terminate", 42), ("close", 42)]


class FakeJob:
    made: list = []

    def __init__(self, assign=True):
        self.assign, self.proc, self.terminated, self.closed = assign, None, False, False
        FakeJob.made.append(self)

    def add(self, proc):
        self.proc = proc
        return self.assign

    def terminate(self):
        self.terminated = True
        os.killpg(self.proc.pid, 9)

    def close(self):
        self.closed = True


@pytest.mark.skipif(os.name == "nt", reason="the Windows path is faked on Linux")
def test_runner_on_windows_cancel_ends_the_job(tmp_path):
    FakeJob.made = []
    r = B.Runner()
    r.windows, r.job_factory = True, FakeJob
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    out = r.run([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path, cancel=cancel)
    job = FakeJob.made[0]
    assert out.stopped == "cancelled" and job.terminated and job.closed


@pytest.mark.skipif(os.name == "nt", reason="the Windows path is faked on Linux")
def test_runner_on_windows_without_a_job_still_runs(tmp_path):
    FakeJob.made = []
    r = B.Runner()
    r.windows, r.job_factory = True, lambda: FakeJob(assign=False)
    out = r.run([sys.executable, "-c", "print('ok')"], cwd=tmp_path)
    assert out.returncode == 0 and "ok" in out.output and FakeJob.made[0].closed and not FakeJob.made[0].terminated
    r.job_factory = lambda: (_ for _ in ()).throw(OSError("no jobs"))
    assert r.run([sys.executable, "-c", "print('ok')"], cwd=tmp_path).returncode == 0


def test_decode_mixed_output_line_by_line():
    data = "Python ü ok\r\n".encode("utf-8") + "ISCC é\r\n".encode("cp850") + b"\xff\xfe broken\n"
    text = B._decode(data, fallback="cp850")
    assert text.startswith("Python ü ok\r\nISCC é\r\n") and "broken" in text


@pytest.mark.parametrize("error", [ValueError("odd"), RuntimeError("odd")])
def test_history_save_unexpected_error_takes_the_package_back_out(env, monkeypatch, error):
    p = cafe(env)
    monkeypatch.setattr(env.store, "save", lambda profile: (_ for _ in ()).throw(error))
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert e.value.message == B.NOT_RECORDED
    monkeypatch.undo()
    assert_nothing_left(env, p)


def test_history_written_but_save_reports_failure_keeps_the_package(env, monkeypatch):
    p = cafe(env)
    real = env.store.save

    def half(profile):                    # the new file is written, then removing an old one fails
        real(profile)
        raise ProfileError("The cafe couldn't be saved.")
    monkeypatch.setattr(env.store, "save", half)
    result = build(env, p)
    monkeypatch.undo()
    assert result.path.is_dir()
    assert [h.licence_id for h in load(env.store.find(p.cafe_id)).history] == [result.licence_id]


@pytest.mark.parametrize("form", ["b64", "urlsafe", "HEX"])
def test_verification_catches_other_key_encodings(env, monkeypatch, form):
    import base64
    raw = env.keys.private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    leaked = {"b64": base64.b64encode(raw), "urlsafe": base64.urlsafe_b64encode(raw),
              "HEX": raw.hex().upper().encode()}[form]
    real = docs.render_readme
    monkeypatch.setattr(docs, "render_readme", lambda *a, **k: real(*a, **k) + leaked.decode())
    p = cafe(env)
    with pytest.raises(BuildError) as e:
        build(env, p)
    assert "signing key" in e.value.message
    assert_nothing_left(env, p)
