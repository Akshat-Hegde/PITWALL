# Race Podium + QR Story Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At the end of an F1 25 race, the TV shows a podium of the cafe's drivers with a QR code beside each name, followed by a "Grab your card" screen with a QR for every finisher and an optional "Join our Wi-Fi" QR. Each QR opens that driver's race story card, which they can save for Instagram (1080×1920) or share on WhatsApp. Time trials keep today's flow: a session ends, and that driver's card QR shows on the TV.

**Architecture:**
- **Reading the result.** The F1 adapter decodes the Final Classification packet (id 8) and emits a game-agnostic `RaceFinished` event with the rig's own result.
- **Grouping the race.** A new `RaceBook` (core) groups results from several rigs into one race. Same track, a race session type, and reports arriving within a short window count as one race. It ranks the cafe drivers by finishing position.
- **Cards and the TV.** It builds a race card per finisher (reusing the cards table and the `/card/<token>` page) and publishes a `race_podium` moment (an additive WS message). The dashboard renders it as a two-phase overlay, podium then "Grab your card", using the existing `Qr` component.
- **Wi-Fi QR.** Guest Wi-Fi details are an optional owner setting from `/setup`.

**Tech Stack:** Python 3.11 (`simtelemetry` hub, FastAPI), React/TS dashboard (Vitest), F1 25 UDP (formats 2025 and 2026).

**Spec:** chat 2026-10-14. The user's design: "post race podium (race only, not time trial) with a QR beside each name that opens that driver's card to download and post to Instagram". The controller's agreed refinements:
- every finisher gets a QR, on a follow-up screen;
- QR codes sized to scan from 2–3 m;
- a Wi-Fi join QR, because cards only open on the cafe network;
- the Instagram story format;
- time trials keep the session-end QR.

## Global Constraints

- Everything works offline on the cafe LAN. The card QR encodes the hub's LAN URL as today.
- TV pages never show IP addresses or diagnostics as text. A QR code that encodes the card URL is fine, and already done today.
- Every feature can be switched off in `[features]`. Add `race_podium = true`, under the existing `sharing` umbrella: with `sharing` off, there are no QR codes anywhere.
- WebSocket schema v1 is frozen: additive only. Document it in `docs/WS_SCHEMA.md` (a new moment kind `race_podium`, plus the race fields on a card).
- The product name only comes from `hub/simtelemetry/brand.py`. The guard test `hub/tests/test_no_hardcoded_name.py` must keep passing.
- Phone numbers only with consent. This feature adds no personal fields. The Wi-Fi password is an owner setting, shown only as a QR on the TV, and documented as "use a guest network".
- No F1/FIA logos, official fonts or team marks.
- One git commit per task, all tests passing (`.venv\Scripts\python -m pytest -q`; `npx vitest run`, `npx tsc -b` and `npm run build` in `dashboard/`). Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never touch port 8000 (the user's live hub). Never run the installer, schtasks, netsh or taskkill.
- The work is on branch `race-podium` (from `packager`).

## Rulings (controller, binding)

- **R1. Race only.** Only session types 15, 16 and 17 (Race, Race 2, Race 3) produce a race podium. Practice, qualifying and Time Trial do not.
- **R2. Grouping.**
  - Each rig reports its own player's result.
  - Results with the same `track_key` and a race session type that arrive within `RACE_GROUP_WINDOW_S = 90` s of the first one form one race.
  - The podium is published `RACE_SETTLE_S = 8` s after the last report of that group, or immediately once every rig that was "driving" in a race session on that track has reported.
  - Duplicate reports from one rig for the same race (the game can resend) are ignored.
- **R3. Ranking.**
  - Cafe drivers are ranked by their in-game finishing `position`. The card and screen show the real race position ("P4"), and the podium shows the top three cafe drivers.
  - Finishers come before DNF/DSQ/not classified (status ≠ 3), which come last, ordered by laps completed and then by position.
- **R4. Solo races.** With a single cafe driver in the race (racing AI), there's no podium overlay. That driver still gets a race card, shown by the existing `CardQr` corner card.
- **R5. Driver names.** The driver name is the staff-assigned name for the rig, else the game name, else the rig name: the same order laps use (`LapBook` context / `drivers`).
- **R6. Race card contents:**
  - position;
  - grid position;
  - positions gained;
  - laps;
  - best lap (from the packet);
  - total race time (`m_totalRaceTime`, seconds, plus `m_penaltiesTime`);
  - result status;
  - track;
  - the cafe-ranked result ("1st of 4 at <cafe name>").

  It's stored in the existing `cards` table, with `kind: "race"` in its data. Session cards keep `kind` absent or `"session"`.
- **R7. Overlay timing.** The `race_podium` moment runs about 40 s: 15 s podium, then 25 s "Grab your card". The dashboard owns the exact timing. The moment carries every finisher's card URL.
- **R8. Wi-Fi QR.**
  - Optional owner settings: `wifi_ssid` (≤ 32 chars), `wifi_password` (8–63 chars or empty for an open network) and `wifi_security` (`WPA` | `nopass`).
  - The TV shows a "Join our Wi-Fi" QR (`WIFI:T:WPA;S:<ssid>;P:<pass>;;`, with `\ ; , : "` escaped as the WIFI URI spec requires) beside card QR codes when an SSID is set. Its text shows the SSID only, never the password.
  - The feed carries the encoded QR string only when `sharing` is on and an SSID is set.
- **R9. Instagram.**
  - The card page's save button reads "Save for Instagram story"; the existing image is already 1080×1920.
  - Add one line of help: "Then post it from your gallery to your Instagram story."
  - No Web Share of files: the LAN page is plain HTTP, so it can't use it reliably.
- **R10. Demo.** The demo director gains a `race` action that simulates a 4-rig race ending, which makes screenshots and manual checks possible without a real LAN race.

---

### Task 1: Decode Final Classification and emit `RaceFinished`

**Files:**
- Modify: `hub/simtelemetry/adapters/f1/f2025.py`, `f2026.py` (layouts `FinalClassificationData`, `PacketFinalClassificationData` from `docs/F1_25_structures.txt` and `docs/F1_2026_SeasonPack_structures.txt`), `formats.py` (register the packet), `decode.py` (decode it), `adapter.py` (emit the event only for race session types; the session type comes from the rig's latest Session packet)
- Modify: `hub/simtelemetry/core/adapter.py` (add the `RaceFinished` dataclass to `DecodeResult`, as `race_results: list[RaceFinished]`)
- Test: `hub/tests/test_final_classification.py`

**Interfaces (produces):**

```python
@dataclass(slots=True)
class RaceFinished:              # core/adapter.py, game-agnostic
    track_key: str | None
    session_type: str            # e.g. "Race"
    session_uid: str | None
    position: int                # player's finishing position (1-based)
    grid_position: int | None
    laps: int
    best_lap_ms: int | None      # 0 from the game -> None
    total_time_s: float | None   # m_totalRaceTime (+ m_penaltiesTime)
    penalties_s: int
    status: str                  # "finished" | "dnf" | "dsq" | "not_classified" | "retired" | "active" | "inactive" | "invalid"
    num_cars: int
```

**Steps:**
- [ ] Write failing tests. Build a synthetic Final Classification packet with the test helpers in `hub/tests/f1_helpers.py`, extended with a builder for packet id 8 in both formats. The packet size must equal `sizes.py`'s 1042 (2025) and 1134 (2026). Test that:
  - with the session type set to Race (15), the adapter yields one `RaceFinished` for the player car with all fields mapped;
  - with Time Trial (18) or a qualifying type, it yields none;
  - `best_lap_ms` 0 maps to None;
  - status mapping follows `m_resultStatus` 0–7.
- [ ] Run them and see them fail. Implement. Also check that `test_layouts_spec.py` / `test_sizes_table.py` (existing) still pass, extending them if they enumerate decoded packets.
- [ ] Full suite, then commit: "F1: decode Final Classification; RaceFinished event for race sessions".

### Task 2: `RaceBook`, race cards and the `race_podium` moment

**Files:**
- Create: `hub/simtelemetry/core/races.py`: `RaceBook` (grouping per R2, ranking per R3, solo per R4)
- Modify: `hub/simtelemetry/hub.py` (feed `RaceFinished` events from decode results into the RaceBook; run the settle timer in the hub's existing async loop or check due races on each consume/tick, with no new thread), `core/cards.py` (`build_race_card(hub, rig_id, result, race) -> dict | None` storing `kind: "race"`, reusing `new_token`, the store and URL building exactly as session cards do; an existing session card's QR flow is unchanged), `config.py` (`FeaturesConfig.race_podium: bool = True`), `config/hub.example.toml` (document the flag), `tools/demo_director.py` (`race` action, R10), `api/staff.py` only if the demo action list is validated there
- Test: `hub/tests/test_races.py`

**Interfaces (produces):**
- `RaceBook(clock)`, with `.add(rig_id: str, result: RaceFinished, now: float) -> None` and `.due(now: float, driving_race_rigs: set[str]) -> list[Race]`.
- `Race` holds `track_key`, `track_name`, `session_type`, `results: list[tuple[rig_id, RaceFinished]]` ranked, and `finished_at`.
- The `race_podium` moment body is `{"track_key", "track_name", "session_type", "drivers": [{"rank", "position", "driver", "rig_id", "grid_position", "laps", "best_lap_ms", "total_time_s", "status", "card_url", "card_token"}], "wifi": {"ssid": str, "qr": str} | None}`. It's published via `hub.laps.publish_moment("race_podium", ...)` only when `features.sharing and features.race_podium` and there are ≥ 2 cafe drivers (R4). With 1 driver, only the race card is made, and it appears through the existing cards feed (`state.cards`) like a session card.
- The feed's `cards` entries gain optional `kind` and `position` (additive).

**Steps:**
- [ ] Write failing tests:
  - three rigs reporting positions 4, 1 and 7 within 90 s on one track become one race ranked 1, 4, 7;
  - a fourth report 3 minutes later is a new race;
  - a duplicate report from the same rig is ignored;
  - a DNF is ranked last;
  - a settle at 8 s after the last report, or immediately when all driving race rigs have reported;
  - a solo race makes a card but no moment;
  - the moment is suppressed when `race_podium` is false and when `sharing` is false;
  - race cards are stored with `kind: "race"` and open at `/card/<token>` (the existing card API returns the race fields);
  - the demo `race` action publishes a podium with 4 drivers.
- [ ] Implement, run the suite, then commit: "Race podium: group rig results into races, race story cards, race_podium moment, demo race".

### Task 3: Guest Wi-Fi setting

**Files:**
- Modify: `core/settings.py` (`wifi_ssid`, `wifi_password`, `wifi_security`, validated per R8; the password is never returned by GET /api/setup, the same "blank = keep" rule as the PINs once settings exist), `api/setup.py`, `api/setup.html` (a "Guest Wi-Fi (optional)" section with a note: "Shown as a QR code on the TV. Use a guest network."), `core/feed.py` (`cafe.wifi` = `{"ssid", "qr"}` or null, with the QR string built server-side with correct escaping; only when `features.sharing` is on), `docs/WS_SCHEMA.md`
- Test: `hub/tests/test_wifi_qr.py`

**Steps:**
- [ ] Write failing tests:
  - escaping of `; , : \ "` in the SSID and password;
  - an open network (`nopass`) has no P field;
  - GET /api/setup never contains the password;
  - a later save with a blank password keeps it;
  - the feed `cafe.wifi` is null when `sharing` is off or no SSID is set;
  - the password appears in no API response except inside the `cafe.wifi.qr` string.
- [ ] Implement, run the suite, then commit: "Guest Wi-Fi QR: optional owner setting, encoded for the TV".

### Task 4: Dashboard: race podium overlay, "Grab your card", Wi-Fi QR, card page

**Files:**
- Modify: `dashboard/src/schema.ts` and `state/reducer.ts` (the `race_podium` moment kind; `cafe.wifi`; card `kind`/`position`), `components/Moments.tsx` (add `race_podium` to `MOMENT_MS` at 40 000 ms, render `<RacePodium>`)
- Create: `components/RacePodium.tsx`
  - Phase 1 (0–15 s): a podium of the top 3 cafe drivers (P1 centre, raised), each with their rig colour, name, real race position, best lap and a **QR beside the name** (about 300 px on the 1920×1080 stage, so roughly 20 cm on a 55" TV).
  - Phase 2 (15–40 s): "Grab your card": a grid of every finisher (up to 10) with their QR, name and "P<n>", plus the Wi-Fi QR tile ("Join our Wi-Fi · <SSID>") when `cafe.wifi` is set.
  - Use the existing pattern system (slanted tags, Flash, EdgeLines) and the `TvStage` scale. No IPs as text.
- Modify: `components/CardQr.tsx` (show the Wi-Fi QR beside the card QR when set), the card page component (find it: it renders `/card/<token>`; "Save for Instagram story" label plus the help line per R9; a race variant of the card artwork showing the big "P<n>", "Race · <track>", grid → finish ("+3 places"), best lap, total time, "1st of 4 at <cafe>"; the session card artwork unchanged)
- Test: `dashboard/src/components/RacePodium.test.tsx` (it renders the 3 podium QR codes and names in phase 1; switches to the grid with N finishers and the Wi-Fi tile in phase 2, using fake timers; never renders the Wi-Fi password as text), plus a reducer test for the moment and `cafe.wifi`, and a card page test for the race variant fields (if the card drawing is canvas, test the data mapping function instead of pixels)

**Steps:**
- [ ] Write failing tests, implement, then run `npx vitest run`, `npx tsc -b` and `npm run build`.
- [ ] Visual check with a throwaway demo hub: `.venv\Scripts\python -m simtelemetry run --demo --data-dir <temp> --http-port 8199`. Trigger `POST /api/staff/demo/race`, set a guest Wi-Fi in /setup (the setup code from `<temp>\setup-code.txt`), and take Edge headless screenshots of the TV at about 5 s (podium) and about 20 s (grid) and of a race card page at 430×900 DSF 2. Save them under `.superpowers/sdd/2026-10-14-race-podium/`. Stop the hub.
- [ ] Commit: "TV: race podium with QR codes, Grab your card, Wi-Fi QR; race story card; Save for Instagram".

### Task 5: Docs and the packaged build

**Files:** `README.md` (a "Race podium and story cards" section: race vs time trial behaviour, the Wi-Fi QR, the feature flags), `docs/INSTALL.md` (guest Wi-Fi in setup), `docs/WS_SCHEMA.md` (complete it), `docs/TEST_PLAN.md` (add: run a 2-PC F1 25 LAN race and check the podium, the QR codes and the race card; record the packets with `listen` for a regression fixture). Bump the version to 0.3.0 and rebuild the installer (`packaging\build.ps1`; do not run it).

- [ ] Docs, then the version bump, then build. Full suite, then commit: "Docs + v0.3.0 for race podium".

## After this plan
- With the user's 2 PCs: an F1 25 LAN race recorded with `listen`, to confirm the Final Classification fields and the grouping window on real packets, and to add the recording as a fixture.
- Assetto Corsa / ACC adapters (they will need their own race-result events to feed RaceBook).
