"""The package's documents (spec 2.6, F7): setup guide, licence certificate, upgrade certificate and README.

- `render_html(kind, profile, issued, ...)` fills an HTML template in `factory/templates/` with `string.Template`
  (no new dependency). Every piece of cafe text is HTML-escaped; pictures (the cafe's logo, the 9T7 Racing logo)
  are embedded as data URIs and the QR code as inline SVG, so the page needs nothing from outside: no fonts, no
  CDNs, no other files.
- `render_readme(profile, issued, ...)` gives README.txt (plain text, Windows line endings).
- `html_to_pdf(html_path, pdf_path)` prints a page to PDF with Microsoft Edge (already on every Windows PC), run
  headless with its own temporary profile. `find_edge()` finds it. Errors are `DocsError` with plain text.

Branding (spec F5): the "9t7" variant shows the 9T7 Racing logo from `factory/assets/brand/9t7-logo.svg|png`
(or, while that file isn't there, the company name in plain type) and "<product>, by <company>". The "unbranded"
variant shows only the product name and the cafe's own logo; nothing in it names the company. `vendor_mark_hits()`
is the check the build (C10) runs on generated text.

The game settings come from `simtelemetry.rig_setup`, the same words the hub's setup and staff pages show (U1).
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import io
import os
import re
import subprocess
import tempfile
from pathlib import Path
from string import Template
from typing import Any, Callable, Iterable

from simtelemetry import brand, licence, rig_setup
from simtelemetry.provision import logo_kind

from . import pricing
from .profile import DEFAULT_ACCENT, SAFETY_FLAGS, CafeProfile, feature_label, logo_file_problem

TEMPLATES = Path(__file__).with_name("templates")
BRAND_DIR = Path(__file__).with_name("assets") / "brand"
VENDOR_LOGO_FILES = ("9t7-logo.svg", "9t7-logo.png")          # the first one found is used
VENDOR_LOGO_MAX = 2 * 1024 * 1024
KINDS = ("guide", "certificate", "upgrade_certificate")
README_NAME = "README.txt"
VIDEO_NAME = f"{brand.PRODUCT_NAME} guide video.mp4"
PDF_TIMEOUT_S = 120

EDGE_MISSING = "Microsoft Edge wasn't found. Choose its location in Settings."
EDGE_FAILED = "Microsoft Edge couldn't be started. Choose its location in Settings."
PDF_SLOW = "Making the PDF took too long. Close any Microsoft Edge windows and try again."
PDF_FAILED = "Microsoft Edge didn't make the PDF. Try again; if it keeps happening, restart the PC."

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_VENDOR = re.compile(re.escape(brand.COMPANY.split()[0]), re.IGNORECASE)     # "9T7", any case
_DATA_URI = re.compile(r"data:[A-Za-z0-9.+/-]+;base64,[A-Za-z0-9+/=]+")


class DocsError(ValueError):
    """A document couldn't be made; the message is plain English for the factory window."""


# --- small helpers ---------------------------------------------------------------------------------

def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def long_date(day: dt.date) -> str:
    """3 November 2026."""
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _and(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _template(name: str) -> Template:
    return Template((TEMPLATES / name).read_text(encoding="utf-8"))


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def supplier(variant: str) -> str:
    """Who the cafe contacts: the company for the 9t7 variant, "your supplier" for unbranded (spec 2.3)."""
    return brand.COMPANY if variant == "9t7" else "your supplier"


def vendor_mark_hits(text: str, ignore: Iterable[str] = ()) -> list[str]:
    """Every place `text` names the company ("9T7" in any case), for checking unbranded documents. Embedded
    pictures (data URIs) and the given strings (licence codes: random base64 that can spell anything) are skipped."""
    for s in ignore:
        if s:
            text = text.replace(s, " ")
    text = _DATA_URI.sub(" ", text)
    return [text[max(0, m.start() - 30):m.end() + 30] for m in _VENDOR.finditer(text)]


def qr_svg(text: str) -> str:
    """An inline SVG QR code (segno, offline). It scales with its CSS box."""
    import segno

    out = io.BytesIO()
    segno.make(text, error="l", micro=False).save(out, kind="svg", border=2, dark="#000", light="#fff",
                                                  xmldecl=False, svgns=True, omitsize=True, nl=False)
    return out.getvalue().decode("utf-8")


# --- pictures --------------------------------------------------------------------------------------

def vendor_logo(brand_dir: Path | None = None) -> str | None:
    """The 9T7 Racing logo as a data URI, or None while the seller hasn't copied it into factory/assets/brand."""
    folder = Path(brand_dir) if brand_dir is not None else BRAND_DIR
    for name in VENDOR_LOGO_FILES:
        path = folder / name
        try:
            if not path.is_file() or path.stat().st_size > VENDOR_LOGO_MAX:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if name.endswith(".svg") and b"<svg" in data[:4096]:
            return _data_uri(data, "image/svg+xml")
        if name.endswith(".png") and data.startswith(b"\x89PNG\r\n\x1a\n"):
            return _data_uri(data, "image/png")
    return None


def cafe_logo(profile: CafeProfile, logo_dir: Path | None) -> str | None:
    """The cafe's logo as a data URI. None without a logo or without `logo_dir`; DocsError if the file is bad."""
    if not profile.logo or logo_dir is None:
        return None
    path = Path(logo_dir) / profile.logo
    problem = logo_file_problem(path)
    if problem:
        raise DocsError(problem)
    data = path.read_bytes()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(logo_kind(data) or "")
    if mime is None:
        raise DocsError("Choose a PNG, JPEG or WebP picture for the logo.")
    return _data_uri(data, mime)


def _header(cafe: str, tagline: str, variant: str, logo_uri: str | None, brand_dir: Path | None) -> str:
    cafe_html = '<div class="cafe">'
    if logo_uri:
        cafe_html += f'<img class="cafe-logo" src="{logo_uri}" alt="">'
    cafe_html += f'<div><div class="cafe-name">{esc(cafe)}</div>'
    if tagline:
        cafe_html += f'<div class="tagline">{esc(tagline)}</div>'
    cafe_html += "</div></div>"
    if variant == "9t7":
        mark = vendor_logo(brand_dir)
        vendor = (f'<img class="vendor-logo" src="{mark}" alt="{esc(brand.COMPANY)}">' if mark
                  else f'<div class="wordmark">{esc(brand.COMPANY)}</div>')
        vendor += f'<div class="product">{esc(brand.PRODUCT_NAME)}, by {esc(brand.COMPANY)}</div>'
    else:
        vendor = f'<div class="wordmark">{esc(brand.PRODUCT_NAME)}</div>'
    return f'<header class="top">{cafe_html}<div class="vendor">{vendor}</div></header>'


def _css(accent: str) -> str:
    return _template("print.css").substitute(accent=accent if _HEX.match(accent or "") else DEFAULT_ACCENT)


# --- the licence a document is about -----------------------------------------------------------------

def _payload(profile: CafeProfile, issued: Any) -> licence.LicencePayload:
    payload = getattr(issued, "payload", None)
    if not isinstance(payload, licence.LicencePayload) or not isinstance(getattr(issued, "code", None), str):
        raise TypeError("issued must be factory.licence_issue.Issued (code and payload)")
    if payload.cafe_id != profile.cafe_id:
        raise DocsError("This licence is for another cafe, so its documents weren't made.")
    return payload


def _games(ids: Iterable[str]) -> list[str]:
    return [licence.game_name(g) for g in ids]


def _features(names: Iterable[str]) -> list[str]:
    """Plain names of the licensed features, in the hub's order. The safety switches aren't products."""
    return [feature_label(n) for n in names if n not in SAFETY_FLAGS]


def _row(label: str, amount: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f"<tr{c}><th>{label}</th><td class=\"amount\">{amount}</td></tr>"


def _note(profile: CafeProfile) -> str:
    note = _one_line(profile.discount_note)
    return f'<p class="muted small">{esc(note)}</p>' if note else ""


def price_rows(b: pricing.Breakdown) -> str:
    """The certificate's price table: base, extra rigs, other add-ons, discount, total (9t7); the agreed price
    only (unbranded)."""
    inr = pricing.format_inr
    if b.base is None:
        return _row("Agreed price", esc(inr(b.total)), "total")
    rows = [_row(f"{esc(brand.PRODUCT_NAME)} licence, including {_plural(b.base_rigs or 0, 'rig')}",
                 esc(inr(b.base)))]
    if b.extra_rigs:
        rows.append(_row(f"{_plural(b.extra_rigs, 'extra rig')} at {esc(inr(b.extra_rig_price))} each",
                         esc(inr(b.extra_total))))
    if b.other:
        rows.append(_row("Other add-ons", esc(inr(b.other))))
    if b.discount:
        rows.append(_row("Discount", "−" + esc(inr(b.discount))))
    rows.append(_row("Total", esc(inr(b.total)), "total"))
    return "\n".join(rows)


def _issuer(variant: str) -> str:
    return f"Issued by {esc(brand.COMPANY)}. " if variant == "9t7" else ""


# --- the documents -----------------------------------------------------------------------------------

def render_html(kind: str, profile: CafeProfile, issued: Any = None, *, logo_dir: Path | None = None,
                brand_dir: Path | None = None, previous: Any = None, price_inr: int | None = None,
                installer_name: str | None = None) -> str:
    """The HTML of one document.

    kind: "guide", "certificate" or "upgrade_certificate".
    issued: `licence_issue.Issued` (code + payload); required for the certificates. The guide uses it, when given,
        for the licensed rigs and games (else the profile's).
    logo_dir: the profiles' logos folder (`ProfileStore.logo_dir`); without it the cafe's logo is left out.
    brand_dir: where the 9T7 Racing logo is looked for (default factory/assets/brand).
    previous: upgrade only: what the cafe had before (a `HistoryEntry`, or anything with rigs, games and features);
        default the latest history entry before this licence.
    price_inr: certificate: the agreed price (default the profile's); upgrade: the add-ons' price (default, for
        9t7 with only rigs added, the list price of those rigs).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown document {kind!r}")
    payload = _payload(profile, issued) if (issued is not None or kind != "guide") else None
    variant = payload.variant if payload is not None else profile.variant
    cafe = _one_line(payload.cafe_name if payload is not None else profile.name)
    common = {
        "css": _css(profile.accent),
        "header": _header(cafe, _one_line(profile.tagline), variant, cafe_logo(profile, logo_dir), brand_dir),
        "cafe": esc(cafe),
        "product": esc(brand.PRODUCT_NAME),
        "supplier": esc(supplier(variant)),
    }
    if kind == "guide":
        return _guide(profile, payload, common, installer_name)
    assert payload is not None
    common.update(code=esc(issued.code), qr=qr_svg(issued.code), licence_id=esc(payload.licence_id),
                  date=esc(long_date(payload.issued)), issuer=_issuer(variant))
    if kind == "certificate":
        return _certificate(profile, payload, common, price_inr)
    return _upgrade(profile, payload, common, previous, price_inr)


def _guide(profile: CafeProfile, payload: licence.LicencePayload | None, common: dict[str, str],
           installer_name: str | None) -> str:
    rigs = payload.rigs if payload is not None else profile.rigs
    games = _games(payload.games if payload is not None else dict.fromkeys(profile.games))
    features = set(payload.features) if payload is not None else set(profile.features_on())
    wifi = profile.wifi if profile.wifi is not None and profile.wifi.ssid.strip() else None
    rigs_text = _plural(rigs, "rig")

    known = ["name"] + (["logo"] if profile.logo else []) + ["colour"]
    if wifi is not None:
        known.append("guest Wi-Fi")
    if profile.hours is not None:
        known.append("opening hours")
    named = [n for n in profile.rig_names[:rigs] if n and n.strip()]
    if named:
        known.append("rig names")
    prefilled = _and(known)

    settings_rows = "\n".join(f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>"
                              for label, value in rig_setup.settings())
    rig_names = ""
    if named:
        items = [f"Rig {i}: {esc(_one_line(n))}" for i, n in enumerate(profile.rig_names[:rigs], 1)
                 if n and n.strip()]
        rig_names = ("Your rig names are ready and each rig gets its name as soon as it sends data ("
                     + "; ".join(items) + "). Check them on the setup page.")
    else:
        rig_names = "Give each rig its name there."

    step = 6
    stickers = ""
    if "self_checkin" in features:
        stickers = (f'<section>\n<h2>{step}. Check-in stickers</h2>\n'
                    "<p>Open the staff page (Start-menu shortcut <strong>"
                    f"{esc(brand.PRODUCT_NAME)} Staff</strong>) and choose <strong>Check-in QR</strong>: a printable "
                    f"A4 sheet with one QR sticker per rig. Print it, cut out the stickers and stick one on each of "
                    f"your {esc(rigs_text)} where the driver can see it. Guests scan it with their phone to put their "
                    "name on the rig.</p>\n<p>Print the stickers again when you add a rig, when you press "
                    "<strong>New code</strong> for a rig, and when the hub address changes.</p>\n</section>")
        step += 1
    if wifi is not None:
        wifi_text = (f"Test it on your guest Wi-Fi, <strong>{esc(_one_line(wifi.ssid))}</strong>: the TV shows it "
                     "to guests as a QR code.")
    else:
        wifi_text = "Test it on the Wi-Fi your guests use."

    values = dict(common)
    values.update(
        title=esc(f"Setup guide - {_one_line(profile.name)}"),
        rigs_text=esc(rigs_text), game=esc(rig_setup.GAME), games=esc(_and(games)),
        installer=esc(installer_name or profile.installer_name()),
        prefilled=esc(prefilled),
        prefilled_check=esc(f"Your cafe's {prefilled} are already filled in: check them and change anything "
                            "you like."),
        u1=esc(rig_setup.sentence()), settings_rows=settings_rows,
        restricted=esc(rig_setup.RESTRICTED_NOTE), same_pc=esc(rig_setup.SAME_PC_NOTE), rig_names=rig_names,
        stickers=stickers,
        wifi_step=str(step), wifi_text=wifi_text,
        phone_ok=esc(f"Your phone can reach {brand.PRODUCT_NAME}. Check-in and cards will work."),
        tv_step=str(step + 1), backup_step=str(step + 2), licence_step=str(step + 3),
        footer=esc(f"{brand.PRODUCT_NAME} setup guide for {_one_line(profile.name)}."),
    )
    return _template("guide.html").substitute(values)


def _certificate(profile: CafeProfile, payload: licence.LicencePayload, common: dict[str, str],
                 price_inr: int | None) -> str:
    price = profile.price_inr if price_inr is None else price_inr
    if price is None:
        raise DocsError("Enter the price first.")
    try:
        b = pricing.breakdown(payload.rigs, price, payload.variant)
    except ValueError:
        raise DocsError("The price must be a whole number of rupees, 0 or more.") from None
    features = _features(payload.features)
    values = dict(common)
    values.update(
        title=esc(f"Licence certificate - {_one_line(payload.cafe_name)}"),
        rigs=esc(str(payload.rigs)), games=esc(_and(_games(payload.games))),
        features=('<ul class="features">' + "".join(f"<li>{esc(f)}</li>" for f in features) + "</ul>"
                  if features else "The standard live timing screens"),
        price_rows=price_rows(b), price_note=_note(profile),
    )
    return _template("certificate.html").substitute(values)


def previous_entry(profile: CafeProfile, seq: int) -> Any:
    """The latest history entry before licence number `seq` that records what it covered, or None."""
    entries = [h for h in profile.history if h.seq < seq and h.rigs is not None]
    return max(entries, key=lambda h: h.seq) if entries else None


def addons(old: Any, payload: licence.LicencePayload) -> tuple[int, list[str], list[str]]:
    """(rigs added, game names added, feature names added) from `old` (rigs, games, features) to the licence."""
    more_rigs = max(0, payload.rigs - int(old.rigs))
    games = _games(g for g in payload.games if g not in set(old.games))
    features = _features(f for f in payload.features if f not in set(old.features))
    return more_rigs, games, features


def upgrade_price_rows(variant: str, rig_price: int, more_rigs: int, old_rigs: int, total: int) -> str:
    inr = pricing.format_inr
    if variant != "9t7":
        return _row("Agreed price", esc(inr(total)), "total")
    rows = []
    if more_rigs:
        paid = rig_price // pricing.EXTRA_RIG_INR
        label = f"{_plural(more_rigs, 'more rig')}"
        if paid:
            label += f": {_plural(paid, 'rig')} at {esc(inr(pricing.EXTRA_RIG_INR))} each"
        if paid < more_rigs:
            label += f" (the first {pricing.BASE_RIGS} rigs are included in the base price)"
        rows.append(_row(label, esc(inr(rig_price))))
    if total > rig_price:
        rows.append(_row("Other add-ons", esc(inr(total - rig_price))))
    elif total < rig_price:
        rows.append(_row("Discount", "−" + esc(inr(rig_price - total))))
    rows.append(_row("Total", esc(inr(total)), "total"))
    return "\n".join(rows)


def _upgrade(profile: CafeProfile, payload: licence.LicencePayload, common: dict[str, str], previous: Any,
             price_inr: int | None) -> str:
    old = previous if previous is not None else previous_entry(profile, payload.seq)
    if old is None or getattr(old, "rigs", None) is None:
        raise DocsError("This cafe has no earlier licence on record, so there is nothing to upgrade from. "
                        "Build a package instead.")
    more_rigs, games, features = addons(old, payload)
    if not (more_rigs or games or features):
        raise DocsError("The new licence adds no rigs, games or features, so there is no upgrade to list.")
    rig_price = pricing.upgrade_price(int(old.rigs), payload.rigs) if payload.variant == "9t7" else 0
    if price_inr is None:
        if payload.variant != "9t7" or games or features:
            raise DocsError("Enter the price of the add-ons.")
        price_inr = rig_price
    if isinstance(price_inr, bool) or not isinstance(price_inr, int) or price_inr < 0:
        raise DocsError("The price must be a whole number of rupees, 0 or more.")

    items = []
    if more_rigs:
        items.append(f"{_plural(more_rigs, 'more rig')} ({payload.rigs} in all)")
    items += [f"Game: {g}" for g in games]
    items += [f"Feature: {f}" for f in features]
    values = dict(common)
    values.update(
        title=esc(f"Upgrade certificate - {_one_line(payload.cafe_name)}"),
        addons="\n".join(f"  <li>{esc(i)}</li>" for i in items),
        price_rows=upgrade_price_rows(payload.variant, rig_price, more_rigs, int(old.rigs), price_inr),
        price_note=_note(profile),
    )
    return _template("upgrade_certificate.html").substitute(values)


def render_readme(profile: CafeProfile, issued: Any = None, *, installer_name: str | None = None) -> str:
    """README.txt for the package, plain English, with Windows line endings (Notepad)."""
    payload = _payload(profile, issued) if issued is not None else None
    variant = payload.variant if payload is not None else profile.variant
    rigs = payload.rigs if payload is not None else profile.rigs
    games = _games(payload.games if payload is not None else dict.fromkeys(profile.games))
    text = _template("README.txt").substitute(
        product=brand.PRODUCT_NAME,
        cafe=_one_line(payload.cafe_name if payload is not None else profile.name),
        installer=installer_name or profile.installer_name(),
        guide=profile.guide_pdf_name(), certificate=profile.certificate_pdf_name(), video=VIDEO_NAME,
        rigs_text=_plural(rigs, "rig"), games=_and(games), supplier=supplier(variant),
    )
    return "\r\n".join(text.splitlines()) + "\r\n"


# --- PDF with Microsoft Edge ---------------------------------------------------------------------------

def edge_candidates(env: dict[str, str] | None = None) -> list[Path]:
    """Where Windows installs Edge: Program Files (x86), Program Files, then the user's own copy."""
    env = os.environ if env is None else env
    roots = [env.get("ProgramFiles(x86)") or r"C:\Program Files (x86)",
             env.get("ProgramFiles") or r"C:\Program Files"]
    if env.get("LOCALAPPDATA"):
        roots.append(env["LOCALAPPDATA"])
    out: list[Path] = []
    for root in roots:
        path = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if path not in out:
            out.append(path)
    return out


def find_edge(configured: str | Path | None = None, env: dict[str, str] | None = None) -> Path:
    """The Edge program: the one chosen in Settings if it is there, else the standard places. DocsError if none."""
    candidates = ([Path(configured)] if configured else []) + edge_candidates(env)
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    raise DocsError(EDGE_MISSING)


def html_to_pdf(html_path: str | Path, pdf_path: str | Path, edge: str | Path | None = None,
                runner: Callable[..., Any] = subprocess.run, timeout: float = PDF_TIMEOUT_S,
                env: dict[str, str] | None = None) -> Path:
    """Print `html_path` to `pdf_path` with Edge headless (no header or footer), in a throwaway browser profile so
    the seller's own Edge windows and settings don't matter. Checks the PDF was made; DocsError otherwise."""
    exe = find_edge(edge, env)
    src = Path(html_path).resolve()
    pdf = Path(pdf_path).resolve()
    if not src.is_file():
        raise DocsError(PDF_FAILED)
    pdf.unlink(missing_ok=True)                    # never mistake an old PDF for a new one
    kwargs: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "timeout": timeout,
                              "check": False}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryDirectory(prefix="edge-pdf-", ignore_cleanup_errors=True) as profile_dir:
        args = [str(exe), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
                "--no-default-browser-check", "--disable-extensions", f"--user-data-dir={profile_dir}",
                f"--print-to-pdf={pdf}", src.as_uri()]
        try:
            runner(args, **kwargs)
        except subprocess.TimeoutExpired:
            pdf.unlink(missing_ok=True)
            raise DocsError(PDF_SLOW) from None
        except OSError:
            raise DocsError(EDGE_FAILED) from None
    try:
        with open(pdf, "rb") as f:
            ok = f.read(5) == b"%PDF-"
    except OSError:
        ok = False
    if not ok:
        pdf.unlink(missing_ok=True)
        raise DocsError(PDF_FAILED)
    return pdf


def write_pdf(html_text: str, pdf_path: str | Path, work_dir: str | Path | None = None, **kwargs: Any) -> Path:
    """Write `html_text` to a temporary .html file (in `work_dir` if given) and print it to `pdf_path`."""
    with tempfile.TemporaryDirectory(prefix="doc-", dir=work_dir, ignore_cleanup_errors=True) as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(html_text, encoding="utf-8")
        return html_to_pdf(page, pdf_path, **kwargs)
