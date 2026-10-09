# Lap tracking: assumptions about real game behaviour (F1 25)

Lap tracking (`hub/simtelemetry/adapters/f1/laps.py`) was built from the UDP spec, without a recording of
a real session. The spec defines the fields but not how they behave over time, so the rules below rest on
assumptions. Each one says what we assume, how the code handles it (including when the assumption is
wrong), and how to check it in the real test.

**How to verify:** run the hub with `--lap-debug` (works with `run`, `listen` and `replay`). Every lap event
is logged with the wall-clock time, the rig and the game's session time (`game_t`), both in the console and
in `data\logs\lap-debug-<date>-<time>.log`. Event names in that log:

| Event | Meaning |
|---|---|
| `lap_started` | LapData's lap number went up. `out_lap=True` if the lap began as an out lap or in the pit. |
| `lap_completed` | A lap was recorded. `source=session_history` (normal) or `source=lap_data_fallback`. |
| `lap_invalidated` | LapData's `m_currentLapInvalid` changed from 0 to 1. |
| `reset` | `reason=flashback`, `lap_number_decreased`, `lap_number_jumped` or `session_changed`. |
| `lap_retracted` | A completed lap was withdrawn: undone by a flashback, or replaced by corrected numbers. |
| `session_history_update` | The player's Session History changed; `changed=` lists the lap entries that changed. |
| `recorded ...` | What the lap book did with a completed lap: counted, bests, sector ratings. |

Write down the in-game times while driving, then compare them with the log. Tick each assumption as
**confirmed** or note what you saw instead.

---

### A1. Session History is per car and arrives several times a second for the player

- **Assumption:** Session History packets cycle through all cars (spec: "20 per second but cycling through
  cars"). In Time Trial that's the player plus ghost cars, so the player's history arrives every few
  hundred ms. Entries for other cars (ghosts) are ignored: the decoder keeps only `m_carIdx ==
  m_playerCarIndex`.
- **Handled:** completed laps wait for the player's history; nothing else is used for times.
- **Verify:** `session_history_update` lines appear within about a second after each line crossing, and
  never with lap times that belong to the ghost (PB/rival) lap.

### A2. The history entry for lap N is filled in shortly after LapData moves to lap N+1

- **Assumption:** when the car crosses the line, LapData's `m_currentLapNum` goes up first, and the history
  entry for the finished lap gets its time and sectors at the same moment or shortly after. LapData's
  `m_lastLapTimeInMS` holds the finished lap's time from the first packet of the new lap, or a packet later.
  The last history entry (`m_numLaps`) is the lap in progress (spec: "including current partial lap").
- **Handled:** on the rollover the hub keeps LapData's view of lap N (last lap time, S1, S2, validity) and
  completes the lap when a history entry for N with a non-zero time arrives. The last-lap time keeps
  updating from LapData while waiting. An entry is never used while LapData is still on that lap.
- **Verify:** for each line crossing, `lap_started lap=N+1` comes first, then `session_history_update`
  with `changed=(N, N+1)` and `lap_completed lap=N source=session_history`, normally within 1 s
  (compare `game_t`). The lap time matches the in-game time.

### A3. A history entry is only trusted when it matches LapData's last lap time

- **Assumption:** right after a restart (A7) history may still hold the previous run's entries until the
  game rewrites it. A stale entry is recognisable because its time differs from LapData's last lap time.
- **Handled:** lap N's history entry is used only if its time equals the rollover's last-lap time
  (within 1 ms). Otherwise the hub waits for an update (or uses the fallback, A4).
- **Verify:** no lap is ever recorded with a time from an earlier run. After a restart, the first
  `lap_completed` has the new lap's time.

### A4. If history doesn't confirm a lap within 3 s of game time, LapData is used

- **Assumption:** history normally arrives within 3 s of the rollover (A1, A2). If it doesn't (packet loss,
  or the game doesn't write history in some mode), LapData's numbers are good enough.
- **Handled:** the lap is completed with `source=lap_data_fallback`: last lap time, S1 and S2 from the
  last packet of the lap, S3 = lap - S1 - S2, validity from `m_currentLapInvalid`.
- **Verify:** in a normal session there are **no** `source=lap_data_fallback` lines. If there are, note the
  mode and track; history behaves differently from A1/A2 there.

### A5. Later history replaces numbers that differ

- **Assumption:** history is the authority. It can differ from LapData's numbers, e.g. by a millisecond
  of rounding between S2 and S3, or the game may invalidate a lap after the line.
- **Handled:** if history later disagrees with a recorded lap (time, sectors or validity), that lap is
  retracted and recorded again with history's numbers (`lap_retracted ... reason=corrected by session
  history`, then `lap_completed`).
- **Verify:** note any `corrected by session history` lines and what changed. Frequent corrections would
  mean A2's timing is wrong.

### A6. A flashback sends FLBK; going back across the line lowers the lap number and drops the lap

- **Assumption:** every flashback sends an `FLBK` event. The game's session time goes back to the
  flashback point (the spec says `m_overallFrameIdentifier` doesn't go back after flashbacks, which
  implies the other timers do). A flashback within a lap keeps the lap number. A flashback back over the
  start/finish line lowers LapData's lap number within a few packets, and the lap that had just been
  completed disappears from history (its entry goes back to 0 or `m_numLaps` drops).
- **Handled:** `FLBK` logs `reset reason=flashback`, and the dashboard's trace of the lap in progress is
  cut back to the new position. A lap-number decrease within 60 LapData packets of `FLBK` is that
  flashback: pending laps from that point are dropped, and a completed lap is retracted when history no
  longer has it (or when LapData is back on it).
- **Verify:** use one flashback mid-lap, and if possible one just after crossing the line.
  - Mid-lap: one `reset reason=flashback`, the lap number doesn't change, and `game_t` jumps back.
  - Across the line: `reset reason=flashback`, a second `reset reason=flashback` from the lap number going
    down, then `lap_retracted`. Re-driving that lap produces a new `lap_completed`.
  - Also note whether the game marks the lap as invalid after a flashback (`lap_invalidated`, and
    `valid=` on `lap_completed`).

### A7. Time Trial "restart lap" lowers the lap number without FLBK and keeps the session

- **Assumption:** restarting in Time Trial (or a "restart session") puts LapData back on lap 1, or another
  lower lap number, without an `FLBK` event. The session UID may or may not change; if it does, A10
  applies instead. History is rewritten for the new run, possibly a little later.
- **Handled:** `reset reason=lap_number_decreased`. Laps already recorded stay recorded (they were real
  laps). History matching (A3) protects against old entries.
- **Verify:** restart once. Note whether you see `lap_number_decreased` or `session_changed`, and
  whether history's `num_laps` drops right away or later.

### A8. Out laps are recognisable from LapData at the start of the lap

- **Assumption:** a lap that starts from the pit/garage has `m_driverStatus = 3` (out lap) or a non-zero
  `m_pitStatus` on its first LapData packets. In Time Trial, the run-up lap before the first timed lap is
  such an out lap.
- **Handled:** such laps are recorded with `out_lap=True` and never count towards bests or the
  leaderboard, whatever the game's validity says.
- **Verify:** the first lap after leaving the garage shows `lap_started ... out_lap=True` (or the first
  `lap_completed` shows `out_lap=True`). Timed laps after it show `out_lap=False`. **If a real timed lap
  shows `out_lap=True`, it won't appear on the leaderboard: report this.**

### A9. Laps completed before the hub saw them are not reported

- **Assumption:** when the hub starts (or restarts) during a session, history already contains earlier
  laps. They may already have been recorded by an earlier run of the hub.
- **Handled:** only laps the hub saw in progress are reported. The lap in progress when the hub starts
  counts once it completes.
- **Verify:** restart the hub mid-session: no burst of old `lap_completed` lines; the next line crossing
  completes the lap that was in progress.

### A10. A new session changes the session UID

- **Assumption:** leaving to the menu and starting another session (another track, mode or restart that
  creates a new session) changes `m_sessionUID` on all packets.
- **Handled:** `reset reason=session_changed`; all lap state for that rig is cleared. Recorded laps stay.
- **Verify:** change track once: exactly one `session_changed` reset, then normal laps on the new track.

### A11. Validity: LapData's flag only goes from valid to invalid within a lap; history decides

- **Assumption:** `m_currentLapInvalid` stays 1 for the rest of the lap once set, and is reset to 0 when
  the next lap starts. History's lap-valid bit (`m_lapValidBitFlags & 0x01`) is the final verdict.
- **Handled:** `lap_invalidated` is logged when the flag goes to 1. The recorded lap uses history's bit
  (or LapData's flag in the fallback). Invalid laps are recorded but never set bests and are unrated.
- **Verify:** cut a corner: `lap_invalidated` at that moment, and that lap's `lap_completed ... valid=False`.
  The in-game HUD agrees.

### A12. LapData sector times mean "completed sector of this lap" once m_sector is past them

- **Assumption:** `m_sector1TimeMSPart`/`MinutesPart` hold the current lap's S1 once `m_sector` is 1 or 2,
  and `m_sector2...` hold S2 once `m_sector` is 2. Before that they may still hold the previous lap's
  values or 0.
- **Handled:** live S1/S2 are shown only when `m_sector` is past them.
- **Verify:** on the TV, S1 appears when crossing into sector 2 and matches the in-game split; the
  sectors clear when a new lap starts.

### A13. Lap distance is negative before the line is first crossed

- **Assumption:** (spec) `m_lapDistance` is negative on the run-up to the first crossing, then goes from 0
  to about the track length each lap.
- **Handled:** distances below 0 aren't used for the track outline or live deltas.
- **Verify:** on the TV the live delta stays empty until the line, then starts.

### A14. The player's name identifies the driver

- **Assumption:** the Participants name for the player car is the player's profile/gamertag, the same on
  every session, and different players have different names. Offline it may be a generic name (e.g. the
  driver's surname or "Player").
- **Handled:** personal bests and leaderboard entries are per driver name (case-insensitive). A rig with
  no name yet counts as its own driver.
- **Verify:** note the name shown on the TV for each player. If two people share a generic name, their
  laps merge into one leaderboard entry: report this.

### A15. Only valid laps that aren't out laps count; ratings follow the TV convention

- **Assumption (our rule, not the game's):** bests use only valid laps that aren't out laps. Sector
  ratings: purple = equal to or faster than the fastest of all rigs on this track since the hub started,
  green = this driver's best, yellow = slower. Live sectors are rated against the bests without changing
  them.
- **Handled:** as stated. A retracted lap (A5, A6) is removed and bests are recomputed.
- **Verify:** the purple/green/yellow colours on the TV match what you'd expect from your laps.

---

## Results from the real test

| # | Confirmed? | What we saw instead |
|---|---|---|
| A1 | | |
| A2 | | |
| A3 | | |
| A4 | | |
| A5 | | |
| A6 | | |
| A7 | | |
| A8 | | |
| A9 | | |
| A10 | | |
| A11 | | |
| A12 | | |
| A13 | | |
| A14 | | |
| A15 | | |
