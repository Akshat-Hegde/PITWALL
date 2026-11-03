import datetime as dt
import html
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from factory import docs, pricing
from factory.docs import DocsError, render_html, render_readme
from factory.licence_issue import issue
from factory.profile import FEATURE_LABELS, FEATURES, CafeProfile, HistoryEntry, ProfileStore, Wifi
from simtelemetry import brand, licence, rig_setup
from simtelemetry.config import FeaturesConfig

DAY = dt.date(2026, 11, 3)
KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))     # fixed: the same codes every run
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
U1 = ("Game Options › Settings › UDP Telemetry Settings: UDP Telemetry On, UDP Broadcast Mode Off, "
      "UDP IP Address = the hub PC's address, UDP Port 20777, UDP Send Rate 20Hz, UDP Format 2025")
MARK = re.compile("9t7", re.IGNORECASE)
EVIL = "<script>alert(1)</script>"


def cafe(variant="9t7", rigs=6, **over) -> CafeProfile:
    p = CafeProfile.new("Apex Lounge", variant=variant, rigs=rigs)
    if variant == "unbranded":
        p.set_price(45_000)
    for k, v in over.items():
        setattr(p, k, v)
    return p


def issued(p: CafeProfile, seq=None, licence_id="l-00000000000000aa"):
    return issue(p, KEY, seq=seq, issued=DAY, licence_id=licence_id)


def text_of(page: str) -> str:
    """The page as a reader sees it: no tags, entities decoded, whitespace collapsed."""
    page = re.sub(r"<style>.*?</style>|<svg.*?</svg>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def all_docs(p: CafeProfile, **kw) -> dict[str, str]:
    i = issued(p)
    return {"guide": render_html("guide", p, i, **kw), "certificate": render_html("certificate", p, i, **kw),
            "readme": render_readme(p, i)}


def upgrade_pair(variant="9t7", **change):
    p = cafe(variant, rigs=4)
    p.apply_preset("basic")
    first = issued(p)
    p.history.append(HistoryEntry(pitwall_version="0.6.0", licence_id=first.payload.licence_id, seq=1, date=DAY,
                                  rigs=4, games=list(first.payload.games), features=list(first.payload.features)))
    for k, v in change.items():
        setattr(p, k, v)
    return p, issued(p, licence_id="l-00000000000000bb")


# --- both variants, every document ------------------------------------------------------------------------

@pytest.mark.parametrize("variant", ["9t7", "unbranded"])
def test_every_document_renders_for_both_variants(variant):
    p = cafe(variant)
    for kind, page in all_docs(p).items():
        assert "Apex Lounge" in page, kind
        assert "$" not in page.replace("$$", ""), kind                      # every placeholder filled
        if kind != "readme":
            assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
            assert brand.PRODUCT_NAME in text_of(page)
    p2, up = upgrade_pair(variant, rigs=6)
    assert "Upgrade certificate" in render_html("upgrade_certificate", p2, up, price_inr=10_000)


def test_unbranded_documents_never_name_the_company(tmp_path):
    p = cafe("unbranded", tagline="Fast laps")
    brand_dir = tmp_path / "brand"
    brand_dir.mkdir()
    (brand_dir / "9t7-logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>9T7</text></svg>')
    pages = all_docs(p, brand_dir=brand_dir)
    p2, up = upgrade_pair("unbranded", rigs=6)
    pages["upgrade"] = render_html("upgrade_certificate", p2, up, price_inr=9_000, brand_dir=brand_dir)
    for kind, page in pages.items():
        assert not MARK.search(page), (kind, MARK.findall(page))            # not in text, comments, CSS or title
        assert not docs.vendor_mark_hits(page)
        assert brand.COMPANY not in page
        assert "your supplier" in page, kind


def test_9t7_documents_use_the_logo_file_or_the_company_name(tmp_path):
    p = cafe()
    page = render_html("certificate", p, issued(p), brand_dir=tmp_path)    # no logo file yet
    assert '<div class="wordmark">9T7 Racing</div>' in page
    assert f"{brand.PRODUCT_NAME}, by {brand.COMPANY}" in text_of(page)
    assert f"Contact {brand.COMPANY}" in text_of(render_html("guide", p, brand_dir=tmp_path))

    (tmp_path / "9t7-logo.png").write_bytes(PNG)
    page = render_html("certificate", p, issued(p), brand_dir=tmp_path)
    assert 'class="vendor-logo" src="data:image/png;base64,' in page and 'class="wordmark"' not in page
    (tmp_path / "9t7-logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    assert 'src="data:image/svg+xml;base64,' in render_html("guide", p, brand_dir=tmp_path)

    (tmp_path / "9t7-logo.svg").write_text("not a picture")
    (tmp_path / "9t7-logo.png").write_bytes(b"not a picture either")
    assert 'class="wordmark">9T7' in render_html("guide", p, brand_dir=tmp_path)     # a bad file falls back to the name


def test_brand_readme_tells_the_seller_where_the_logo_goes():
    readme = docs.BRAND_DIR / "README.md"
    assert readme.is_file() and "9t7-logo.svg" in readme.read_text(encoding="utf-8")


def test_the_cafe_logo_is_embedded(tmp_path):
    store = ProfileStore(tmp_path)
    p = cafe("unbranded")
    src = tmp_path / "logo.png"
    src.write_bytes(PNG)
    store.import_logo(p, src)
    for kind in ("guide", "certificate"):
        page = render_html(kind, p, issued(p), logo_dir=store.logo_dir)
        assert '<img class="cafe-logo" src="data:image/png;base64,' in page
        assert "<img" in page and "http" not in re.sub(r'xmlns="http://www.w3.org/2000/svg"', "", page)
    (store.logo_dir / p.logo).unlink()
    with pytest.raises(DocsError, match="logo file is missing"):
        render_html("guide", p, logo_dir=store.logo_dir)


def test_vendor_mark_hits_skips_pictures_and_codes():
    code = "PW1-ab9T7cd.ef"
    text = f'<img src="data:image/png;base64,AA9t7BB=="> {code} plain words'
    assert docs.vendor_mark_hits(text, ignore=[code]) == []
    assert docs.vendor_mark_hits(text + " by 9T7 Racing", ignore=[code])
    assert docs.vendor_mark_hits("<!-- 9t7 -->")


# --- price ------------------------------------------------------------------------------------------------

def price_lines(page: str) -> list[tuple[str, str]]:
    table = page.split("<h2>Price</h2>")[1].split("</table>")[0]
    return [(text_of(th), text_of(td)) for th, td in re.findall(r"<th>(.*?)</th><td class=\"amount\">(.*?)</td>",
                                                                  table, re.S)]


def test_certificate_price_breakdown_for_six_rigs():
    p = cafe(rigs=6)
    assert price_lines(render_html("certificate", p, issued(p))) == [
        (f"{brand.PRODUCT_NAME} licence, including 4 rigs", "₹20,000"),
        ("2 extra rigs at ₹5,000 each", "₹10,000"),
        ("Total", "₹30,000"),
    ]


def test_certificate_with_a_discount_and_its_note():
    p = cafe(rigs=6, discount_note="Opening offer <b>")
    p.set_price(27_500)
    page = render_html("certificate", p, issued(p))
    assert price_lines(page) == [(f"{brand.PRODUCT_NAME} licence, including 4 rigs", "₹20,000"),
                                 ("2 extra rigs at ₹5,000 each", "₹10,000"),
                                 ("Discount", "−₹2,500"), ("Total", "₹27,500")]
    assert "Opening offer &lt;b&gt;" in page


def test_certificate_four_rigs_and_hand_priced_extras():
    p = cafe(rigs=4)
    assert price_lines(render_html("certificate", p, issued(p))) == [
        (f"{brand.PRODUCT_NAME} licence, including 4 rigs", "₹20,000"), ("Total", "₹20,000")]
    p.set_price(1_25_000)
    lines = price_lines(render_html("certificate", p, issued(p)))
    assert ("Other add-ons", "₹1,05,000") in lines and lines[-1] == ("Total", "₹1,25,000")


def test_unbranded_certificate_shows_only_the_agreed_price():
    p = cafe("unbranded", rigs=6)
    assert price_lines(render_html("certificate", p, issued(p))) == [("Agreed price", "₹45,000")]


def test_certificate_needs_a_price():
    p = cafe(rigs=6)
    i = issued(p)
    p.set_price(None)
    with pytest.raises(DocsError, match="Enter the price"):
        render_html("certificate", p, i)
    assert "₹31,000" in render_html("certificate", p, i, price_inr=31_000)


# --- certificate content ------------------------------------------------------------------------------------

def test_certificate_lists_the_licence():
    p = cafe(rigs=6)
    p.apply_preset("basic")
    i = issued(p)
    t = text_of(render_html("certificate", p, i))
    for want in ("Licensed to Apex Lounge", "Licence number l-00000000000000aa", "Date 3 November 2026", "Rigs 6",
                 "Games F1 25", "Licensed forever. Add rigs or games any time.", "not a tax invoice"):
        assert want in t, want
    assert FEATURE_LABELS["moments"] in t and FEATURE_LABELS["self_checkin"] in t
    assert FEATURE_LABELS["events"] not in t                       # basic: not licensed
    assert FEATURE_LABELS["backup_warning"] not in t               # safety switches aren't products
    assert "_" not in t.split("Features")[1].split("Price")[0]     # no flag names


def test_certificate_carries_the_code_and_its_qr():
    p = cafe()
    i = issued(p)
    page = render_html("certificate", p, i)
    assert f'<div class="code">{i.code}</div>' in page
    svg = re.search(r'<div class="qr">(<svg.*?</svg>)</div>', page, re.S)
    assert svg and 'viewBox="' in svg.group(1) and "<path" in svg.group(1)
    assert svg.group(1) == docs.qr_svg(i.code)
    import segno
    assert segno.make(i.code, error="l").version == segno.make(i.code, error="l", micro=False).version   # a big QR
    assert "<script" not in page.lower() and "@import" not in page and "url(" not in page


def test_certificate_refuses_another_cafes_licence():
    other = cafe()
    with pytest.raises(DocsError, match="another cafe"):
        render_html("certificate", cafe(), issued(other))
    with pytest.raises(TypeError):
        render_html("certificate", cafe(), "PW1-just-text")
    with pytest.raises(ValueError):
        render_html("invoice", cafe(), issued(other))


def test_features_all_have_plain_labels():
    assert set(FEATURE_LABELS) == set(FeaturesConfig.model_fields) == set(FEATURES)
    assert all("_" not in label for label in FEATURE_LABELS.values())


# --- escaping -------------------------------------------------------------------------------------------------

def test_cafe_text_is_shown_as_text_not_run():
    p = cafe(name=f"A {EVIL}"[:40], tagline=EVIL, rig_names=["<b>x</b>", "", "<i>"], discount_note=EVIL,
             wifi=Wifi(ssid="<img src=x>", password="12345678"))
    p.set_price(25_000)
    pages = all_docs(p)
    p2, up = upgrade_pair(rigs=6, tagline=EVIL, name=f"A {EVIL}"[:40])
    pages["upgrade"] = render_html("upgrade_certificate", p2, up, price_inr=10_000)
    for kind in ("guide", "certificate", "upgrade"):
        page = pages[kind]
        for raw in ("<script>", "<b>x</b>", "<i>", "<img src=x>"):
            assert raw not in page, (kind, raw)
        assert "&lt;script&gt;" in page, kind
        assert "<script>alert(1)</script>" in text_of(page), kind
    guide = text_of(pages["guide"])
    assert "Rig 1: <b>x</b>; Rig 3: <i>" in guide and "<img src=x>" in guide


# --- the guide ---------------------------------------------------------------------------------------------------

def test_guide_has_the_u1_settings_word_for_word():
    p = cafe(rigs=6)
    t = text_of(render_html("guide", p))
    assert U1 in t
    assert rig_setup.sentence() in t
    assert "Your Telemetry may stay Restricted." in t and "not 127.0.0.1" in t
    for label, value in rig_setup.settings():
        assert f"{label} {value}" in t


def test_guide_follows_spec_2_6():
    p = cafe(rigs=6, wifi=Wifi(ssid="Apex Guests", password="12345678"), rig_names=["Red", "Blue"])
    t = text_of(render_html("guide", p, issued(p)))
    for want in ("Setup guide", "6 rigs", "Your hub address is shown on the setup page", "Owner PIN", "Staff PIN",
                 "Reset owner PIN", "Check-in stickers", "Check-in QR", "Test the guest Wi-Fi from a phone",
                 "Apex Guests", "USB stick", "Use this folder", "Back up now", "Enter new code",
                 "Rig 1: Red; Rig 2: Blue", p.installer_name(), "Contact 9T7 Racing"):
        assert want in t, want
    for never in ("tournament", "Tournament", "UDP port 8000", "localhost", "FIA", "Formula 1", "[features]",
                  "stack trace", "secret"):
        assert never not in t, never
    numbers = [int(n) for n in re.findall(r"<h2>(\d+)\.", render_html("guide", p))]
    assert numbers == list(range(1, len(numbers) + 1))


def test_guide_without_check_in_leaves_out_the_stickers_and_keeps_steps_in_order():
    p = cafe()
    p.features = {**p.features, "self_checkin": False}
    page = render_html("guide", p)
    assert "Check-in stickers" not in page
    numbers = [int(n) for n in re.findall(r"<h2>(\d+)\.", page)]
    assert numbers == list(range(1, len(numbers) + 1))


def test_guide_uses_the_licence_over_the_profile():
    p = cafe(rigs=6)
    i = issued(p)
    p.rigs = 8
    assert "your licence for 6 rigs" in text_of(render_html("guide", p, i))
    assert "your licence for 8 rigs" in text_of(render_html("guide", p))
    assert "1 rig " in text_of(render_html("guide", cafe(rigs=1)))


def test_documents_are_offline_and_use_system_fonts():
    p = cafe()
    for page in (render_html("guide", p), render_html("certificate", p, issued(p))):
        assert not re.search(r"(src|href)=\"https?:", page)
        assert "@font-face" not in page and "fonts.googleapis" not in page and "@import" not in page
        assert "Segoe UI" in page and "@page { size: A4" in page
        for banned in ("Formula1", "Formula 1", "F1 Regular", "Titillium"):
            assert banned not in page


# --- upgrade certificate -----------------------------------------------------------------------------------------

def test_upgrade_lists_only_the_add_ons():
    p, up = upgrade_pair(rigs=6, features={**cafe().features})          # basic -> full, 4 -> 6 rigs
    page = render_html("upgrade_certificate", p, up, price_inr=18_000)
    items = [text_of(li) for li in re.findall(r"<li>(.*?)</li>", page.split("<h2>Add-ons</h2>")[1].split("</ul>")[0])]
    assert items[0] == "2 more rigs (6 in all)"
    assert sorted(items[1:]) == sorted(f"Feature: {FEATURE_LABELS[f]}"
                                       for f in ("events", "head_to_head", "owner", "challenges", "race_podium"))
    assert not any("Game:" in i for i in items)                       # F1 25 was already licensed
    assert FEATURE_LABELS["moments"] not in page                       # already had it
    assert price_lines(page) == [("2 more rigs: 2 rigs at ₹5,000 each", "₹10,000"), ("Other add-ons", "₹8,000"),
                                 ("Total", "₹18,000")]
    assert up.code in page and '<div class="qr"><svg' in page


def test_upgrade_rigs_only_defaults_to_the_list_price():
    p, up = upgrade_pair(rigs=7)
    assert price_lines(render_html("upgrade_certificate", p, up)) == [
        ("3 more rigs: 3 rigs at ₹5,000 each", "₹15,000"), ("Total", "₹15,000")]
    page = render_html("upgrade_certificate", p, up, price_inr=12_000)
    assert ("Discount", "−₹3,000") in price_lines(page)


def test_upgrade_within_the_base_rigs_and_unbranded():
    p = cafe(rigs=2)
    first = issued(p)
    p.history.append(HistoryEntry(pitwall_version="0.6.0", licence_id="l-1", seq=1, date=DAY, rigs=2,
                                  games=["f1_25"], features=list(first.payload.features)))
    p.rigs = 5
    up = issued(p, licence_id="l-00000000000000bb")
    lines = price_lines(render_html("upgrade_certificate", p, up))
    assert lines[0] == ("3 more rigs: 1 rig at ₹5,000 each (the first 4 rigs are included in the base price)",
                        "₹5,000")
    p2, up2 = upgrade_pair("unbranded", rigs=6)
    page = render_html("upgrade_certificate", p2, up2, price_inr=7_000)
    assert price_lines(page) == [("Agreed price", "₹7,000")]
    with pytest.raises(DocsError, match="price of the add-ons"):
        render_html("upgrade_certificate", p2, up2)


def test_upgrade_needs_a_previous_licence_and_an_add_on():
    p = cafe()
    with pytest.raises(DocsError, match="no earlier licence"):
        render_html("upgrade_certificate", p, issued(p))
    p2, same = upgrade_pair()
    with pytest.raises(DocsError, match="adds no rigs, games or features"):
        render_html("upgrade_certificate", p2, same)
    p3, more = upgrade_pair(features={**cafe().features})
    with pytest.raises(DocsError, match="price of the add-ons"):
        render_html("upgrade_certificate", p3, more)                   # features have no list price
    old = HistoryEntry(pitwall_version="0.6.0", licence_id="x", seq=1, date=DAY, rigs=6, games=["f1_25"],
                       features=list(more.payload.features))
    with pytest.raises(DocsError, match="adds no"):
        render_html("upgrade_certificate", p3, more, previous=old)


# --- README ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("variant", ["9t7", "unbranded"])
def test_readme(variant):
    p = cafe(variant, rigs=6)
    text = render_readme(p, issued(p))
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    for want in (p.installer_name(), p.guide_pdf_name(), p.certificate_pdf_name(), docs.VIDEO_NAME, "README.txt",
                 "Hub PC", "licence certificate", "6 rigs and F1 25", "Enter new code",
                 f"{brand.PRODUCT_NAME} for Apex Lounge"):
        assert want in text, want
    if variant == "9t7":
        assert f"Contact {brand.COMPANY}." in text
    else:
        assert "Contact your supplier." in text and not MARK.search(text)
    assert "$" not in text and "<" not in text


# --- Edge and PDF ------------------------------------------------------------------------------------------------------

def fake_edge(tmp_path) -> dict[str, str]:
    env = {"ProgramFiles(x86)": str(tmp_path / "pf86"), "ProgramFiles": str(tmp_path / "pf"),
           "LOCALAPPDATA": str(tmp_path / "local")}
    exe = tmp_path / "pf" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    return env


def test_find_edge(tmp_path):
    with pytest.raises(DocsError) as e:
        docs.find_edge(env={"ProgramFiles(x86)": str(tmp_path / "a"), "ProgramFiles": str(tmp_path / "b")})
    assert str(e.value) == "Microsoft Edge wasn't found. Choose its location in Settings."
    env = fake_edge(tmp_path)
    found = docs.find_edge(env=env)
    assert found == tmp_path / "pf" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    own = tmp_path / "edge.exe"
    own.write_bytes(b"MZ")
    assert docs.find_edge(own, env=env) == own                          # the Settings choice first
    assert docs.find_edge(tmp_path / "gone.exe", env=env) == found      # a stale choice: the standard place
    assert [str(c).replace("\\", "/") for c in docs.edge_candidates({})][:2] == [
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe"]


class Runner:
    def __init__(self, write=b"%PDF-1.7\n...", raise_=None):
        self.write, self.raise_, self.calls = write, raise_, []

    def __call__(self, args, **kw):
        self.calls.append((args, kw))
        assert Path(next(a for a in args if a.startswith("--user-data-dir=")).split("=", 1)[1]).is_dir()
        if self.raise_:
            raise self.raise_
        if self.write is not None:
            Path(next(a for a in args if a.startswith("--print-to-pdf=")).split("=", 1)[1]).write_bytes(self.write)
        return subprocess.CompletedProcess(args, 0)


def page(tmp_path) -> Path:
    path = tmp_path / "my docs" / "guide.html"
    path.parent.mkdir()
    path.write_text("<!doctype html><p>hi</p>", encoding="utf-8")
    return path


def test_html_to_pdf_success(tmp_path):
    env, src, run = fake_edge(tmp_path), page(tmp_path), Runner()
    out = docs.html_to_pdf(src, tmp_path / "out" / ".." / "Setup guide.pdf", runner=run, env=env, timeout=30)
    assert out == (tmp_path / "Setup guide.pdf").resolve() and out.read_bytes().startswith(b"%PDF-")
    (args, kw), = run.calls
    assert args[0] == str(docs.find_edge(env=env))
    for flag in ("--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={out}"):
        assert flag in args
    assert args[-1] == src.resolve().as_uri() and args[-1].startswith("file:///")
    assert kw["timeout"] == 30 and kw["check"] is False
    profile = next(a for a in args if a.startswith("--user-data-dir=")).split("=", 1)[1]
    assert not Path(profile).exists()                                   # the temporary profile is gone


def test_html_to_pdf_missing_edge(tmp_path):
    run = Runner()
    with pytest.raises(DocsError, match="Microsoft Edge wasn't found"):
        docs.html_to_pdf(page(tmp_path), tmp_path / "a.pdf", runner=run, env={"ProgramFiles": str(tmp_path / "x"),
                                                                               "ProgramFiles(x86)": str(tmp_path)})
    assert run.calls == []
    with pytest.raises(DocsError, match="couldn't be started"):
        docs.html_to_pdf(tmp_path / "my docs" / "guide.html", tmp_path / "a.pdf",
                         runner=Runner(raise_=FileNotFoundError()), env=fake_edge(tmp_path))


@pytest.mark.parametrize("written", [None, b"", b"<html>not a pdf"])
def test_html_to_pdf_no_or_empty_output(tmp_path, written):
    env, src = fake_edge(tmp_path), page(tmp_path)
    old = tmp_path / "a.pdf"
    old.write_bytes(b"%PDF-1.4 an old one")                              # never mistaken for the new one
    with pytest.raises(DocsError) as e:
        docs.html_to_pdf(src, old, runner=Runner(write=written), env=env)
    assert str(e.value) == docs.PDF_FAILED and not old.exists()


def test_html_to_pdf_timeout(tmp_path):
    env, src = fake_edge(tmp_path), page(tmp_path)
    run = Runner(raise_=subprocess.TimeoutExpired("msedge", 5))
    with pytest.raises(DocsError, match="took too long"):
        docs.html_to_pdf(src, tmp_path / "a.pdf", runner=run, env=env, timeout=5)
    assert not (tmp_path / "a.pdf").exists()


def test_write_pdf_from_rendered_html(tmp_path):
    env = fake_edge(tmp_path)
    p = cafe()
    seen = {}

    def run(args, **kw):
        seen["html"] = Path(url2pathname(urlparse(args[-1]).path)).read_text(encoding="utf-8")
        return Runner()(args, **kw)

    out = docs.write_pdf(render_html("guide", p), tmp_path / "g.pdf", work_dir=tmp_path, runner=run, env=env)
    assert out.read_bytes().startswith(b"%PDF-") and "Setup guide" in seen["html"]
    assert [x.name for x in tmp_path.iterdir() if x.name.startswith("doc-")] == []     # temporary page removed


def test_price_helpers_agree_with_pricing():
    b = pricing.breakdown(6, 30_000)
    assert "₹10,000" in docs.price_rows(b) and "Total" in docs.price_rows(b)
    assert docs.long_date(dt.date(2027, 1, 9)) == "9 January 2027"
    assert licence.game_name("f1_25") == rig_setup.GAME
