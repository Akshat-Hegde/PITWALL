import datetime as dt
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from factory import profile as prof
from factory.profile import (BASIC_OFF, FEATURES, PRESETS, SAFETY_FLAGS, SLUG_RE, CafeProfile, Contact, Hours,
                             ProfileError, ProfileStore, Wifi, safe_file_name, slugify)
from simtelemetry import adapters, brand, licence, licence_pubkey
from simtelemetry.config import FeaturesConfig
from simtelemetry.core.settings import ACCENT_SWATCHES
from simtelemetry.provision import BakedProfile, load_baked

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64
WEBP = b"RIFF\0\0\0\0WEBPVP8 " + b"\0" * 64
DAY = dt.date(2026, 11, 3)
SECRET = {"name": "Ravi Kumar", "phone": "+91 98765 43210", "city": "Pune"}


def good(**over) -> CafeProfile:
    p = CafeProfile.new("Apex Lounge", rigs=6)
    p.tagline = "Race the city"
    p.wifi = Wifi(ssid="Apex Guests", password="racing123")
    p.hours = Hours(open_hour=11, close_hour=1)
    p.rig_names = ["Senna", "", "Lauda"]
    p.contact = Contact(**SECRET)
    for k, v in over.items():
        setattr(p, k, v)
    return p


def fields(p: CafeProfile, logo_dir=None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for field, msg in p.problems(logo_dir):
        out.setdefault(field, []).append(msg)
    return out


# --- defaults, presets, features ------------------------------------------------------------------

def test_new_profile_defaults():
    p = CafeProfile.new("Apex Lounge")
    assert prof._CAFE_ID_RE.match(p.cafe_id) and p.cafe_id != CafeProfile.new("Apex Lounge").cafe_id
    assert p.games == list(adapters.registry()) == ["f1_25"]
    assert p.features == PRESETS["full"] and p.preset() == "full"
    assert p.variant == "9t7" and p.rigs == 4 and p.price_inr == 20_000 and p.price_auto
    assert p.accent == ACCENT_SWATCHES[0] and p.problems() == []


def test_features_follow_featuresconfig():
    assert FEATURES == tuple(FeaturesConfig.model_fields)
    p = CafeProfile.model_validate({"features": {"events": False, "gone_feature": True, "battles": "yes"}})
    assert list(p.features) == list(FEATURES)
    assert p.features["events"] is False and p.features["battles"] is True and "gone_feature" not in p.features


def test_basic_preset_names_are_real_flags_and_never_safety_flags():
    assert BASIC_OFF == {"events", "head_to_head", "owner", "challenges", "race_podium"}
    assert BASIC_OFF <= set(FeaturesConfig.model_fields)
    assert SAFETY_FLAGS == licence.NOT_LICENSED_FLAGS and not BASIC_OFF & SAFETY_FLAGS
    for name in PRESETS:
        assert all(PRESETS[name][f] for f in SAFETY_FLAGS)


def test_presets():
    p = CafeProfile.new("Apex", preset="basic")
    assert p.preset() == "basic"
    assert [f for f, on in p.features.items() if not on] == [f for f in FEATURES if f in BASIC_OFF]
    p.features = {**p.features, "auto_end_sessions": False, "events": True}
    assert p.preset() is None
    p.apply_preset("basic")
    assert p.features["auto_end_sessions"] is True and p.features["events"] is False
    p.apply_preset("full")
    assert all(p.features.values())
    with pytest.raises(ProfileError):
        p.apply_preset("gold")


# --- price ----------------------------------------------------------------------------------------

def test_9t7_price_follows_rigs_until_typed():
    p = CafeProfile.new("Apex")
    p.rigs = 6
    assert p.price_inr == 30_000
    p.set_price(27_000)
    p.rigs = 8
    assert p.price_inr == 27_000 and not p.price_auto and p.list_price() == 40_000
    p.use_list_price()
    assert p.price_inr == 40_000 and p.price_auto
    b = p.price_breakdown()
    assert (b.base, b.extra_rigs, b.total) == (20_000, 4, 40_000)


def test_unbranded_price_has_no_default():
    p = CafeProfile.new("Apex", variant="unbranded", rigs=6)
    assert p.price_inr is None and not p.price_auto and p.list_price() is None
    p.use_list_price()
    assert p.price_inr is None
    p.set_price(45_000)
    assert p.price_breakdown().total == 45_000 and p.price_breakdown().base is None
    q = CafeProfile.new("Apex", rigs=6)
    q.variant = "unbranded"            # switching drops the automatic 9t7 price
    assert q.price_inr is None
    r = CafeProfile.new("Apex")
    r.set_price(18_000)
    r.variant = "unbranded"            # a typed price is kept
    assert r.price_inr == 18_000


def test_price_breakdown_needs_a_price():
    with pytest.raises(ProfileError):
        CafeProfile.new("Apex", variant="unbranded").price_breakdown()


# --- every check message --------------------------------------------------------------------------

@pytest.mark.parametrize("change, field, message", [
    ({"name": ""}, "name", "Enter the cafe's name."),
    ({"name": "   "}, "name", "Enter the cafe's name."),
    ({"name": "x" * 41}, "name", "The cafe name can be at most 40 characters."),
    ({"name": "Apex\nLounge"}, "name", "The cafe name must be one line of text."),
    ({"tagline": "x" * 61}, "tagline", "The tagline can be at most 60 characters."),
    ({"tagline": "Race\tthe city"}, "tagline", "The tagline must be one line of text."),
    ({"logo": "../x.png"}, "logo", "The logo file is missing. Choose the logo again."),
    ({"accent": "red"}, "accent", "Choose an accent colour."),
    ({"wifi": Wifi(ssid=" ")}, "wifi", "Enter the Wi-Fi name, or leave the guest Wi-Fi out."),
    ({"wifi": Wifi(ssid="x" * 33, password="racing123")}, "wifi",
     "The Wi-Fi name is too long: at most 32 letters (fewer with accents or emoji)."),
    ({"wifi": Wifi(ssid="Apex", password="short")}, "wifi", "A WPA Wi-Fi password is 8 to 63 characters."),
    ({"wifi": Wifi(ssid="Apex", password="racing123", security="nopass")}, "wifi",
     "An open Wi-Fi network has no password. Clear the password or choose WPA."),
    ({"hours": Hours(open_hour=11, close_hour=11)}, "hours",
     "The closing time must be after the opening time, or between 00:00 and 06:00 for a cafe that closes after "
     "midnight."),
    ({"hours": Hours(open_hour=25, close_hour=3)}, "hours", "Choose an opening and a closing time."),
    ({"rigs": 0}, "rigs", "Choose 1 to 24 rigs."),
    ({"rigs": 25}, "rigs", "Choose 1 to 24 rigs."),
    ({"rig_names": ["x" * 17]}, "rig_names", "Rig 1's name can be at most 16 characters."),
    ({"rig_names": ["Senna", "senna"]}, "rig_names", 'Two rigs are called "senna". Give each rig its own name.'),
    ({"rig_names": ["", "Rig 3"]}, "rig_names", 'Rig 2 can\'t be called "Rig 3": that is another rig\'s number.'),
    ({"rigs": 2, "rig_names": ["", "", "Lauda"]}, "rig_names",
     "Rig 3 has a name, but the cafe has 2 rigs. Clear the name or add rigs."),
    ({"games": []}, "games", "Choose at least one game."),
    ({"games": ["f1_25", "acc"]}, "games",
     f"acc isn't a game this version of {brand.PRODUCT_NAME} can read. Untick it."),
    ({"games": ["f1_25", "f1_25"]}, "games", "A game is listed twice."),
    ({"variant": "unbranded"}, "price_inr", "An unbranded build needs a price."),
    ({"price_auto": False, "price_inr": None}, "price_inr", "Enter the price."),
    ({"price_auto": False, "price_inr": -5}, "price_inr", "The price can't be less than ₹0."),
    ({"discount_note": "x" * 201}, "discount_note", "The discount note can be at most 200 characters."),
    ({"contact": Contact(phone="9" * 81)}, "contact", "The contact's phone number can be at most 80 characters."),
    ({"cafe_id": "c-bad"}, "cafe_id", "This cafe's id is damaged. Make the cafe again with New cafe."),
])
def test_every_check_message(change, field, message):
    p = good()
    assert p.problems() == []
    for k, v in change.items():
        setattr(p, k, v)
    assert message in fields(p).get(field, []), p.problems()


def test_logo_file_checks(tmp_path):
    store = ProfileStore(tmp_path)
    p = good()
    for data in (PNG, JPEG, WEBP):
        src = tmp_path / "pick"
        src.write_bytes(data)
        store.import_logo(p, src)
        assert store.problems(p) == []
    store.logo_path(p).unlink()
    assert fields(p, store.logo_dir)["logo"] == ["The logo file is missing. Choose the logo again."]
    store.logo_path(p).write_bytes(b"GIF89a" + b"\0" * 10)
    assert fields(p, store.logo_dir)["logo"] == ["Choose a PNG, JPEG or WebP picture for the logo."]
    store.logo_path(p).write_bytes(PNG + b"\0" * (1024 * 1024))
    assert fields(p, store.logo_dir)["logo"] == ["Choose a logo under 1 MB."]


def test_import_logo_refuses_with_plain_messages(tmp_path):
    store = ProfileStore(tmp_path)
    p = good()
    big, gif = tmp_path / "big.png", tmp_path / "x.gif"
    big.write_bytes(PNG + b"\0" * (1024 * 1024))
    gif.write_bytes(b"GIF89a")
    for path, msg in ((big, "Choose a logo under 1 MB."), (gif, "Choose a PNG, JPEG or WebP picture for the logo."),
                      (tmp_path / "nope.png", "The logo file is missing. Choose the logo again.")):
        with pytest.raises(ProfileError, match=msg.replace(".", r"\.")):
            store.import_logo(p, path)
    assert p.logo is None and not store.logo_dir.exists()


def test_messages_are_plain_english():
    p = CafeProfile.model_validate({"name": "", "rigs": 0, "accent": "x", "games": [], "variant": "unbranded",
                                    "cafe_id": "zz", "wifi": {"ssid": ""}, "hours": {"open_hour": 30}})
    msgs = [m for _, m in p.problems()]
    assert len(msgs) >= 7
    for m in msgs:
        assert m[0].isupper() and m.endswith(".")
        for word in ("UDP", "None", "Traceback", "validation", "[features]", "pydantic", "Value error"):
            assert word not in m


# --- what leaves the factory --------------------------------------------------------------------

def test_baked_profile_is_exactly_bakedprofile():
    p = good(logo="c-0000-abcd.PNG")
    p.features = {**PRESETS["basic"]}
    p.rig_names = ["Senna", "", "Rig 3", "  Lauda  ", "", ""]
    b = p.baked_profile()
    assert set(b) == set(BakedProfile.model_fields)
    model = BakedProfile.model_validate(b)                      # strict: types must be exact
    assert model.model_dump(mode="json") == b
    assert b["logo"] == "logo.png" and b["accent"] == "#E10600"
    assert b["rig_names"] == ["Senna", None, None, "Lauda"]
    assert b["wifi"] == {"ssid": "Apex Guests", "password": "racing123", "security": "WPA"}
    assert b["hours"] == {"open_hour": 11, "close_hour": 1}
    model.settings()                                            # the settings provisioning would write are valid


def test_baked_features_leave_off_licensed_flags_out():
    """A licensed feature that is off isn't written into hub.toml: the licence keeps it off, and an add-on code
    switches it on with no reinstall. The safety flags are written as set (only hub.toml controls them)."""
    p = good()
    p.apply_preset("basic")
    p.features = {**p.features, "auto_end_sessions": False}
    feats = p.baked_profile()["features"]
    assert not BASIC_OFF & set(feats)
    assert feats["auto_end_sessions"] is False and feats["backup_warning"] is True
    assert all(feats[f] for f in feats if f not in SAFETY_FLAGS)
    pay = p.licence_payload(1, "lic-1", DAY)
    assert set(pay["features"]) == {f for f, on in p.features.items() if on}


def test_licence_payload_validates():
    p = good()
    p.apply_preset("basic")
    pay = p.licence_payload(seq=3, licence_id="lic-0007", issued=DAY)
    parsed = licence.check_payload(licence.encode_payload(pay))
    assert (parsed.cafe_id, parsed.cafe_name, parsed.rigs, parsed.games, parsed.variant, parsed.seq, parsed.issued) \
        == (p.cafe_id, "Apex Lounge", 6, ("f1_25",), "9t7", 3, DAY)
    assert set(parsed.features) == set(FEATURES) - BASIC_OFF
    assert set(pay) == set(licence.LicencePayload.model_fields)


def test_contact_and_price_never_leave_the_factory():
    p = good(discount_note="Friend of Ravi")
    p.set_price(17_777)
    for out in (p.baked_profile(), p.licence_payload(1, "lic-1", DAY)):
        text = json.dumps(out, ensure_ascii=False)
        for secret in (*SECRET.values(), "98765", "17777", "Friend of Ravi"):
            assert secret not in text
        assert "contact" not in out and "price_inr" not in out and "history" not in out


def test_a_baked_folder_provisions(tmp_path, monkeypatch):
    """End to end with the hub: profile.json + logo + a signed licence load in provision.load_baked."""
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", (key.public_key().public_bytes(Encoding.Raw,
                                                                                         PublicFormat.Raw),))
    store = ProfileStore(tmp_path / "Shipments")
    p = good()
    src = tmp_path / "logo.webp"
    src.write_bytes(WEBP)
    store.import_logo(p, src)
    assert store.problems(p) == []
    baked = tmp_path / "baked"
    baked.mkdir()
    (baked / "profile.json").write_text(json.dumps(p.baked_profile(), ensure_ascii=False), encoding="utf-8")
    assert store.copy_logo(p, baked).name == "logo.webp"
    data = licence.encode_payload(p.licence_payload(p.next_seq(), "lic-0001", DAY))
    (baked / "licence.txt").write_text(licence.make_code(data, key.sign(data)), encoding="utf-8")
    b = load_baked(baked)
    assert b.licence is not None and b.licence.payload.cafe_id == p.cafe_id
    assert b.settings.name == "Apex Lounge" and b.logo == (WEBP, ".webp")
    assert b.profile.pending_rig_names() == {1: "Senna", 3: "Lauda"}


def test_indic_rig_and_cafe_names_survive():
    marathi = "र्‍या"                 # the eyelash "rya": ZWJ inside a Devanagari word
    p = good(name="रेसिंग अड्डा", rig_names=[marathi + "न"])
    assert p.problems() == []
    assert p.baked_profile()["rig_names"] == [marathi + "न"]
    assert p.licence_payload(1, "lic-1", DAY)["cafe_name"] == "रेसिंग अड्डा"


# --- names --------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, slug", [("Apex Lounge", "Apex-Lounge"), ("Café Rapide!", "Cafe-Rapide"),
                                        ("  --Pit  Stop--  ", "Pit-Stop"), ("R&D 24/7", "R-D-24-7"),
                                        ("x" * 80, "x" * 40)])
def test_slug(name, slug):
    assert slugify(name, "c-7f3a09c1d2e4b5a6") == slug and SLUG_RE.match(slug)


@pytest.mark.parametrize("name", ["रेसिंग अड्डा", "", "!!!", "🏎️🏁"])
def test_slug_falls_back_to_the_cafe_id(name):
    assert slugify(name, "c-7f3a09c1d2e4b5a6") == "cafe-7f3a09c1"


def test_file_names():
    p = good(name='Apex: "Lounge" <2>?')
    assert p.installer_name() == f"{brand.EXE_NAME}-Setup-Apex-Lounge-2.exe"
    assert p.package_folder_name(DAY) == "Apex Lounge 2 (2026-11-03)"
    assert p.guide_pdf_name() == "Setup guide - Apex Lounge 2.pdf"
    assert p.certificate_pdf_name() == "Licence certificate - Apex Lounge 2.pdf"
    assert good(name="रेसिंग अड्डा").package_folder_name(DAY) == "रेसिंग अड्डा (2026-11-03)"


@pytest.mark.parametrize("text, out", [("CON", "_CON"), ("nul.txt", "_nul.txt"), ("Apex. ", "Apex"),
                                       ("a/b\\c", "a b c"), ("", "fallback"), ("...", "fallback"),
                                       ("x" * 70, "x" * 60), ("Tab\there", "Tab here"), ("Com1", "_Com1")])
def test_safe_file_name(text, out):
    assert safe_file_name(text, "fallback") == out


# --- storage ------------------------------------------------------------------------------------

def test_round_trip(tmp_path):
    store = ProfileStore(tmp_path)
    p = good()
    p.history.append(prof.HistoryEntry(pitwall_version="0.6.0", licence_id="lic-1", seq=1, date=DAY,
                                       price_inr=30_000, package="Apex Lounge (2026-11-03)", rigs=6,
                                       games=["f1_25"], features=p.features_on()))
    path = store.save(p)
    assert path == tmp_path / "profiles" / "Apex-Lounge.json"
    again = prof.load(path)
    assert again == p and again.next_seq() == 2
    assert not list(path.parent.glob("*.tmp"))


def test_draft_saves_and_loads(tmp_path):
    store = ProfileStore(tmp_path)
    p = CafeProfile.model_validate({"name": "", "rigs": 0, "variant": "unbranded"})
    path = store.save(p)
    assert prof.load(path) == p and p.problems()
    assert path.name.startswith("cafe-")


def test_older_profile_file_gets_new_flags(tmp_path):
    p = good()
    data = p.model_dump(mode="json")
    del data["features"]["race_podium"]
    data["features"]["retired_flag"] = False
    data["unknown_key"] = 1
    path = tmp_path / "old.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    q = prof.load(path)
    assert q.features["race_podium"] is True and "retired_flag" not in q.features


def test_list_find_rename_and_same_names(tmp_path):
    store = ProfileStore(tmp_path)
    a, b = good(), good()
    pa, pb = store.save(a), store.save(b)
    assert pa.name == "Apex-Lounge.json" and pb.name == f"Apex-Lounge-{b.cafe_id[2:10]}.json"
    assert store.save(a) == pa and store.save(b) == pb            # saving again keeps the file
    a.name = "Zen Racing"
    pa2 = store.save(a)
    assert pa2.name == "Zen-Racing.json" and not pa.exists() and store.find(a.cafe_id) == pa2
    (store.dir / "broken.json").write_text("{not json", encoding="utf-8")
    entries = store.list()
    assert [e.title for e in entries] == ["Apex Lounge", "Zen Racing", "broken"]
    assert entries[-1].profile is None and entries[-1].error == "This cafe's file is damaged."


def test_load_errors_are_plain(tmp_path):
    with pytest.raises(ProfileError, match="missing"):
        prof.load(tmp_path / "nope.json")
    (tmp_path / "bad.json").write_text(json.dumps({"rigs": "lots"}), encoding="utf-8")
    with pytest.raises(ProfileError, match="damaged"):
        prof.load(tmp_path / "bad.json")


def test_save_failure_is_plain(tmp_path):
    (tmp_path / "profiles").write_text("a file where the folder should be", encoding="utf-8")
    with pytest.raises(ProfileError, match="couldn't be saved"):
        ProfileStore(tmp_path).save(good())


def test_logo_keeps_its_file_when_the_cafe_is_renamed(tmp_path):
    store = ProfileStore(tmp_path)
    p = good()
    src = tmp_path / "l.png"
    src.write_bytes(PNG)
    store.import_logo(p, src)
    assert p.logo.startswith(p.cafe_id) and p.logo.endswith(".png")
    store.save(p)
    p.name = "New Name"
    store.save(p)
    assert store.problems(prof.load(store.find(p.cafe_id))) == []


def test_main_says_plainly_when_the_app_is_missing(capsys, monkeypatch):
    import builtins

    from factory import __main__ as entry
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "factory.app":
            raise ModuleNotFoundError("No module named 'factory.app'", name="factory.app")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert entry.main() == 1
    out = capsys.readouterr().out
    assert "factory window" in out and "Traceback" not in out


def test_factory_is_not_shipped():
    spec = (Path(__file__).resolve().parents[2] / "packaging" / "pitwall.spec").read_text(encoding="utf-8")
    assert '"factory"' in spec
