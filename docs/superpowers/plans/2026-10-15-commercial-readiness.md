# Commercial Readiness (Hardening) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Pitwall is sold to non-technical sim racing cafe owners. Make install, setup and day-to-day use foolproof and self-explaining, so that as few support calls as possible arise. Every failure should either fix itself or tell the owner, in plain English, what to do.

**Source:** three read-only audits run on 2026-10-15 (install/first run, rigs/network/TV, day-to-day use) on branch `self-checkin` at f925775. The user asked: "this will be deployed commercially so check whether everything is aligned, makes sense and working and it should be easy to use and install even by non tech people, so cover all edge cases, i need as less support calls to arise as possible".

**Branch:** `hardening`, from `self-checkin` f925775. Version becomes **0.5.0** in the last task.

## Global Constraints (all tasks)

- **Offline and safe:**
  - Offline LAN only; no CDN or online calls.
  - The TV never shows IP addresses, warnings or technical diagnostics.
  - Every new feature that changes behaviour can be switched off in `[features]` (document each new flag in `config/hub.example.toml` and README).
- **Naming:** the product name comes only from `hub/simtelemetry/brand.py`, and `test_no_hardcoded_name.py` must pass.
- **Data:** phone numbers only with consent. Tournament features are not implemented, so nothing may promise them.
- **Schema:** WS schema v1 changes are additive only, and documented in `docs/WS_SCHEMA.md`.
- **Plain English:** all user-facing text on staff, owner, setup, guest and installer screens is plain English with no jargon: no "UDP", "WS", "secret", "[features]", "500", "Failed to fetch" or stack traces. Where a technical setting name must be typed into the game, quote the game's own label, e.g. "UDP IP Address".
- **Commits:** one commit per task (or a few focused commits), all tests passing:
  - `.venv\Scripts\python -m pytest hub -q`;
  - if `dashboard/` is touched, `npx vitest run` and `npx tsc -b` in `dashboard/`.
  - Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Off limits on this PC:**
  - Never run the built installer, schtasks, netsh, taskkill or powercfg on this dev PC.
  - Never touch port 8000.
  - Never scan the C: drive.
  - Use temp data dirs for any manual hub run.

## User rulings (binding, 2026-10-15)

- **U1. Rig telemetry setup is "hub address".** In F1 25: Game Options › Settings › UDP Telemetry Settings: UDP Telemetry **On**, UDP Broadcast Mode **Off**, UDP IP Address = **the hub PC's address**, UDP Port **20777**, UDP Send Rate **20Hz**, UDP Format **2025**. Your Telemetry may stay Restricted.
  - This applies to every rig, including a rig on the hub PC itself, which also uses the hub's network address, not 127.0.0.1.
  - Every doc and page must say exactly this, in this order, with this menu path.
  - The hub must warn loudly (staff and setup pages, never the TV) when its own address changes.
- **U2. Sessions end automatically.**
  - **(a) Closing time:** every open session is ended at the cafe's closing time, through the normal `hub.end_session` path so the card is still made.
  - **(b) Overrun:** a timed session (booking minutes) is ended once its time is up AND the rig has not been DRIVING for 5 minutes.
  - Check-in sessions have no time limit (U5), so only (a) applies to them, plus the existing check-in takeover.
  - **Staff page:** auto-ended sessions show "Ended automatically at closing time" or "Ended automatically: time was up".
  - **Restart:** on hub start, a session left open from a previous business day is ended immediately the same way.
  - **Switch:** `[features] auto_end_sessions = true`.
- **U3. The staff PIN is required.**
  - **Setup:** /setup cannot be saved without a staff PIN. It may equal the owner PIN; say so in the hint.
  - **Existing installs** with an empty staff PIN: the staff page accepts the **owner PIN** until a staff PIN is set, and shows a red banner "Set a staff PIN on the setup page" to whoever unlocks it with the owner PIN.
  - **No longer valid:** a hub with no PIN at all is not a valid state. A fresh install always has an owner PIN, since setup requires one.
- **U4. Guest Wi-Fi.**
  - **Docs and setup page:** "Guests' phones must be on a Wi-Fi that can reach this PC: your main cafe Wi-Fi, or a guest network with 'client/guest isolation' turned off."
  - **Phone test:** /setup and the staff Health tab show a **"Test from your phone"** QR. It opens a tiny hub page `/hello` that says "Your phone can reach {{PRODUCT_NAME}}. Check-in and cards will work." and records the success, so setup shows a green "A phone reached the hub at 14:02".
  - **Advice when it fails:** "If the page doesn't open on a phone on the guest Wi-Fi, guests can't use check-in or cards: use the main Wi-Fi or turn off isolation."
- **U5. Self check-in sessions have no time limit.** No change, but U2(a) closing-time auto-end applies.
- **U6. No TV booking timer.** Remove every claim that the TV shows time left (README, docs/TEST_PLAN.md, docs/WS_SCHEMA.md). The `booking` feed field stays; describe it as for future use and staff tools.
- **U7. No after-hours TV mode.** The TV shows the same screens around the clock. No burn-in work.
- **U8. Unsigned installer for now.**
  - INSTALL.md gets a clear "Windows protected your PC" section: More info → Run anyway, why it appears, and the unknown-publisher UAC prompt.
  - It also covers antivirus: how to allow the Pitwall folder in Windows Security, and that third-party antivirus firewalls (Norton, McAfee, Quick Heal…) need TCP 8000 and UDP 20777 allowed.
  - `packaging/build.ps1` gets an optional signing step. It runs only when env `PITWALL_SIGN_CERT` (a .pfx path) and `PITWALL_SIGN_PASS` are set, using signtool on the exe and the installer, and is skipped silently otherwise. Add VersionInfo (company 9T7 Racing, product name from brand) to the exe and installer.

## Controller rulings (defaults the user didn't need to decide)

- **K1. The hub never refuses to start because of configuration.**
  - **hub.toml:** if it fails to parse or validate, log the exact problem to hub.log and to `<home>/data/last-start-error.txt`, start with defaults, and show a staff and setup warning: "Your settings file has a mistake on line N: … The hub started with default settings." Unknown keys are warnings, not errors.
  - **settings.json:** if corrupt, move it to `settings.json.broken-<timestamp>`, restore the newest copy from the latest backup zip if one exists, otherwise start in setup mode. Raise a staff/setup warning either way.
  - **laps.db:** if corrupt, move it aside, start an empty DB, and tell the owner to restore from backup (staff/setup warning).
  - **Ports:** if the HTTP port is busy, log and write last-start-error.txt, then exit (nothing can show a page). If UDP 20777 is busy, start the web pages anyway, show "Another program is using port 20777 (often SimHub). Close it or change its port", and retry binding every 30 s.
- **K2. Startup errors are always visible.**
  - **Logging:** starts before the config loads (fallback `<home>/data/logs`). Every startup exception goes to hub.log and last-start-error.txt via `log.exception`.
  - **Clean start:** a clean start deletes last-start-error.txt.
- **K3. Nothing goes in hub.toml that an owner needs.**
  - **Backups:** the backup folder (and USB stick) is chosen on the owner page. Store it in settings.json; hub.toml stays as a fallback. A path with backslashes works.
  - **Rig names:** rigs are renamed on the setup page (K5).
  - **Old messages:** every message that says "set X in hub.toml" or "[features]" or "restart" for something owners do routinely is rewritten to point at the page where it's done.
- **K4. Hub address.**
  - **Choosing it:** `lan_address()` keeps its default-route choice. When that is None or loopback, it falls back to the private IPv4 address that rig packets arrive on, or the first private IPv4 address.
  - **Watching it:** the hub stores the address it last showed (`<data>/hub-address.json`). When the current one differs, staff and setup show: "This PC's network address changed from A to B. On every rig set UDP IP Address to B, and reprint the check-in stickers. To stop this happening, reserve the address in your router (see the setup guide)."
  - **Acknowledging:** an "OK, done" button acknowledges it and stores the new address.
  - **Stickers:** the sticker sheet warns when the address is missing or loopback.
- **K5. Rig editor on the setup page** (owner PIN), replacing TOML editing.
  - **Rename:** max 16 characters, shown on TV.
  - **Forget:** removes a rig that no longer exists from rigs.json and its check-in code.
  - **"Same rig as…" (merge):** when a rig PC gets a new address, move the old rig's name, colour, number and check-in code to the new address, and forget the old one.
  - **Identify:** "the rig whose car is moving right now".
  - **Registration:** a rig is registered only after its first **valid** packet. Wrong-format and garbage senders never create a rig. They go to a staff Health line instead: "A PC at <address> is sending telemetry in the wrong format: set UDP Format to 2025."
- **K6. Rig health wording.**
  - **No data:** "Nothing from Rig 3" becomes a checklist: "On Rig 3 check: UDP Telemetry On · UDP IP Address = <hub address> · Port 20777 · Format 2025, then drive out of the garage."
  - **When to warn:** warnings for rigs silent for more than 10 minutes appear only during opening hours, and at most once per rig per day.
  - **Wrong format:** a wrong-format rig shows the state "Wrong game settings", not "In menu".
- **K7. Pause and gaps.**
  - **Driving:** "driving" uses `m_gamePaused` and `is_spectating` (already decoded). A paused or spectating rig is not DRIVING.
  - **Session reset:** a gap in packets must not throw away the rig's live state. Only emit session_changed when the session UID actually changes to a different real session.
- **K8. Staff page safety.**
  - **Rig list refresh:** it must refresh after every action. Fix the `renderRigs` focus early-return so it only skips while an `input`/`select`/`textarea` has focus, and blur buttons after the action.
  - **End session:** asks for confirmation ("End Alex's session on Rig 2? Their card will be made now."), and the button sits apart from the +time buttons.
  - **Other confirmations:** queue "Remove" and team-member "×" confirm too.
  - **Same name:** when a name being started is already driving on another rig, or is on today's board, ask "There's already an Alex today. Same person? Their laps will be on one line." with "Same person" or "Add a letter".
  - **PIN guessing:** after 3 lockouts in an hour from one address, lock that address for 15 minutes. Log it and show it on the owner page ("Someone tried wrong PINs 15 times at 21:40").
  - **Stored PINs:** owner and staff PINs are stored hashed (`hashlib.scrypt` with a salt) in settings.json. Migrate plaintext on load and keep old installs working.
  - **Error banners:** "Can't reach the hub" clears automatically when the hub answers again, and raw "Failed to fetch" or "500" text is replaced with plain sentences.
  - **No card:** ending a session with no clean lap shows "No card this time: no clean lap was completed."
  - **Card panel:** it shows the guest Wi-Fi QR (when set) next to the card QR, with "Join the Wi-Fi first".
- **K9. Day boundary.**
  - **Setup:** opening hours may close after midnight. Closing time can be 00:00–06:00, meaning the next day; show "closes at 02:00 (next day)".
  - **Day start:** `day_start_hour` is derived automatically. It is the closing hour when the cafe closes after midnight, otherwise 0. The hub.toml value overrides only when set explicitly.
  - **Uses:** "today" boards, challenges, analytics and U2(a) closing-time auto-end all use the business day.
- **K10. Guest phone and names.**
  - **iPhone story save:** on iOS, "Save for Instagram story" shows the card image full-screen with "Press and hold the picture, then tap Save to Photos". Android keeps the download.
  - **Name filter:** allow the real surnames Lauda and Dick (whole-word allow-list checked before the blocklist). Strip zero-width, bidi-override and other invisible format characters (Unicode category Cf) in `clean_name`.
  - **Name length:** names are capped at 16 characters (what the TV fits), for staff and check-in.
  - **Card file name:** non-Latin names get `lap-card.png`, not `lap-card-_.png`.
- **K11. Backups.**
  - **Contents:** include `checkin.json` and `data/logos/`.
  - **Warning:** if the last successful backup is more than 2 days old (or none after 2 days of use), the owner page and staff Health show "Last backup: 5 days ago. Check the backup folder or USB stick."
  - **Errors:** backup errors are in plain English ("The USB stick isn't plugged in" when the folder's drive is missing).
- **K12. TV robustness (dashboard).**
  - **Silent connection:** if no WS message arrives for 3 s, close and reconnect. If there is still none after 10 s, treat all rigs as no-data, so the TV shows the waiting or attract screen rather than frozen cars. No text about connections on the LIVE page.
  - **Version change:** the snapshot carries the hub app version. When it changes, or on a schema mismatch, the TV calls `location.reload()` itself, at most once per 60 s. No manual reload is needed.
  - **Clocks:** all time comparisons on the TV use hub time (offset from `ts`), not the TV PC clock.
  - **Wake lock:** request a screen wake lock where the browser allows it (localhost).
  - **Rig labels:** Attract never falls back to a rig's IP. Use `rig.name`.
  - **MULTIVIEW:** supports up to 12 active rigs (2×2, 3×2, 4×2, 4×3 grids). The rig colour palette is extended to 12.
  - **Demo:** the tournament bracket demo ("Hotlap cup") is removed from the demo rotation, because tournaments are not a product feature.
- **K13. Installer and Windows.**
  - **Hub not answering:** WaitForHub waits up to 90 s. If the hub still doesn't answer, the finished page says so in plain English, includes last-start-error.txt's first line if present, and doesn't offer the setup page.
  - **Power:** a new task "Keep this PC awake (recommended for the hub and TV PC)", checked by default. When ticked, it sets AC standby, hibernate and monitor timeouts to 0 via powercfg. The hub also calls `SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED)` while it runs, on Windows only.
  - **TV-only install:** a component "This PC only shows the TV (the hub runs on another PC)". It asks for the hub PC's address or name, installs only the TV launcher and shortcut pointing at it, and creates no hub task or firewall rules.
  - **Start-menu shortcuts:**
    - "Show setup code" and "Reset owner PIN": elevated `cmd /k` with a plain explanation;
    - "Open backups folder";
    - "Open logs folder".
  - **TV launcher:** starts hidden. Instead of opening the browser after 120 s, it opens a bundled local `waiting.html` that polls the hub and redirects when it answers, so there is never a browser error page.
  - **Repeat trigger:** the task's `StartBoundary` becomes 2000-01-01.
  - **Packaging:** `[InstallDelete]` of `{app}\_internal` before the files are copied; an `AppMutex` / `SetupMutex`; `hub.example.toml` is always overwritten next to hub.toml.
  - **Upgrades:** the Ready page warns "Install updates when nobody is driving: the hub restarts".
  - **Permissions:** the data folder grants SYSTEM and Administrators full control and Users read and execute, plus modify only on `data/logs`. Check that the TV launcher and any user-run command still work. If a user-run command needs write access, it runs elevated.
  - **schtasks:** the "disabled" check must not depend on Windows' display language. Use the task XML or a COM query.
  - **Finish page:** "already set up" is shown only when settings.json has `setup_done = true`.
- **K14. Docs.**
  - **RIG_SETUP.md** is rewritten for U1. Remove the placeholders and TODOs, and the reference to a missing file. Add a note on SimHub and wheel software: F1 25 sends to one address, so a rig that also runs SimHub should point the game at SimHub and use SimHub's UDP forwarding to the hub address. Explain how.
  - **INSTALL.md** covers:
    - SmartScreen and antivirus (U8);
    - keeping the PC awake;
    - optional Windows automatic sign-in (netplwiz) for a hub PC that also drives the TV;
    - reserving the hub's and the rigs' addresses in the router;
    - guest Wi-Fi (U4);
    - "only one hub per cafe";
    - the TV-only install;
    - the Start-menu shortcuts;
    - a plain restore procedure.
  - **README:**
    - remove "set PIN in hub.toml", the TV timer (U6) and "cloud version" hints;
    - document the new `[features]` flags;
    - align everything with U1–U8 and K1–K13.
  - **TEST_PLAN:** align with the behaviour, add pause, replay and spectate checks, and add tests for U2, U3, U4, K4, K5 and K13.
  - **WS_SCHEMA:** fix the drift (lan_address, rig address and warnings are not shown on the TV) and document new fields.
  - **setup.html and staff.html** rig text matches U1 word for word.

## Tasks

Run Tasks 1–5 sequentially in the main checkout. Task 6 is dashboard-only and may run in parallel in a worktree, then be merged. Task 7 runs after all the others, and Task 8 is last.

1. **Hub start-up and config robustness:** K1, K2, the hub-side keep-awake from K13, and the K8 PIN hashing (settings migration).
2. **Network and rigs:** K4, K5, K6, K7, plus the U1 wording on setup.html and staff.html. Add tests for the address change, rig merge/forget/rename, the valid-packet registration and the pause state.
3. **Sessions and staff page:** U2, U3, K8 (except hashing), K9. Add tests for closing-time and overrun auto-end, auto-end on start-up, cafes that close after midnight, required staff PIN, the owner-PIN fallback and the PIN lockout escalation.
4. **Guests and phones:** U4 (`/hello`, test QR, setup status), K10, and the sticker sheet warning from K4. Add tests.
5. **Backups:** K11 and the K3 backup folder on the owner page. Add tests.
6. **TV dashboard (worktree):** K12. Add vitest coverage.
7. **Installer and packaging:** K13 (except the hub-side keep-awake) and the U8 signing hook and VersionInfo. Build with `packaging/build.ps1` (Inno Setup is installed) **without running the installer**. Bump the version to 0.5.0 everywhere. Inspect the compiled script and output.
8. **Docs alignment:** K14, U6, U8 docs. Grep every doc and page for contradictions with U1–U8 and K1–K13.

After each task: spec and code review, fix rounds, ledger in `.superpowers/sdd/2026-10-15-commercial-readiness/progress.md`. After all tasks: a whole-branch review, then merge into `packager` and push the backup. The user then runs the spare-PC install test (docs/INSTALL-TEST.md, updated for 0.5.0).
