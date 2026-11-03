"""The factory window's logic (factory/controller.py), without tkinter: the cafe list, edits and Save, problems by
field and tab, prices, presets, the key banner and Set up keys / Copy key to…, which buttons work, and the job
flows (start, progress, cancel, finish, error) with the back end faked."""

import datetime as dt
import threading
from pathlib import Path

import pytest

from factory import build as B
from factory import docs
from factory.docs import EDGE_MISSING, DocsError
from factory import controller as C
from factory.build import BuildCancelled, BuildError, FactorySettings, RebuildRow, UpgradeResult
from factory.controller import Backend, Controller, ControllerError, parse_price
from factory.profile import SAFETY_FLAGS, HistoryEntry, load
from simtelemetry import __version__, brand

DAY = dt.date(2026, 11, 3)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class Opened(list):
    def __call__(self, path):
        self.append(Path(path))


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "repo"
    (repo / "hub" / "simtelemetry").mkdir(parents=True)
    video = tmp_path / "video"
    video.mkdir()
    for name in B.VIDEO_FILES.values():
        (video / name).write_bytes(b"video")
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"MZ")
    settings = FactorySettings(shipments=tmp_path / "Shipments", edge=edge, keys_dir=tmp_path / "keys",
                               repo_root=repo, video_dir=video)

    class Env:
        pass
    e = Env()
    e.tmp, e.repo, e.settings, e.video, e.edge = tmp_path, repo, settings, video, edge
    e.settings_file = tmp_path / "config" / "settings.json"
    e.opened = Opened()
    e.backend = Backend()
    e.make = lambda **kw: Controller(settings, settings_file=e.settings_file, backend=e.backend,
                                     opener=e.opened, today=lambda: DAY, **kw)
    return e


def ready_cafe(c, name="Apex Lounge", rigs="6"):
    c.new_cafe()
    c.set_name(name)
    c.set_rigs_text(rigs)
    return c.profile


def keys_ready(c, env, backed_up=True):
    c.setup_keys()
    if backed_up:
        usb = env.tmp / "usb"
        usb.mkdir(exist_ok=True)
        c.copy_key_to(usb)


def run(c, timeout=10):
    assert c.join(timeout), "the job didn't end"
    return c.poll()


def history(seq=1, rigs=6, features=None, kind="build", variant="9t7"):
    from factory.profile import PRESETS
    return HistoryEntry(kind=kind, pitwall_version=__version__, licence_id=f"l-{seq:016x}", seq=seq, date=DAY,
                        price_inr=30_000, package=f"Apex Lounge ({DAY})", rigs=rigs, games=["f1_25"],
                        features=features or [k for k, v in PRESETS["full"].items() if v], variant=variant)


# --- prices typed by hand -------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,value", [("20000", 20000), ("20,000", 20000), ("₹ 25,000", 25000),
                                        ("Rs. 45,000", 45000), ("1,25,000", 125000), ("30000/-", 30000),
                                        ("15000.00", 15000), ("", None), ("  ", None), ("0", 0)])
def test_parse_price(text, value):
    assert parse_price(text) == value


@pytest.mark.parametrize("text", ["abc", "-5", "20.5", "12e3", "9999999999"])
def test_parse_price_refuses(text):
    with pytest.raises(ControllerError, match="whole rupees"):
        parse_price(text)


# --- list, new, save, select, search -------------------------------------------------------------------------

def test_new_cafe_is_listed_first_until_saved(env):
    c = env.make()
    assert c.rows() == [] and c.profile is None and not c.dirty
    c.new_cafe()
    assert c.rows() == [(C.NEW_KEY, "New cafe", "not saved yet")]
    assert c.dirty and c.leave_prompt() == "Save the changes to this new cafe?"
    c.set_name("Apex Lounge")
    assert c.rows()[0][1] == "Apex Lounge"
    assert c.leave_prompt() == "Save the changes to Apex Lounge?"
    assert c.profile.price_inr == 20_000 and c.price_text == "20000"


def test_save_writes_the_file_and_lists_it(env):
    c = env.make()
    c.new_cafe()
    c.set_name("Apex Lounge")
    path = c.save()
    assert path.is_file() and c.path == path and not c.dirty and c.leave_prompt() is None
    assert c.rows() == [(str(path), "Apex Lounge", "not built yet")]
    assert c.selected_key() == str(path)
    assert load(path).name == "Apex Lounge"
    assert c.status == "Saved."


def test_save_of_a_half_filled_cafe_says_what_is_left(env):
    c = env.make()
    c.new_cafe()
    c.save()
    assert c.status == "Saved. 1 thing to fix before building."


def test_save_refuses_text_the_form_couldnt_use(env):
    c = env.make()
    ready_cafe(c)
    c.set_price_text("lots")
    with pytest.raises(ControllerError, match="whole rupees"):
        c.save()


def test_select_and_search(env):
    c = env.make()
    for name, city in (("Apex Lounge", "Pune"), ("Grid Garage", "Mumbai"), ("Pit Stop", "Pune")):
        c.new_cafe()
        c.set_name(name)
        c.set_contact(city=city)
        c.save()
    assert [r[1] for r in c.rows()] == ["Apex Lounge", "Grid Garage", "Pit Stop"]
    c.set_search("grid")
    assert [r[1] for r in c.rows()] == ["Grid Garage"]
    c.set_search("PUNE")
    assert [r[1] for r in c.rows()] == ["Apex Lounge", "Pit Stop"]
    c.set_search("")
    key = c.rows()[1][0]
    c.select(key)
    assert c.profile.name == "Grid Garage" and not c.dirty and c.selected_key() == key


def test_damaged_file_is_listed_and_refused_plainly(env):
    c = env.make()
    folder = env.settings.shipments / "profiles"
    folder.mkdir(parents=True)
    (folder / "broken.json").write_text("{not json", encoding="utf-8")
    c.refresh_list()
    key, title, note = c.rows()[0]
    assert title == "broken" and note == "This cafe's file is damaged."
    with pytest.raises(ControllerError, match="damaged"):
        c.select(key)


def test_revert_drops_changes(env):
    c = env.make()
    ready_cafe(c)
    c.save()
    c.set_name("Other")
    assert c.dirty
    c.revert()
    assert c.profile.name == "Apex Lounge" and not c.dirty
    c.new_cafe()
    c.revert()
    assert c.profile is None and c.rows()[0][1] == "Apex Lounge"


def test_edits_round_trip_through_save(env):
    c = env.make()
    ready_cafe(c)
    c.set_tagline("Race night every Friday")
    c.set_accent("#14b8a6")
    c.set_accent("not a colour")                         # ignored
    c.set_wifi(True, "Apex Guest", "racing123", "WPA")
    c.set_hours(True, 18, 2)
    c.set_contact(name="Ravi", phone="98200 00000", city="Pune")
    c.set_rig_name(0, "Red")
    c.set_rig_name(2, "Blue")
    c.set_feature("challenges", False)
    c.set_discount_note("Opening offer")
    src = env.tmp / "logo.png"
    src.write_bytes(PNG)
    c.choose_logo(src)
    path = c.save()
    p = load(path)
    assert p.tagline == "Race night every Friday" and p.accent == "#14B8A6"
    assert (p.wifi.ssid, p.wifi.password, p.wifi.security) == ("Apex Guest", "racing123", "WPA")
    assert (p.hours.open_hour, p.hours.close_hour) == (18, 2)
    assert (p.contact.name, p.contact.city) == ("Ravi", "Pune")
    assert p.rig_names == ["Red", "", "Blue"] and p.features["challenges"] is False
    assert p.discount_note == "Opening offer" and p.logo and c.logo_preview_path() is not None
    assert c.problems() == {}
    c.set_wifi(False)
    c.set_hours(False)
    c.clear_logo()
    assert c.profile.wifi is None and c.profile.hours is None and c.logo_path() is None


def test_rig_name_slots_follow_the_rig_count(env):
    c = env.make()
    ready_cafe(c, rigs="3")
    assert c.rig_name_slots() == ["", "", ""]
    c.set_rig_name(4, "Extra")                            # beyond the count: shown, so it can be cleared
    assert c.rig_name_slots() == ["", "", "", "", "Extra"]
    assert c.problems()["rig_names"] == ["Rig 5 has a name, but the cafe has 3 rigs. Clear the name or add rigs."]
    c.set_rig_name(4, "")
    assert c.profile.rig_names == [] and "rig_names" not in c.problems()


def test_bad_logo_is_refused_plainly(env):
    c = env.make()
    ready_cafe(c)
    bad = env.tmp / "logo.gif"
    bad.write_bytes(b"GIF89a....")
    with pytest.raises(ControllerError, match="PNG, JPEG or WebP"):
        c.choose_logo(bad)


# --- problems next to the fields ----------------------------------------------------------------------------

def test_problems_map_to_fields_and_tabs(env):
    c = env.make()
    c.new_cafe()
    assert c.problems() == {"name": ["Enter the cafe's name."]}
    assert c.tab_problems() == {"Cafe": 1, "Rigs & games": 0, "Features": 0, "Branding & price": 0}
    assert c.tab_title("Cafe") == "Cafe (1 to fix)" and c.tab_title("Features") == "Features"
    c.set_name("Apex")
    c.set_wifi(True, "", "")
    c.set_rigs_text("lots")
    c.set_price_text("cheap")
    c.set_game("f1_25", False)
    probs = c.problems()
    assert probs["wifi"] == ["Enter the Wi-Fi name, or leave the guest Wi-Fi out."]
    assert probs["rigs"] == [C.RIGS_BAD]
    assert probs["price_inr"] == [C.PRICE_BAD]
    assert probs["games"] == ["Choose at least one game."]
    assert c.tab_problems() == {"Cafe": 1, "Rigs & games": 2, "Features": 0, "Branding & price": 1}
    c.set_rigs_text("30")
    assert c.problems()["rigs"] == ["Choose 1 to 24 rigs."]
    c.set_rigs_text("6")
    c.set_price_text("30000")
    c.set_game("f1_25", True)
    c.set_wifi(False)
    assert c.problems() == {}


def test_every_field_has_a_tab():
    from factory.profile import CafeProfile
    fields = set(CafeProfile.model_fields) - {"v", "price_auto", "history"}
    assert fields <= set(C.FIELD_TAB)
    assert set(C.FIELD_TAB.values()) <= set(C.TABS)


# --- price auto-fill and variants --------------------------------------------------------------------------

def test_list_price_follows_the_rigs_until_a_price_is_typed(env):
    c = env.make()
    ready_cafe(c, rigs="6")
    assert c.profile.price_inr == 30_000 and c.price_text == "30000" and c.profile.price_auto
    assert c.price_note().startswith("List price")
    c.set_price_text("30000")                             # the window re-sending what it shows: still automatic
    assert c.profile.price_auto
    c.set_price_text("25,000")
    assert c.profile.price_inr == 25_000 and not c.profile.price_auto
    c.set_rigs_text("8")
    assert c.profile.price_inr == 25_000 and c.price_text == "25,000"
    assert c.price_note() == "Typed price. The list price is ₹40,000."
    assert c.price_lines() == [("Licence, including 4 rigs", "₹20,000"),
                               ("4 extra rigs at ₹5,000 each", "₹20,000"),
                               ("Discount", "−₹15,000"), ("Total", "₹25,000")]
    c.use_list_price()
    assert c.profile.price_inr == 40_000 and c.price_text == "40000" and c.profile.price_auto


def test_price_lines_small_cafe_and_hand_priced_extras(env):
    c = env.make()
    ready_cafe(c, rigs="2")
    assert c.price_lines() == [("Licence, including up to 4 rigs", "₹20,000"), ("Total", "₹20,000")]
    c.set_price_text("22000")
    assert ("Other add-ons", "₹2,000") in c.price_lines()
    c.set_price_text("x")
    assert c.price_lines() == []
    c.set_price_text("")
    assert c.price_lines() == [("List price", "₹20,000")]


def test_unbranded_has_no_list_price(env):
    c = env.make()
    ready_cafe(c, rigs="6")
    c.set_variant("unbranded")
    assert c.profile.price_inr is None and c.price_text == ""
    assert c.problems()["price_inr"] == ["An unbranded build needs a price."]
    assert c.price_lines() == [] and c.price_note().startswith("Unbranded")
    c.set_price_text("45000")
    assert c.price_lines() == [("Agreed price", "₹45,000")]
    c.use_list_price()                                    # no list price for unbranded: unchanged
    assert c.profile.price_inr == 45_000
    c.set_variant("9t7")                                  # a typed price is kept
    assert c.profile.price_inr == 45_000 and not c.profile.price_auto
    c.set_variant("unbranded")
    c.set_price_text("")
    c.set_variant("9t7")                                  # no price: the list price is filled in again
    assert c.profile.price_inr == 30_000 and c.profile.price_auto and c.price_text == "30000"


def test_variant_switch_keeps_text_the_form_couldnt_use(env):
    c = env.make()
    ready_cafe(c)
    c.set_price_text("abc")
    c.set_variant("unbranded")
    assert c.price_text == "abc" and c.problems()["price_inr"] == [C.PRICE_BAD]
    c.set_variant("bogus")
    assert c.profile.variant == "unbranded"


def test_variant_choices_use_the_brand():
    choices = Controller.variant_choices()
    assert [k for k, _, _ in choices] == ["9t7", "unbranded"]
    assert choices[0][1] == brand.COMPANY and choices[1][1] == "Unbranded"
    assert brand.PRODUCT_NAME in choices[1][2] and brand.COMPANY in choices[1][2]


# --- features and presets ---------------------------------------------------------------------------------

def test_presets_and_safety_flags(env):
    c = env.make()
    ready_cafe(c)
    assert c.preset_name() == "Full"
    c.apply_preset("basic")
    assert c.preset_name() == "Basic" and c.profile.features["owner"] is False
    c.set_feature("owner", True)
    assert c.preset_name() == "Custom"
    for flag in SAFETY_FLAGS:
        c.set_feature(flag, False)                        # ignored: always on
        assert c.profile.features[flag] is True
    rows = {name: (on, locked) for name, _, on, locked in c.feature_rows()}
    assert all(rows[f] == (True, True) for f in SAFETY_FLAGS)
    assert rows["owner"] == (True, False)
    with pytest.raises(ControllerError):
        c.apply_preset("gold")


def test_a_saved_profile_with_a_safety_flag_off_shows_it_on(env):
    c = env.make()
    p = ready_cafe(c)
    flag = sorted(SAFETY_FLAGS)[0]
    p.features = {**p.features, flag: False}
    path = env.settings.store.save(p)
    c.refresh_list()
    c.select(str(path))
    assert c.profile.features[flag] is True


def test_game_rows(env):
    c = env.make()
    ready_cafe(c)
    assert c.game_rows() == [("f1_25", "F1 25", True)]
    c.set_game("ac_evo", True)                            # a game this version can't read shows, to untick
    assert [g for g, _, on in c.game_rows() if on] == ["f1_25", "ac_evo"]
    assert "isn't a game" in c.problems()["games"][0]


# --- keys: banner, Set up keys, Copy key to… -------------------------------------------------------------

def test_banner_through_first_run(env):
    c = env.make()
    assert c.banner() == (C.BANNER_NO_KEYS, ["Set up keys"])
    assert c.actions()["copy_key"].enabled is False
    text = c.setup_keys()
    assert "rebuilt" not in text and "built again" in text and "Copy key to" in text
    assert "hub/simtelemetry/licence_pubkey.py" in text.replace("\\", "/")
    assert (env.repo / "hub" / "simtelemetry" / "licence_pubkey.py").is_file()
    assert c.keys.has_keys and c.keys.trusted and not c.keys.backed_up
    assert c.banner() == (C.BANNER_BACKUP, ["Copy key to…"])
    usb = env.tmp / "usb"
    usb.mkdir()
    msg = c.copy_key_to(usb)
    assert str(usb) in msg and (usb / "signing.key").is_file()
    assert c.banner() is None and c.keys.backed_up
    assert "Last copied to" in c.key_summary() and "lost" in c.key_summary()


def test_set_up_keys_again_only_adds_the_key_to_the_source(env):
    c = env.make()
    keys = env.backend.create_keys(env.settings.keys_dir)
    c.refresh_keys()
    assert c.banner()[0] == C.BANNER_NOT_TRUSTED and c.banner()[1] == ["Set up keys", "Copy key to…"]
    text = c.setup_keys()
    assert text.startswith("Your signing key (key " + keys.fingerprint)
    assert c.keys.trusted


def test_copy_key_never_into_the_repo_or_shipments(env):
    c = env.make()
    c.setup_keys()
    env.settings.shipments.mkdir(parents=True)
    for bad in (env.repo, env.settings.shipments):
        with pytest.raises(ControllerError):
            c.copy_key_to(bad)
    assert not c.keys.backed_up
    with pytest.raises(ControllerError, match="isn't there"):
        c.copy_key_to(env.tmp / "no-drive")


def test_damaged_key_shows_in_the_banner(env):
    c = env.make()
    env.settings.keys_dir.mkdir()
    (env.settings.keys_dir / "signing.key").write_text("junk")
    c.refresh_keys()
    text, buttons = c.banner()
    assert "damaged" in text and buttons == ["Settings"]
    assert "damaged" in c.actions()["build"].reason or c.profile is None


# --- which buttons work -------------------------------------------------------------------------------------

def test_build_needs_a_ready_cafe_and_a_known_key(env):
    c = env.make()
    a = c.actions()
    assert not a["build"].enabled and a["build"].reason == C.NO_CAFE
    assert not a["save"].enabled and a["shipments"].enabled and a["new"].enabled
    c.new_cafe()
    assert c.actions()["build"].reason == "Fix the marked fields first."
    assert c.hint() == "Build package: Fix the marked fields first."
    c.set_name("Apex")
    assert c.actions()["build"].reason == "Set up keys first."
    env.backend.create_keys(env.settings.keys_dir)
    c.refresh_keys()
    assert c.actions()["build"].reason.startswith("Finish Set up keys")
    c.setup_keys()
    assert c.actions()["build"].enabled and c.hint() == "Ready to build."
    assert c.actions()["preview"].enabled and c.actions()["preview"].label == "Preview"
    c.set_price_text("x")
    assert not c.actions()["build"].enabled and not c.actions()["preview"].enabled


def test_build_needs_edge_the_video_and_good_settings(env):
    c = env.make()
    keys_ready(c, env)
    ready_cafe(c)
    assert c.actions()["build"].enabled
    env.settings.edge = None
    env.backend.find_edge = lambda configured=None, env=None: (_ for _ in ()).throw(DocsError(EDGE_MISSING))
    assert c.actions()["build"].reason == EDGE_MISSING
    assert c.edge_text() == "Microsoft Edge wasn't found. Choose msedge.exe."
    env.backend.find_edge = docs.find_edge
    env.settings.edge = env.edge
    (env.video / "9t7.mp4").unlink()
    assert c.actions()["build"].reason == B.VIDEO_MISSING
    c.set_variant("unbranded")
    c.set_price_text("40000")
    assert c.actions()["build"].enabled                   # the unbranded video is there
    env.settings.shipments = env.repo / "Shipments"
    assert "outside the program's source folder" in c.actions()["build"].reason


def test_upgrade_needs_history_and_something_added(env):
    c = env.make()
    keys_ready(c, env)
    p = ready_cafe(c)
    assert c.actions()["upgrade"].reason == "This cafe has no package yet. Use Build package first."
    p.history = [history(rigs=6)]
    assert c.actions()["upgrade"].reason.startswith("Nothing was added")
    c.set_rigs_text("8")
    assert c.actions()["upgrade"].enabled
    assert c.upgrade_default_price() == (10_000, "Price of the add-ons in rupees (the list price is ₹10,000):")
    c.set_rigs_text("4")
    assert "takes away" in c.actions()["upgrade"].reason
    c.set_rigs_text("6")
    c.set_feature("challenges", False)
    p.history = [history(rigs=6, features=[f for f in p.features_on()])]
    c.set_feature("challenges", True)
    assert c.actions()["upgrade"].enabled
    assert c.upgrade_default_price() == (None, "Price of the add-ons in rupees:")


def test_rebuild_all_needs_a_built_cafe(env):
    c = env.make()
    keys_ready(c, env)
    p = ready_cafe(c)
    c.save()
    assert c.actions()["rebuild"].reason == "No cafe has a package yet."
    p.history = [history()]
    c.save()
    assert c.actions()["rebuild"].enabled


# --- jobs ----------------------------------------------------------------------------------------------------

def fake_result(profile, store, path):
    entry = history(seq=profile.next_seq(), rigs=profile.rigs)
    profile.history.append(entry)
    store.save(profile)
    path.mkdir(parents=True)
    return B.BuildResult(path=path, code="PW1-code", licence_id=entry.licence_id, seq=entry.seq,
                         pitwall_version=__version__, entry=entry, details="step log")


def test_build_saves_first_runs_in_a_worker_and_reloads_the_history(env):
    c = env.make()
    keys_ready(c, env)
    ready_cafe(c)
    seen = {}
    main = threading.current_thread()

    def fake_build(profile, settings, runner, keys, cancel, progress, *, store, today):
        seen.update(thread=threading.current_thread(), saved=store.find(profile.cafe_id) is not None, today=today,
                    keys=keys.fingerprint)
        progress(3, 9, "Making the licence")
        return fake_result(profile, store, settings.shipments / "Apex Lounge (2026-11-03)")

    env.backend.build_package = fake_build
    job = c.start_build()
    assert job.kind == "build" and job.total == len(B.BUILD_STEPS)
    notices = run(c)
    assert seen["thread"] is not main and seen["saved"] and seen["today"] == DAY
    assert seen["keys"] == c.keys.fingerprint
    assert c.job is None and len(notices) == 1
    n = notices[0]
    assert n.kind == "info" and n.title == "Package ready" and "Apex Lounge (2026-11-03)" in n.message
    assert n.details == "step log" and n.folder == env.settings.shipments / "Apex Lounge (2026-11-03)"
    assert env.opened == [n.folder]
    assert len(c.profile.history) == 1 and not c.dirty
    assert c.rows()[0][2] == "built 2026-11-03"
    assert c.status == "Package saved: Apex Lounge (2026-11-03)"


def test_progress_and_busy_state(env):
    c = env.make()
    keys_ready(c, env)
    ready_cafe(c)
    go, reported = threading.Event(), threading.Event()

    def fake_build(profile, settings, runner, keys, cancel, progress, *, store, today):
        progress(4, 9, "Making the installer")
        reported.set()
        go.wait(5)
        raise BuildError("The installer couldn't be made.", "ISCC said no")

    env.backend.build_package = fake_build
    c.start_build()
    assert reported.wait(5)
    assert c.poll() == []
    assert (c.job.done, c.job.total, c.job.text) == (4, 9, "Making the installer")
    assert c.status == "Making the installer" and c.hint() == "Making the installer"
    a = c.actions()
    assert all(not a[k].enabled for k in ("new", "save", "preview", "build", "upgrade", "rebuild", "settings",
                                          "setup_keys", "copy_key"))
    assert a["cancel"].enabled and a["shipments"].enabled and a["build"].reason == C.BUSY
    for edit in (lambda: c.set_name("x"), c.save, c.new_cafe, c.start_build, c.setup_keys,
                 lambda: c.copy_key_to(env.tmp)):
        with pytest.raises(ControllerError, match="Wait for the current job"):
            edit()
    assert c.close_prompt()
    go.set()
    (n,) = run(c)
    assert n.kind == "error" and n.message == "The installer couldn't be made." and n.details == "ISCC said no"
    assert c.status == "Build package stopped." and c.close_prompt() is None
    assert not c.actions()["cancel"].enabled


def test_cancel_cleans_up_and_says_so(env):
    c = env.make()
    keys_ready(c, env)
    ready_cafe(c)
    started = threading.Event()

    def fake_build(profile, settings, runner, keys, cancel, progress, *, store, today):
        started.set()
        assert cancel.wait(5)
        raise BuildCancelled(B.CANCELLED, "cancelled at step 4")

    env.backend.build_package = fake_build
    c.start_build()
    assert started.wait(5)
    c.cancel_job()
    assert c.job.cancelling and not c.actions()["cancel"].enabled
    assert c.status.startswith("Cancelling")
    (n,) = run(c)
    assert n.kind == "info" and n.message == B.CANCELLED and c.status == B.CANCELLED
    assert c.profile.history == [] and env.opened == []


def test_unexpected_error_is_plain_with_the_trace_in_details(env):
    c = env.make()
    keys_ready(c, env)
    ready_cafe(c)

    def fake_build(*a, **k):
        raise ZeroDivisionError("boom")

    env.backend.build_package = fake_build
    c.start_build()
    (n,) = run(c)
    assert n.kind == "error" and n.message.startswith("Something went wrong")
    assert "ZeroDivisionError" in n.details and "boom" not in n.message


def test_start_refuses_when_the_button_is_off(env):
    c = env.make()
    ready_cafe(c)
    with pytest.raises(ControllerError, match="Set up keys first"):
        c.start_build()
    assert c.job is None


def test_issue_upgrade_flow(env):
    c = env.make()
    keys_ready(c, env)
    p = ready_cafe(c)
    p.history = [history(rigs=6)]
    c.save()
    c.set_rigs_text("7")
    calls = {}

    def fake_upgrade(profile, settings, keys, runner, price, cancel, progress, *, store, today):
        calls.update(price=price, rigs=profile.rigs)
        folder = settings.shipments / "Apex Lounge (2026-11-03) upgrade"
        folder.mkdir(parents=True)
        entry = history(seq=2, rigs=7, kind="upgrade")
        profile.history.append(entry)
        store.save(profile)
        return UpgradeResult(code="  PW1-new.code\n", pdf_path=folder / "x.pdf", folder=folder,
                             licence_id=entry.licence_id, seq=2, price_inr=price, entry=entry, details="log")

    env.backend.issue_upgrade = fake_upgrade
    with pytest.raises(ControllerError, match="whole rupees"):
        c.start_upgrade("five")
    c.start_upgrade("4,000")
    (n,) = run(c)
    assert calls == {"price": 4000, "rigs": 7}
    assert n.kind == "upgrade" and n.code == "PW1-new.code" and "Use this code" in n.message
    assert "₹4,000" in n.message and env.opened == [n.folder] and n.details == "log"
    assert [h.seq for h in c.profile.history] == [1, 2] and not c.dirty


def test_upgrade_price_must_be_given_for_add_on_features(env):
    c = env.make()
    keys_ready(c, env)
    p = ready_cafe(c)
    c.apply_preset("basic")
    p.history = [history(rigs=6, features=p.features_on())]
    c.apply_preset("full")
    with pytest.raises(ControllerError, match="Enter the price of the add-ons"):
        c.start_upgrade("")
    assert c.job is None


def test_upgrade_copy_text_is_the_code_alone():
    r = UpgradeResult(code="\nPW1-abc.def \r\n", pdf_path=Path("x"), folder=Path("y"), licence_id="l", seq=2,
                      price_inr=0, entry=None)
    assert Controller.upgrade_copy_text(r) == "PW1-abc.def"


def test_rebuild_all_summary(env):
    c = env.make()
    keys_ready(c, env)
    p = ready_cafe(c)
    p.history = [history()]
    c.save()
    c.set_name("Apex Lounge 2")                            # unsaved: saved before the rebuild reads the files
    seen = {}

    def fake_rebuild(store, settings, runner, keys, cancel, progress, *, today):
        seen["names"] = [e.title for e in store.list()]
        progress(9, 18, "Apex: Saving the package")
        return [RebuildRow("Apex Lounge 2", "ok", "Built.", settings.shipments / "Apex Lounge 2 (2026-11-03)",
                           "log a"),
                RebuildRow("Grid Garage", "failed", "Use Issue upgrade or Build package for it.", None, "log b"),
                RebuildRow("New One", "skipped", "Not built yet. Use Build package for this cafe.")]

    env.backend.rebuild_all = fake_rebuild
    c.start_rebuild_all()
    (n,) = run(c)
    assert seen["names"] == ["Apex Lounge 2"]
    assert n.kind == "rebuild" and n.message == "Rebuild all: 1 of 3 built."
    assert n.rows == [("Apex Lounge 2", "Built", "Built.", "Apex Lounge 2 (2026-11-03)"),
                      ("Grid Garage", "Failed", "Use Issue upgrade or Build package for it.", ""),
                      ("New One", "Skipped", "Not built yet. Use Build package for this cafe.", "")]
    assert "== Apex Lounge 2\nlog a" in n.details and "== Grid Garage\nlog b" in n.details
    assert n.folder == env.settings.shipments and env.opened == []


def test_rebuild_all_error_is_plain(env):
    c = env.make()
    keys_ready(c, env)
    p = ready_cafe(c)
    p.history = [history()]
    c.save()
    env.backend.rebuild_all = lambda *a, **k: (_ for _ in ()).throw(BuildError("There's no signing key."))
    c.start_rebuild_all()
    (n,) = run(c)
    assert n.kind == "error" and n.message == "There's no signing key." and c.status == "Rebuild all stopped."


class FakePreview:
    def __init__(self):
        self.alive = True
        self.stopped = 0
        self.notes = ["The staff and owner PIN in the preview is 0000."]
        self.details = "Preview folder: /tmp/x"

    @property
    def running(self):
        return self.alive

    def stop(self):
        self.stopped += 1
        self.alive = False


def test_preview_start_and_stop(env):
    c = env.make()
    ready_cafe(c)                                          # no keys needed: the preview says so itself
    pv = FakePreview()
    calls = {}

    def fake_start(profile, settings, keys, *, store):
        calls.update(name=profile.name, keys=keys, same=profile is c.profile)
        return pv

    env.backend.start_preview = fake_start
    c.toggle_preview()
    assert c.job.total == 0                               # a moving bar: no steps known
    (n,) = run(c)
    assert calls == {"name": "Apex Lounge", "keys": None, "same": False}
    assert n.kind == "info" and "0000" in n.message and n.details == pv.details
    assert c.preview is pv and c.actions()["preview"].label == "Stop preview"
    assert c.actions()["preview"].enabled
    assert c.dirty                                        # preview doesn't save the cafe
    c.set_price_text("x")                                 # a cafe with problems can still stop its preview
    assert c.actions()["preview"].enabled
    c.toggle_preview()
    assert run(c) == [] and pv.stopped == 1 and c.preview is None and c.status == "Preview stopped."


def test_preview_that_ends_by_itself_is_cleaned_up(env):
    c = env.make()
    ready_cafe(c)
    pv = FakePreview()
    env.backend.start_preview = lambda profile, settings, keys, *, store: pv
    c.toggle_preview()
    run(c)
    pv.alive = False
    c.poll()
    assert c.preview is None and c.job is not None and c.job.kind == "stop_preview"
    run(c)
    assert pv.stopped == 1 and c.job is None


def test_preview_cancelled_while_starting_is_stopped(env):
    c = env.make()
    ready_cafe(c)
    pv = FakePreview()
    started, go = threading.Event(), threading.Event()

    def fake_start(profile, settings, keys, *, store):
        started.set()
        go.wait(5)
        return pv

    env.backend.start_preview = fake_start
    c.toggle_preview()
    assert started.wait(5)
    c.cancel_job()
    go.set()
    (n,) = run(c)
    assert n.kind == "info" and "cancelled" in n.message and pv.stopped == 1 and c.preview is None


def test_preview_error_shows_details(env):
    from factory.preview import PreviewError
    c = env.make()
    ready_cafe(c)
    env.backend.start_preview = lambda *a, **k: (_ for _ in ()).throw(PreviewError("The preview couldn't start.",
                                                                                   "hub said no"))
    c.toggle_preview()
    (n,) = run(c)
    assert (n.kind, n.title, n.message, n.details) == ("error", "Preview", "The preview couldn't start.",
                                                       "hub said no")


def test_build_and_rebuild_wait_for_the_preview_to_stop(env):
    # The preview may run the built program, which a build replaces (Windows can't replace a running program).
    c = env.make()
    keys_ready(c, env)
    p = ready_cafe(c)
    p.history = [history()]
    c.save()
    assert c.actions()["build"].enabled and c.actions()["rebuild"].enabled
    pv = FakePreview()
    env.backend.start_preview = lambda *a, **k: pv
    c.toggle_preview()
    run(c)
    a = c.actions()
    assert not a["build"].enabled and a["build"].reason == C.STOP_PREVIEW_FIRST
    assert not a["rebuild"].enabled and a["rebuild"].reason == C.STOP_PREVIEW_FIRST
    assert c.hint() == "Build package: Press Stop preview first."
    with pytest.raises(ControllerError, match="Stop preview"):
        c.start_build()
    c.toggle_preview()
    run(c)
    assert c.actions()["build"].enabled and c.actions()["rebuild"].enabled


def test_a_job_that_cant_start_leaves_the_window_usable(env, monkeypatch):
    c = env.make()
    ready_cafe(c)
    pv = FakePreview()
    env.backend.start_preview = lambda *a, **k: pv
    c.toggle_preview()
    run(c)

    def no_thread(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", no_thread)
    with pytest.raises(ControllerError, match="couldn't be started"):
        c.toggle_preview()                                # Stop preview
    assert c.job is None and c.preview is pv              # still running, so it can still be stopped
    pv.alive = False
    assert c.poll() == []                                 # the clean-up job can't start either: stopped here
    assert c.preview is None and c.job is None and pv.stopped == 1


def test_a_failure_while_finishing_a_job_is_shown_and_the_window_is_free(env):
    c = env.make()
    keys_ready(c, env)
    ready_cafe(c)
    env.backend.build_package = lambda *a, **k: object()        # a result without .path
    c.start_build()
    (n,) = run(c)
    assert n.kind == "error" and "end of the job" in n.message and "AttributeError" in n.details
    assert c.job is None and c.actions()["build"].enabled


def test_close_prompt_while_a_short_clean_up_runs(env):
    c = env.make()
    ready_cafe(c)
    pv = FakePreview()
    go = threading.Event()
    pv.stop = lambda: (go.wait(5), setattr(pv, "stopped", pv.stopped + 1))
    env.backend.start_preview = lambda *a, **k: pv
    c.toggle_preview()
    run(c)
    c.toggle_preview()
    assert c.close_prompt() == "The factory is finishing a job. Wait a moment, then close it."
    go.set()
    run(c)
    assert c.close_prompt() is None


def test_shutdown_stops_a_running_preview(env):
    c = env.make()
    ready_cafe(c)
    pv = FakePreview()
    env.backend.start_preview = lambda *a, **k: pv
    c.toggle_preview()
    run(c)
    c.shutdown()
    assert pv.stopped == 1 and c.preview is None


# --- settings and folders ------------------------------------------------------------------------------------

def test_settings_update_saves_and_switches_the_list(env):
    c = env.make()
    ready_cafe(c)
    c.save()
    new = env.tmp / "Other Shipments"
    c.update_settings(str(new), "")
    assert c.settings.shipments == new and c.settings.edge is None and c.profile is None and c.rows() == []
    saved = FactorySettings.load(env.settings_file)
    assert saved.shipments == new and saved.edge is None
    with pytest.raises(ControllerError, match="outside the program's source folder"):
        c.update_settings(str(c.settings.repo_root / "Ship"), "")
    with pytest.raises(ControllerError, match="Choose a Shipments folder"):
        c.update_settings("  ", "")
    assert c.settings.shipments == new


def test_settings_problem_on_load_shows_in_the_status(env):
    env.settings_file.parent.mkdir(parents=True)
    env.settings_file.write_text("{oops", encoding="utf-8")
    c = Controller(settings_file=env.settings_file, backend=env.backend, opener=env.opened)
    assert "couldn't be read" in c.status


def test_open_shipments_makes_the_folder(env):
    c = env.make()
    c.open_shipments()
    assert env.settings.shipments.is_dir() and env.opened == [env.settings.shipments]


def test_edge_text(env):
    c = env.make()
    assert c.edge_text() == f"Using {env.edge}."


def test_open_folder_uses_the_desktop_opener(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(C.subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(C.os, "name", "posix")
    monkeypatch.setattr(C.sys, "platform", "linux")
    C.open_folder(tmp_path)
    assert calls == [["xdg-open", str(tmp_path)]]

    def boom(*a, **k):
        raise OSError("no xdg-open")
    monkeypatch.setattr(C.subprocess, "Popen", boom)
    C.open_folder(tmp_path)                               # never raises


def test_no_network_in_the_window_modules():
    for mod in ("controller.py", "app.py"):
        text = (Path(C.__file__).parent / mod).read_text(encoding="utf-8")
        for word in ("urllib", "socket", "http.client", "requests", "webbrowser"):
            assert f"import {word}" not in text and f"from {word}" not in text, (mod, word)


def test_main_says_plainly_when_tkinter_is_missing(capsys, monkeypatch):
    import builtins

    from factory import __main__ as entry
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "factory.app":
            raise ModuleNotFoundError("No module named 'tkinter'", name="tkinter")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert entry.main() == 1
    out = capsys.readouterr().out
    assert "tcl/tk" in out and "Traceback" not in out


def test_main_message_without_a_console_doesnt_fail(monkeypatch):
    # pythonw (the launcher) has no console: sys.stdout is None. On Windows a message box shows instead.
    from factory import __main__ as entry
    shown = []
    monkeypatch.setattr(entry.sys, "stdout", None)
    monkeypatch.setattr(entry.os, "name", "posix")
    entry._tell("hello")                                   # nothing to print to: no error
    if hasattr(__import__("ctypes"), "windll"):
        return
    import ctypes

    class User32:
        @staticmethod
        def MessageBoxW(_h, text, title, _flags):
            shown.append((text, title))

    monkeypatch.setattr(ctypes, "windll", type("W", (), {"user32": User32})(), raising=False)
    monkeypatch.setattr(entry.os, "name", "nt")
    entry._tell("hello")
    assert shown == [("hello", "Factory")]
