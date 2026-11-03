# Progress: Pitwall Factory

Plan: `docs/superpowers/plans/2026-11-03-factory.md`. Spec: `docs/superpowers/specs/2026-11-03-factory-design.md`. Branch: `factory`.

Each session starts by reading this log and continues from the first task not marked done. Every finished task gets a line here with its commits, test counts, any deviations, and anything left for LOCAL.

## Baseline
- 2026-11-03: the branch was created from `hardening` ab915ae (Pitwall 0.5.0). The hub has 884 passing tests and the dashboard has 120 (vitest).
- The spec was committed in c2c6927, and the plan in the commit that added this file.

- 2026-11-03 cloud session (Linux, Python 3.13, root): hub `869 passed, 10 skipped, 5 failed`. The 5 failures are pre-existing and environment-only: 4 in `test_backup_folder.py` (Windows drive letters / root ignores folder permissions) and `test_config.py::test_safe_bad_value_uses_that_default_and_keeps_the_rest`. They also fail on `ab915ae` before any factory work; LOCAL should confirm they pass on Windows. Dashboard: 120 vitest pass, `tsc -b` clean. tkinter is not available in the cloud Python, so the app smoke test skips here.

## Tasks
- [x] C1 Licence core
- [x] C2 Licence storage, owner page, backups
- [x] C3 Enforcement
- [ ] C4 Dashboard
- [ ] C5 Provisioning
- [ ] C6 Installer support (static)
- [ ] C7 Factory profile, pricing, presets
- [ ] C8 Keys and licence issue
- [ ] C9 Documents
- [ ] C10 Build pipeline
- [ ] C11 Preview
- [ ] C12 Form app
- [ ] C13 Whole-branch review and LOCAL hand-off list
- [ ] L1–L6 LOCAL (Windows PC)

## Log

- 2026-11-03 **C1 Licence core** (cloud). New `hub/simtelemetry/licence.py`, `hub/simtelemetry/licence_pubkey.py` (`TRUSTED_KEYS = ()` until L1), `hub/tests/test_licence.py` (60 tests); `cryptography>=42` added to `pyproject.toml`. Hub: `929 passed, 10 skipped, 5 failed` (the same 5 pre-existing environment failures as the baseline; no new ones).
  - API: `parse(code) -> Parsed`, `verify(code, keys=None) -> Licence`, `entitlements_from(licence) -> Entitlements`, `accept_new(current, new_licence) -> Entitlements`, `FALLBACK`, plus `encode_payload(dict) -> bytes` (canonical JSON: sorted keys, compact) and `make_code(payload, sig) -> str` so the factory (C8) signs exactly the bytes the hub verifies. Errors are **raised** as `LicenceError(ValueError)` with plain-English messages (the plan's `-> Licence | LicenceError` is read as "returns or raises").
  - `keys=None` reads `licence_pubkey.TRUSTED_KEYS` at call time, so tests monkeypatch the module attribute.
  - Whitespace and line breaks are removed anywhere in a pasted code (not only around it); `=` padding is tolerated. The stored code is the normalised one.
  - Payload model is strict (`rigs: true` or `"6"` is refused), ignores unknown keys (a newer v1 factory still verifies), `rigs` 1..999. Feature names unknown to this hub are dropped in `entitlements_from`.
  - `Entitlements.licensed(n)`: rig numbers are 1-based ("Rig N" in rigs.json), so rigs 1..N are licensed. `supplier` is `brand.COMPANY` for 9t7, "your supplier" for unbranded; `vendor_mark` is `variant == "9t7"`.
  - PyInstaller spec unchanged: pyinstaller-hooks-contrib bundles `cryptography` itself. **LOCAL** must confirm the built exe verifies a code (part of L1/L2).
  - C1 review: payload strings must be one visible line (no control characters, not blank; games/feature names ≤ 40); `v` is a strict int (`true`/`1.0` refused); `seq` ≤ 2³¹−1; pasted codes also drop zero-width characters and a BOM (Notepad); codes over 20,000 characters are refused unread; `verify(keys=<bytes>)` raises TypeError instead of silently failing; `encode_payload` accepts a `LicencePayload` or `date`, and new `check_payload(bytes)` lets C8 validate before signing; `licensed()` refuses bools. Tests: 84 in test_licence.py; hub `953 passed, 10 skipped, 5 failed` (same 5 pre-existing).

- 2026-11-03 **C2 Licence storage, owner page, backups** (cloud). Hub: `980 passed, 10 skipped, 5 failed` (the same 5 pre-existing environment failures). New `hub/tests/test_licence_storage.py` (26 tests) and the shared helper `hub/tests/licence_helpers.py` (`trust(monkeypatch) -> Signer`, `Signer.code(**payload_overrides)`, `payload()`, `CAFE_ID`) for C3+.
  - `licence.py`: `LICENCE_FILE = "licence.txt"`, `read_file(data_dir)` (None when missing, `LicenceError` when damaged/unreadable/not signed by a trusted key; tolerates a BOM, CRLF and wrapped lines), `write_file(data_dir, licence)` (atomic tmp + fsync + `os.replace`, like settings.json), `NO_LICENCE`, `DAMAGED`, `SAVE_FAILED`, `PROBLEMS`, `GAME_NAMES = {"f1_25": "F1 25"}` + `game_name(id)`, `summary(ent, problem)` ("Licensed to Apex Lounge · 6 rigs · F1 25", "1 rig").
  - `Hub`: `entitlements` (property; `FALLBACK` until loaded, so tests and in-memory hubs are quiet), `licence_problem` ("missing"/"damaged"/None), `load_licence(warn_missing=True)`, `apply_licence(code)` (verify → `accept_new` against the current entitlements → write → swap; under a lock; raises `LicenceError`), `licence_warning()`, `licence_summary()`, `licence_info()` (owner card; never the code), **`entitlement_hooks: list[Callable[[Entitlements], None]]`** called by `_on_entitlements_changed()` on every load/apply (one failing hook is logged, never stops the licence) — **C3 hooks in here**, then `refresh_feed()`.
  - Warnings: `admin_warnings()` adds `licence_missing` / `licence_damaged` (staff Health and /setup, never the TV feed). `__main__` loads the licence right after creating the Hub; only `run` (not `--demo`, not replay) warns about a *missing* file; a damaged one is always said.
  - Feed refresh: `Hub.feed_epoch` is bumped by `refresh_feed()`; `FeedConnection.tick` then sends a fresh `snapshot` (seq carries on) which replaces the TV's state, exactly like a reconnect's. Documented as additive in `docs/WS_SCHEMA.md` (§1 "On connect" and the `snapshot` row). The dashboard already handles a snapshot at any seq (reducer replaces all state); no dashboard change.
  - Owner API: `GET /api/owner/licence` → `{source, summary, cafe_name, rigs, games (display names), game_ids, features, variant, licence_id, seq, warning}`; `POST /api/owner/licence {code}` → same body, or 400 with the LicenceError message (non-string/blank code → INVALID). Both behind the owner `check` (feature flag 404, no PIN 403, `PinGuard` + shared `PinAttempts`).
  - Owner page: Licence card (summary, "Licence <id>", "Enter new code" textarea + "Use this code", plain errors and "Done. The new licence is in use now."), all via `textContent`. The fallback summary is the warning text, shown in red. Setup page: one read-only line under "Rigs" from `/api/setup` `licence` (summary only, shown without PIN like the cafe name; never the code or licence id).
  - Backups: `licence.txt` added to `BACKED_UP_FILES`; restore puts it back with the rest (the hub is stopped for restore and reads it at start). The data folder ACL is set on the folder by the installer and inherited, so no per-file work.
  - C2 review: no Critical findings (PIN + shared lock-out on GET and POST, code never in logs/feed/`/api/setup`, `textContent` only, licence loaded before the loop/UDP start, atomic write, non-downgrading restore all verified). Fixed: `POST /api/owner/licence` is now `async` so `apply_licence` and the **entitlement hooks run on the event loop thread** (C3 hooks mutate state the feed/UDP path read; a worker thread could race them) — test `test_owner_licence_api_applies_on_the_event_loop`; the licence lock is now an `RLock` and `load_licence` takes it too (a hook may re-enter); restore's log line no longer claims "newer" when the backup's licence was damaged. Dashboard: new vitest that a second `snapshot` on the same socket (seq continuing) replaces state with no reconnect. Hub `981 passed, 10 skipped, 5 failed` (pre-existing); dashboard 121 vitest passed, tsc clean.
  - LOCAL: check the Licence card on the owner page by eye, and that `licence.txt` in `C:\ProgramData\...\data` inherits the SYSTEM/Administrators-only permissions after a code is entered.

- 2026-11-03 **C3 Enforcement** (cloud). Hub: `1002 passed, 10 skipped, 5 failed` (the same 5 pre-existing environment failures). New `hub/tests/test_licence_enforcement.py` (22 tests). Dashboard: 121 vitest passed, `tsc -b` clean (only the `vendor_mark?` type and the fixture's new key; the TV's visual change is C4).
  - **Rigs:** `Rig.number` (from the auto name "Rig N" in rigs.json; renaming never changes it, a merge carries it). `Hub.rig_licensed(ip)` (an address that is no rig now, e.g. a forgotten rig's old laps, counts as licensed: history), `Hub.tv_hidden_rigs()` (computed live, so a rig registering later is covered without a hook).
  - **TV feed** (`core/feed.py`): `rigs`/`rig_info`, `frame.rigs` (so `comparison`), leaderboards (`LapStore.board(exclude_rigs=)` in SQL, so a driver's best on a licensed rig still counts), `recent_laps`, `session_story`, `head_to_head` and the boards' `mini_owners`, the TV challenge board (`Competitions.current_challenge/due_winners(exclude=)`), `tv.pinned_rig` (reads null), `status` (`FeedBuilder.status(now, tv=True)`; staff Health keeps every rig) and lap-book messages (`feed.tv_message`: `lap_completed` and moments of hidden rigs dropped; podium/race-podium lines trimmed). Moments made for the TV use the TV's view: the record moment compares with the boards the TV shows (`LapBook.tv_hidden`), now-driving's today record, the podium (`active_track(tv=True)`), challenge winners, and the race podium (cards still made for every rig). `board_key` and the competition/head-to-head cache keys include the hidden set. If a rig the TV already has becomes hidden, that TV gets a fresh snapshot; a new hidden rig is simply never sent. WS_SCHEMA documents this as additive.
  - **Staff/owner:** `/api/staff/rigs` rows gain `licensed` and `licence_note` ("Not licensed"), shown on the rig card. `Hub.licence_rigs_warning()`: "This licence covers N rigs. Rig N+1 and up aren't shown on the TV. Contact {supplier} to add rigs." ("1 rig" for one), only while a rig beyond N is in the registry; in `admin_warnings()` (staff Health and /setup, code `licence_rigs`) and `licence_info()["rigs_warning"]` (owner Licence card).
  - **Features:** one accessor, `Hub.features` = hub.toml `[features]` AND the licensed features (`config.features` stays the owner's own hub.toml flags). Every read now goes through it (hub, feed snapshot `hub.features`, staff, check-in, cards, `wifi_share(config, features)`). There is no feature-toggle UI or API on the owner page (flags live in hub.toml only), so "can't switch on an unlicensed one" is the AND itself (test: setting the hub.toml flag leaves it off).
  - **Games:** `adapters.registry()` (game id -> adapter class; `F1Adapter.game_id = "f1_25"`, also on the `GameAdapter` protocol) and `adapters.game_id(adapter)`. `Hub.on_datagram` drops valid packets of an unlicensed game after registering the rig (health drop `game_not_licensed`), staff state "Game not licensed", and `admin_warnings()` gets "Rig 1: This licence doesn't include <game>." for a minute after the last such packet. Tested with a fake adapter registered under a fake game id.
  - **Variant:** snapshot `hub.vendor_mark` (= `Entitlements.vendor_mark`). The hub pages (staff, owner, setup, check-in, hello, sticker sheet) have no 9T7 mark of their own (checked by a test); only text from the hub names the supplier, and that follows the variant.
  - **Live:** `Hub._apply_entitlements` is registered as an entitlement hook (features, game) and `apply_licence` refreshes every TV through the C2 snapshot; tested for rigs, features, vendor_mark and games.
  - LOCAL: look at the staff rig card's "Not licensed" line and the owner page with the business figures not licensed (Licence card and backups still there) by eye.

## Decisions to confirm
- C1: the error messages end with a full stop ("This code isn't valid: check you copied all of it."), matching the hub's other owner messages.
- C1: re-entering the exact code that is installed says "This code is already installed." instead of "older than the one installed" (a fourth plain message, not in spec §2.3). A different code with the same or a lower seq says "This code is older than the one installed."
- C2: a **damaged** licence file counts as "no licence yet" when a new code is entered, so any validly signed code (even another cafe's) is accepted and the owner can recover without the seller. The signature still has to verify.
- C2: a **restore** keeps this PC's licence when it verifies and the backup's is the same cafe's with a lower seq (or doesn't verify), so restoring an old backup never loses add-ons bought since. A missing or damaged current licence, or another cafe's, is replaced by the backup's.
- C2: there is no `[features]` flag for the licence itself (it decides the flags; an owner switch would defeat it). Code entry lives on the owner page, so with `[features] owner = false` a new code can't be entered until it is switched back on (or the seller provisions it, C5).
- C2: the hub refreshes TVs after a new code with a mid-connection `snapshot` (additive in WS v1) rather than closing the socket.
- C2: a demo or replay with no licence file runs on the fallback without the "No licence found" warning; a damaged file is still reported.
- C3: rigs beyond the licence are the ones whose **number** is above N (as the plan's `licensed(rig_number)`), not "the N lowest numbers present". A rig PC replaced without "same rig as…" on /setup gets the lowest free number, so normally nothing changes; a hand-edited rigs.json without "Rig N" counts as not licensed.
- C3: the rigs warning shows only while a rig beyond N is in the rig list (connected now or seen before and not forgotten).
- C3: `run --demo` stays on the fallback (spec 2.2), so the six-rig demo shows **4 rigs on the TV** and rigs 5–6 say "Not licensed" on the staff page. If the seller wants all six on the demo TV, the demo could carry its own licence or the demo sim could use 4 rigs.
- C3: the licence never turns off `owner`'s **Licence card and backups**: only the business figures (report, CSV) need the licensed `owner` feature, so an add-on code can always be entered. hub.toml `owner = false` still closes the whole page (C2).
- C3: the hub-side safety switches `auto_end_sessions` and `backup_warning` are not licensed products: only hub.toml turns them off (`licence.NOT_LICENSED_FLAGS`).
- C3: the F1 adapter counts every packet format it reads (2025, 2026) as the game "f1_25", so no current cafe loses a rig over the format setting; a separate "F1 26" licence id is a later decision.
- C3: the TV's challenge board and challenge-winner moment leave out laps from rigs beyond the licence (like the other boards); the staff page's challenge list keeps them. Corporate-event team boards are by driver, not rig, and are unchanged.
- C3: head to head and mini-sector owners use each driver's best traced lap of the day, so a driver whose best was on a hidden rig drops out of those two TV views for that day.
