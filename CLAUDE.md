# Pitwall: rules for every Claude session

Pitwall is a LAN telemetry hub plus TV dashboard for **sim racing cafes** running F1 25. It is sold by **9T7 Racing** to **non-technical cafe owners**, mostly in India.

- Hub: Python 3.11, FastAPI, SQLite, asyncio UDP, in `hub/simtelemetry` (package name `simtelemetry`).
- TV: React/Vite on a 1920×1080 stage, in `dashboard/`.
- Installer: PyInstaller one-folder exe plus Inno Setup, in `packaging/`.
- Seller-only tools: `factory/`.

## Current work
Read these first, then continue from the first unfinished task:
- the **Pitwall Factory** plan, `docs/superpowers/plans/2026-11-03-factory.md`;
- its spec, `docs/superpowers/specs/2026-11-03-factory-design.md`;
- the progress log, `docs/superpowers/progress-factory.md`.

Earlier binding rulings are in:
- `docs/superpowers/plans/2026-10-15-commercial-readiness.md` (U1–U8, K1–K14);
- `docs/superpowers/plans/2026-10-15-self-checkin.md` (C1–C8, including the amendment that only phone-started sessions can be taken over, after 5 minutes).

## Working rules
- **Commit after each step with all tests passing, then push.** End every commit message with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Work task by task: implement, review against the spec, fix. Record deviations and decisions in the progress log.
- **Ask before big product decisions.** If no human is available (cloud run), choose the safest option that matches the spec, and log it under "Decisions to confirm".
- Tests:
  - `python -m pytest hub -q`
  - `python -m pytest factory -q`
  - `npx vitest run --maxWorkers=2` and `npx tsc -b` in `dashboard/`
  - Keep them all green. WS schema v1 is **additive only**; document changes in `docs/WS_SCHEMA.md`.
- Only stage files you changed (`git add <paths>`), never `git add -A` when other work may be in the tree.

## Product rules (never break)
- **Offline.** Everything works on the cafe LAN with no internet: no CDNs or online calls. Licences are offline too.
- **Plain English** in every owner, staff, guest and installer text. No jargon ("UDP", "WS", "secret", "500", "[features]", stack traces). Quote the game's own setting labels where needed.
- **The TV never shows IP addresses, warnings or technical diagnostics.**
- **Every feature can be switched off** in `[features]`; new behaviour gets a flag.
- **The product name comes only from `hub/simtelemetry/brand.py`** (`test_no_hardcoded_name.py` enforces this).
- **No F1/F2/F3 logos, official F1 fonts, "Formula 1"/"FIA" text, or team/sponsor marks.** Never extract fonts or logos from reference files; redraw our own. The user's supplied wheel artwork and the 9T7 Racing logos are the only exceptions.
- **Phone numbers only with consent.** Guest data stays private: the data folder is readable only by SYSTEM and Administrators.
- **Tournament features are not implemented.** Never promise them.
- **Names:**
  - 16 characters at most;
  - Indic scripts must survive, so keep ZWJ/ZWNJ inside same-script words;
  - the bad-name filter works on whole words, so real names like Lauda pass.
- **Rig setup wording (U1, word for word):** Game Options › Settings › UDP Telemetry Settings: UDP Telemetry On, UDP Broadcast Mode Off, UDP IP Address = the hub PC's address, UDP Port 20777, UDP Send Rate 20Hz, UDP Format 2025.
- **Licences (factory spec):** forever, no expiry, no phone-home. Add-ons (rigs, games, features) are one-time new codes. The limit is soft: racing is never interrupted. Two variants: "9t7" and "unbranded" (still called Pitwall, with no 9T7 marks anywhere).
- **Pricing:** the 9T7 retail price is ₹20,000 including 4 rigs, plus ₹5,000 for each extra rig. Unbranded builds have a custom price.
- **One codebase. Never fork per cafe.** Per-cafe differences live in the factory profile. A one-off wish becomes a switchable feature.

## Safety
- **Never** run the built installer, `schtasks`, `netsh`, `taskkill`, `powercfg` or `icacls` on the developer's PC.
- **Never** touch port 8000: that is the developer's live hub. Use spare ports and temporary data folders.
- Don't scan or clean the C: drive.
- The factory's private signing key never goes into the repo, a package, a log or a Shipments folder.
- Run long jobs (builds, renders, captures) in the background.

## Cloud sessions (Linux)
- Do **CLOUD** tasks only. LOCAL tasks (Inno Setup compile, Edge PDFs, the real signing key, video render, real installs) are for the user's Windows PC. Mock those parts in tests and list what LOCAL must verify in the progress log.
- Push to the `factory` branch. If the environment only allows its own branch name, push there and write the branch name at the top of the progress log.
