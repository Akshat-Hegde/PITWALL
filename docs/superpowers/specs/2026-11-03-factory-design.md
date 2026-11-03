# Pitwall Factory: per-cafe builds, licences and ship-ready packages

**Status:** design approved in conversation on 2026-11-03; this spec awaits the user's review.
**Owner:** Akshat Hegde (9T7 Racing).
**Branch:** `factory`, from `hardening` / `packager` ab915ae.

## 1. Goal

The seller (the user) can produce a **ready-to-ship Pitwall package for each cafe** in a few minutes, from one form. Two things are true at the same time:

- **There is one Pitwall.** Every fix and feature is made once, in this repo.
- **Each cafe gets its own configured installer.**

Both sides must be seamless and robust:
- **For the seller:** building, previewing, rebuilding and upgrading cafes.
- **For the cafe:** a fresh install comes up already branded and configured, and nothing the seller ships can break a running cafe.

### What the user decided (binding)

- **F1. Configuration model.** One codebase. Each cafe is a small **profile**, and the factory bakes the profile into that cafe's installer. Per-cafe code forks and copied folders are explicitly rejected. A wish that only one cafe has becomes an optional, switchable feature in the main code, sold as an add-on.
- **F2. Configurable per cafe:**
  - branding: name, tagline, logo, accent colour, guest Wi-Fi;
  - rigs: count and optional names;
  - games;
  - features on or off;
  - a licence.
- **F3. Licences are forever.**
  - Whatever a cafe buys works forever: there is no expiry, no update-plan date and no phone-home.
  - Extra rigs, extra games and extra features are **one-time paid add-ons**, delivered as a new licence code. The cafe enters it on the owner page; no reinstall.
- **F4. Soft limit.**
  - Beyond the licensed rig count, extra rigs still record laps.
  - The TV shows only the licensed rigs. Staff and owner pages say plainly that the licence covers N rigs and to contact the supplier.
  - Racing is never interrupted.
  - Unlicensed features are simply off, as with `[features]` flags today.
- **F5. Two branding variants**, chosen per cafe:
  - **9T7 Racing:** the product says "Pitwall, by 9T7 Racing" where it does today, plus the installer publisher, guide, certificate and video.
  - **Unbranded:** still called **Pitwall**, but every 9T7 Racing mark is removed: TV, pages, installer publisher and version details, guide PDF, certificate, video and README.
- **F6. Price.**
  - 9T7 variant: auto-filled as ₹20,000 including 4 rigs, plus ₹5,000 per extra rig. Editable for discounts.
  - Unbranded variant: the price is entered by hand; there is no default.
  - The certificate shows the agreed price.
- **F7. Package contents:**
  - the cafe installer;
  - a personal setup guide (PDF);
  - the guide video (branded or unbranded to match);
  - a licence certificate with the price (PDF);
  - a README.
- **F8. Factory UI:** a simple Windows form app, not a web page or a command line.
- **F9. Preview:** a button that opens that cafe's TV, staff page and phone check-in on the seller's PC, using the cafe's profile and demo cars, before building.

## 2. Architecture

```
factory/ (seller's PC only)                    hub/simtelemetry/ (every cafe)
├── app.py      Tk form app                    ├── licence.py   verify + entitlements
├── profile.py  cafe profile model + checks    ├── provision.py apply a baked-in profile on fresh install
├── keys.py     signing key create/load/backup ├── (setup/owner/staff/feed changes)
├── licence_issue.py  sign licence codes       └── brand.py     COMPANY stays; vendor mark from licence
├── build.py    package pipeline (calls build.ps1 / ISCC)
├── docs.py     guide + certificate HTML → PDF (Edge headless)
└── preview.py  run hub --demo with the profile, open pages
```

The Pitwall program (the PyInstaller output in `dist\Pitwall\`) is built **once per Pitwall version**. A cafe build only recompiles the **Inno Setup installer**, which takes about a minute. The cafe's `profile.json` and `licence.txt` are passed in as files baked into the installer.

### 2.1 The cafe profile (`factory/profile.py`)

The profile is a JSON file, one per cafe, stored at `<Shipments>\profiles\<slug>.json`. It is validated with pydantic, like the hub's settings.

| Field | Rules |
|---|---|
| `cafe_id` | Stable random id, created once. The licence binds to it. |
| `name` | 1–40 characters. |
| `tagline` | Optional, ≤ 60 characters. |
| `logo` | Path to a PNG, JPEG or WebP under 1 MB, copied into the profile folder. |
| `accent` | One of the setup page's colours. |
| `wifi` | Optional: SSID, password and security, as on /setup. |
| `hours` | Optional: opens and closes (next-day closing allowed), as on /setup. |
| `rigs` | 1–24. |
| `rig_names` | Optional list, ≤ 16 characters each. |
| `games` | `["f1_25"]` today. The list is driven by the adapters that actually exist, so a game Pitwall can't read cannot be chosen. |
| `features` | A map of the `[features]` flag names, so it stays in sync with `FeaturesConfig` automatically. "Full" and "Basic" presets are available. |
| `variant` | `"9t7"` or `"unbranded"`. |
| `price_inr` | Required. Auto-filled for 9t7 (editable), blank for unbranded. |
| `discount_note` | Optional. |
| `contact` | Name, phone and city: **seller's records only, never baked into the installer or the licence.** |
| `history[]` | One entry per build, appended by the factory: Pitwall version, licence id, date, price, package path. |

The checks are plain English ("Choose a logo under 1 MB", "An unbranded build needs a price") and are shown next to the fields. Building is impossible while any check fails.

### 2.2 Licences

**Format.** A licence is one copy-pasteable line:
- It starts with `PW1-`.
- It contains a base64url payload, a `.`, then a base64url Ed25519 signature.
- The same text is written to `licence.txt`.

**Payload (JSON):**
- `v`: 1
- `licence_id`: random
- `cafe_id`
- `cafe_name`
- `rigs`
- `games`
- `features`: the list of features that are on
- `variant`
- `issued`: an ISO date
- `seq`: increases with each licence for the same cafe

**Keys** (`factory/keys.py`):
- On first run the factory creates an Ed25519 key pair in `%APPDATA%\PitwallFactory\keys\`. The private key file is readable only by the user's account, and is **never** put into the repo, a package or the Shipments folder.
- The public key is committed in `hub/simtelemetry/licence_pubkey.py`, generated by the factory's "Set up keys" step. A test checks that it is a valid key.
- The factory shows a red "Back up your signing key" banner until the user confirms a copy, for example by clicking "Copy key to…" and choosing a USB drive.
- If the private key is lost, new keys can be made. Existing cafes keep working, but their add-on codes would need the new key's Pitwall build. The banner and the README explain this.

**Verification** (`hub/simtelemetry/licence.py`):
- The hub verifies the signature with the public key, using the `cryptography` package (a new dependency; PyInstaller supports it).
- The result is an `Entitlements` object: rigs, games, features, variant and cafe name.

**Storage on the cafe PC:**
- The licence lives in `<data>\licence.txt`, readable only by SYSTEM and Administrators (the existing data ACL), and is included in backups.
- A new code entered on the owner page is accepted only if it:
  - verifies;
  - is for the cafe this PC belongs to: the `cafe_id` in `cafe.json`, else the installed licence's; a PC with neither accepts any valid code (first time). Decision 9.2 (user, 2026-11-03): another cafe's code is refused even with no licence yet; a PC changing hands is reinstalled by the seller with the new cafe's package and `/FORCEOTHERCAFE`;
  - has a `seq` higher than the current one.

  So an old code can't be re-entered to downgrade, and another cafe's code is refused with a plain message.

**No licence, or a damaged licence:**
- This happens with dev and source runs, a deleted file, or a corrupt file.
- The hub runs with a **fallback entitlement**: 4 rigs, F1 25, every feature, and the 9T7 variant mark.
- Staff and owner pages show "No licence found. Contact your supplier." The TV is unaffected.
- Demo mode and the test suite use the fallback unless a test supplies a licence.

### 2.3 Hub behaviour with a licence (`licence.py` + existing modules)

- **Rigs (F4):**
  - The licensed rigs are the first N by rig number (rig numbers are stable in rigs.json).
  - Rigs beyond N still record laps and appear on the staff page marked "Not licensed".
  - The feed sends the TV only the licensed rigs (frames, rig_info, boards and moments).
  - Staff Health and the owner page show a warning: "This licence covers N rigs. Rig N+1 and up aren't shown on the TV. Contact {supplier} to add rigs." `{supplier}` is "9T7 Racing" for the 9t7 variant and "your supplier" for unbranded.
- **Features:**
  - The effective flags are the hub.toml flags AND the licensed features. An owner can switch a licensed feature off, but can't switch on one that isn't licensed.
  - Unlicensed features behave exactly like switched-off flags.
- **Games:** an unlicensed game's packets are dropped. Its rigs get a Health line: "This licence doesn't include <game>."
- **Variant:**
  - The 9T7 mark (the TV's "POWERED BY" block and any "by 9T7 Racing" text on pages) shows only for `variant == "9t7"`. The feed tells the TV through a new additive `hub.vendor_mark: bool`, documented in WS_SCHEMA.
  - `brand.COMPANY` stays in the exe's version details, because the program is built once. The **installer's** publisher and version details come from the variant at installer build time.
- **Owner page:** a Licence card shows:
  - "Licensed to {cafe} · {rigs} rigs · {games}";
  - the licence id;
  - an **Enter new code** box with plain errors ("This code is for {other cafe}. This PC belongs to {cafe}.", "This code is older than the one installed", "This code isn't valid: check you copied all of it").

  A new code applies instantly: no restart, and the TV refreshes through the feed.

### 2.4 Provisioning a fresh install (`hub/simtelemetry/provision.py`, installer)

- The installer carries `profile.json`, the logo and `licence.txt` for that cafe. They are passed by build.ps1 or ISCC defines, so `/DProfileDir=…` builds a cafe installer, and with no define it builds the generic one.
- On a **fresh install**, `Pitwall.exe provision <dir>` runs before the hub starts, as SYSTEM via the installer. It:
  - writes the licence;
  - pre-fills settings.json with the cafe name, tagline, logo, colour, Wi-Fi and hours, with **no PINs** and `setup_done = false`, so the owner still visits /setup to choose PINs (the setup code flow stays);
  - writes the rig names into rigs.json, mapped by rig number as rigs appear;
  - writes the hub.toml `[features]` to match the profile.
- On an **upgrade or reinstall**, provisioning **only installs the licence**, and only if it is newer (same cafe, higher seq). It never touches the cafe's own settings, PINs, rig names, logo or Wi-Fi.
- Running a different cafe's installer on a provisioned PC is refused before installing ("This installer is for {other cafe}. This PC belongs to {cafe}."), with an explicit override for the seller.
- The setup page shows the pre-filled values, ready to keep or change, and the licence summary.

### 2.5 Packages (`factory/build.py`)

The output goes to `<Shipments>\<Cafe name> (<date>)\`:
- `Pitwall-Setup-<Cafe>.exe`, with the publisher set by the variant;
- `Setup guide - <Cafe>.pdf`;
- `Licence certificate - <Cafe>.pdf`;
- `Pitwall guide video.mp4`, copied from `factory/assets/video/{9t7,unbranded}.mp4`;
- `README.txt`, written in plain English.

**Pipeline:**
1. Validate the profile.
2. Make sure the Pitwall program is built for the current version (`dist\Pitwall\` plus a stamp file with version and git commit). If it isn't, run the program build once.
3. Issue the licence.
4. Compile the installer with the profile.
5. Render the PDFs.
6. Copy the video.
7. **Verify the package:**
   - re-read the baked licence from the build's staging folder;
   - verify the signature;
   - check cafe_id, rigs and variant;
   - check every file exists and is non-empty;
   - check the unbranded package contains no "9T7" text in its generated files.
8. Append to history.
9. Open the folder.

Any failure stops the build, leaves no half package (it writes to a temp folder and renames at the end) and shows a plain message with a "Show details" log.

**Rebuild all:** rebuilds every profile's package against the current Pitwall version, re-issuing each licence with the same entitlements and seq + 1, and shows a summary table.

**Issue upgrade:** after the rigs, games or features are changed in a profile, this issues a new licence code (seq + 1) and an **upgrade certificate** listing only the add-ons and their price, without rebuilding the installer. The code is shown with a Copy button.

### 2.6 Documents (`factory/docs.py`, `factory/templates/`)

- HTML templates turned into PDF with Microsoft Edge headless, which is already on Windows. The browser path is detected, with a plain error if it is missing.
- **Setup guide:** the cafe name and logo, the steps from INSTALL.md made specific to this cafe:
  - their rig count;
  - the exact F1 25 settings (U1);
  - "your hub address is shown on the setup page";
  - PIN advice;
  - sticker printing;
  - the guest Wi-Fi phone test;
  - backups to a USB stick.
- **Licence certificate:**
  - cafe, licence id, date, rigs, games and features;
  - variant branding;
  - the price breakdown (base, then extra rigs at ₹5,000, then any discount, then the total);
  - "Licensed forever. Add rigs or games any time."
  - The licence code, also printed as a QR code.
- The 9t7 variant uses the 9T7 Racing logo. Unbranded uses only the Pitwall name and the cafe's logo.
- No F1, FIA or team marks anywhere.

### 2.7 Preview (`factory/preview.py`)

- Writes the profile into a temporary data folder.
- Runs `Pitwall.exe` (or the venv's `python -m simtelemetry`) with `run --demo --data-dir <tmp> --http-port <free port ≠ 8000>`.
- Opens the TV, the staff page and a phone-sized check-in window in Edge.
- A **Stop preview** button ends it and deletes the temporary folder.

### 2.8 The form app (`factory/app.py`)

- Built with tkinter, which is in the standard library, so there are no new dependencies for the factory.
- **Left:** the cafe list, with a search box and **New cafe**.
- **Right:** a tabbed form: Cafe, Rigs & games, Features, Branding & price.
- **Bottom buttons:** Preview, Build package, Issue upgrade, Rebuild all, Open shipments folder.
- A status bar.
- Long jobs run in a worker thread, with a progress bar and a Cancel button that cleans up.
- Settings: the Shipments folder (default `Documents\Pitwall Shipments`, outside the repo), the key backup and the Edge path.
- Started from a `Pitwall Factory.cmd` / shortcut that runs `.venv\Scripts\pythonw -m factory`. It isn't packaged for cafes and never ships.

## 3. Robustness checklist

**For the seller:**
- Validation on every field.
- Atomic package writes.
- Every package is verified after it is built.
- Build history.
- Key-backup nagging.
- Shipments live outside the repo (`.gitignore` also blocks `Shipments/`, `*.key` and `profiles/`).
- Every factory function works without the GUI, so it is testable on Linux.

**For the cafe:**
- A provisioned install never overwrites the cafe's own changes.
- A missing or corrupt licence never stops the hub or blanks the TV.
- Licence checks are offline and need no clock.
- Soft limits never interrupt a session.
- Wrong-cafe installers are refused.
- All existing 0.5.0 behaviour and tests stay green.

**Security:**
- The private key never leaves the seller's PC.
- The public key alone can't make licences.
- Licence text is shown with `textContent`.
- The owner-page code entry is behind the owner PIN and the shared lock-out.

## 4. Testing

**CLOUD (Linux, pytest):**
- licence sign, verify and tamper (payload byte flip, wrong key, truncated, wrong prefix);
- seq and cafe rules;
- fallback entitlements;
- soft-limit feed filtering;
- feature AND-ing;
- unlicensed-game drop;
- `vendor_mark` in the feed;
- the owner-page code entry API, including errors and the lock-out;
- provision fresh vs upgrade (never overwrites), and the wrong-cafe refusal logic;
- profile validation and presets;
- price calculation;
- licence issue;
- the package pipeline with ISCC and Edge mocked: atomicity, verification, unbranded "9T7" scan, history;
- template rendering (HTML) for both variants;
- preview command line building;
- the tkinter app smoke test (construct the window under `xvfb` if available, otherwise skip).

**CLOUD (vitest):** the TV hides unlicensed rigs and the vendor mark follows `vendor_mark`.

**LOCAL (Windows):**
- real `build.ps1` and ISCC builds of two sample cafes (one 9t7 with 6 rigs, one unbranded with 4 rigs and custom price);
- Edge PDFs checked by eye;
- Preview checked by eye;
- rendering the unbranded video (brag-output composition with the 9T7 marks swapped for the Pitwall wordmark);
- a spare-PC install of one package: fresh install, then an upgrade code applied on the owner page.

## 5. Out of scope

- Automatic updates or online activation (licences are offline by design).
- Assetto Corsa support. The factory only lists games with adapters; AC appears automatically once it is built.
- Per-cafe video rendering (two fixed videos only).
- A web version of the factory.
- Payment and accounting. The certificate is not a tax invoice; add GST details later if needed.
