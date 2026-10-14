# Self Check-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** A customer scans the QR sticker on their rig, types a first name and taps Start; their laps go under that name. The phone page then shows their laps and best lap, and "I'm done" ends the session and shows their story card right there. Staff don't have to start every session, and walk-ins no longer end up under the rig PC's EA account name.

**Architecture:**
- **Codes and API:** each rig gets a random check-in code (stored in the data dir, regenerable by staff). A new `checkin` API router serves the phone page `/checkin/<code>` and its JSON API. It reuses the existing session machinery (`hub.drivers.assign` / `hub.end_session`, which already makes the story card), so the TV, boards, cards and race podium behave exactly as for staff-started sessions.
- **One driver per session:** a per-session secret, returned at check-in and kept in the phone's localStorage, lets only that phone end its own session and fetch its card.
- **Printing:** staff print the codes as an A4 sheet of rig stickers from `/staff/checkin-print` (segno SVG QR codes, already a dependency).

**Tech:** FastAPI hub (`simtelemetry`), plain HTML/JS pages like `api/staff.html`, segno, pytest.

**Spec:** the user asked on 2026-10-15 to "implement that self check in feature": option 1 from the controller's proposal (a QR on each rig opens a "What's your name?" page; one tap starts the session, no staff needed). The rulings below are the controller's design decisions, announced to the user.

## Global Constraints

- Offline LAN only. The QR encodes the hub's LAN URL. TV pages never show IPs or diagnostics as text.
- Every feature can be switched off: add `self_checkin = true` to `[features]`. When it's off, `/checkin/*` returns a friendly "Check-in is switched off, please ask staff" page and the API returns 403.
- Product name only from `hub/simtelemetry/brand.py`. `hub/tests/test_no_hardcoded_name.py` must pass, so pages use the `{{PRODUCT_NAME}}` placeholder via `api/pages.py`, like staff/owner/setup.
- No new personal data. Self check-in takes a first name only (no phone). Profiles stay staff-only.
- WS schema v1 additive only. This feature should need no feed changes; if it does, document them in `docs/WS_SCHEMA.md`.
- One commit per task, all tests passing (`.venv\Scripts\python -m pytest -q`, plus dashboard `npx vitest run` / `npx tsc -b` if the dashboard is touched). Every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never touch port 8000. Never run the installer, schtasks, netsh or taskkill. Branch `self-checkin` (from `packager` 54444f9).

## Rulings (controller, binding)

- **C1. Codes.**
  - Each rig gets a random 8-character URL-safe code (`secrets`), stored in `<data_dir>/checkin.json` as `{rig_id: code}`. Codes are created lazily for every known rig.
  - Staff can regenerate one rig's code (POST, staff PIN), which invalidates the old sticker.
  - An unknown code shows "This code is no longer valid, please ask staff".
- **C2. Check-in.** `POST /api/checkin/<code>` with body `{"name"}`.
  - The name is cleaned with the existing `clean_name`, then checked against the bad-name filter (C5).
  - **Free rig** (no current assignment): start a session with `hub.drivers.assign(rig_id, name=name)`, no booking minutes, and the same "Now driving" moment and feed updates a staff start gets.
  - **Takeover:** if the rig has a session but its health state has not been DRIVING for at least `CHECKIN_TAKEOVER_IDLE_S = 120` s, end it first with `hub.end_session(rig_id)`, so the previous driver's card is still made, then start the new one.
  - **Otherwise:** 409 "Rig N is in use. Please ask staff."
  - Returns `{"rig_name", "driver", "secret", "status_url"}`. The secret is random and stored in memory with the session (rig_id, started_at).
  - Rate limit: at most 10 check-in POSTs per minute per client IP, else 429.
- **C3. Status.** `GET /api/checkin/<code>?secret=...`:
  - Returns `{"rig_name", "state": "free"|"busy"|"yours"|"ended", "driver"?, "laps", "best_ms"?, "card_url"?}`.
  - "yours" while the secret's session is current. Laps and best come from `hub.laps.laps` for that rig, driver key and `completed_at >= started_at`.
  - "ended" once that session has ended, with `card_url` if a card was made: the URL `end_session` returned, remembered against the secret for 2 hours.
  - Without a secret, or with a wrong one: only "free" or "busy" (and "busy" includes no driver name).
- **C4. Done.** `POST /api/checkin/<code>/done` with body `{"secret"}`.
  - Ends the session only if the secret matches the current session, then returns `{"card_url"}` (or null when there were no counted laps).
  - A wrong or old secret gets 403.
- **C5. Bad-name filter.**
  - A small default blocklist lives in `hub/simtelemetry/core/names.py`: a few dozen common English and Hindi/Hinglish profanities, whole-word and case-insensitive, also matching runs of letters with simple leetspeak (0→o, 1→i, 3→e, 4→a, 5→s, @→a, $→s).
  - Cafes can extend it with `[checkin] blocked_words = [...]`.
  - Rejected names get 400 "Please choose another name."
  - Staff-entered names are not filtered (staff are trusted).
- **C6. Phone page** `/checkin/<code>`:
  - Mobile-first, the same look as the staff and card pages.
  - Shows the rig name and a "What's your name?" field; Start becomes "You're on Rig 3. Drive!" with live laps and best lap, polling status every 3 s.
  - Big "I'm done" button (with a confirm). Then "Your card" with Save for Instagram story, via a link to `card_url`.
  - Stores `{code, secret}` in localStorage, so reopening the page resumes.
  - Busy and invalid states have friendly text.
  - Uses `textContent` only, never innerHTML with user input.
- **C7. Staff:**
  - `/staff/checkin-print` (staff PIN like the other staff pages) is an A4 printable sheet with one card per rig. Each card has the rig name, a big QR to `http://<hub LAN address>:<port>/checkin/<code>`, "Scan to put your name on <Rig>" and, if guest Wi-Fi is set, a small "Join our Wi-Fi first" QR built with the existing Wi-Fi helper (`core/wifi.py`).
  - The staff page's rig card gets a "Check-in QR" link to it and a "New code" button (confirm: "Old stickers stop working").
  - The printable page may show the hub address; it is a staff page.
- **C8. Ending.** Sessions started by check-in end the same ways as staff sessions (staff End, booking timer if staff add time, takeover per C2, "I'm done"). No change to `end_session` itself.

---

### Task 1: Check-in core and API

**Files:** create `hub/simtelemetry/core/checkin.py` (codes store, secrets, rate limit), `hub/simtelemetry/core/names.py` (blocklist), `hub/simtelemetry/api/checkin.py` (router: page route plus the JSON API); modify `config.py` (`FeaturesConfig.self_checkin`, `[checkin] blocked_words`), `api/app.py` (include the router), `api/staff.py` (GET codes and POST regenerate, staff PIN), `config/hub.example.toml`.

**Tests:** `hub/tests/test_checkin.py`:
- free rig: check-in starts a session, the name shows in the staff API, and laps go under the name;
- busy rig: 409, with no name leaked;
- idle takeover after 120 s (fake health/clock): the previous driver's card is made and the new driver is assigned;
- status with and without the secret;
- done with the right secret gives the card URL; a wrong secret gives 403;
- an invalid code gives 404 JSON and the friendly page;
- feature off gives 403;
- rate limit gives 429;
- the bad-name filter: whole words, leetspeak, the custom list, normal names like "Ashish" or "Scunthorpe" pass;
- staff regenerate invalidates the old code.

### Task 2: Phone page and staff printing

**Files:** create `hub/simtelemetry/api/checkin.html`, `hub/simtelemetry/api/checkin_print.html` (or render the print sheet server-side; QR codes as inline segno SVG); modify `api/staff.html` (per-rig "Check-in QR" and "New code"), `api/staff.py` (print route); docs: README "Self check-in" section, `docs/INSTALL.md` (print and stick the codes), `docs/TEST_PLAN.md` (a check-in run on a phone). Bump the version to 0.4.0 and rebuild the installer (`packaging\build.ps1`; never run it).

**Tests:**
- page routes return HTML with the placeholder filled;
- the print sheet has one QR SVG per rig and the Wi-Fi QR when set;
- the staff page has the new controls;
- the name guard test passes.

**Visual check:** throwaway demo hub on 8199. Screenshot the phone page at 430×900 DSF 2 in its states (enter name, driving, done/card) and the print sheet at A4. Save them under `.superpowers/sdd/2026-10-15-self-checkin/`.
