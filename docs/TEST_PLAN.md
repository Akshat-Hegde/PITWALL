# Test plan: end-to-end test on 2 devices

Goal: run the whole system against the real game once, end to end. That means telemetry in, laps and
sectors, the TV dashboard, leaderboards that survive a restart, and the lap-tracking assumptions in
[LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md). Work through the sections in order and tick each box. Note anything
unexpected next to the box; that note matters more than the tick.

**The two devices**

- **Rig PC:** F1 25 (the one licensed copy).
- **Hub PC:** runs the hub, with the TV connected to it (or a browser on another screen showing the
  dashboard).

A second rig is simulated in section 7 by replaying your own recording as "Rig 2".

**What you send back afterwards:** the recording(s) from `data\recordings\`, the lap debug log(s) from
`data\logs\lap-debug-*.log`, this checklist with notes, and the filled-in results table at the end of
[LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md).

---

## 0. Before you start (hub PC)

- [ ] Project installed: `python -m venv .venv`, then `.venv\Scripts\python -m pip install -e ".[dev]"`.
- [ ] Tests pass: `.venv\Scripts\python -m pytest`.
- [ ] Dashboard built (needs Node.js 20+), once:
      ```powershell
      cd dashboard
      npm install
      npm run build
      cd ..
      ```
- [ ] Config: copy `config\hub.example.toml` to `config\hub.toml`. Set `[cafe] name` if you like; leave
      `[map]` as it is for now (section 4 finds the right values).
- [ ] **Free space:** at least 10 GB free on the drive with `data\` (recordings use ~0.75 GB per rig per hour),
      and some free on C:. PowerShell: `Get-PSDrive -PSProvider FileSystem` (`Free` column). To put
      recordings on another drive, set `[recorder] directory` in `config\hub.toml`. The hub warns below 5 GB
      and stops recording below 1 GB (`recording stopped: low disk`) but keeps running.
- [ ] **Fresh start:** if a `data\` folder exists from earlier experiments, rename it (e.g. `data-old`) so
      the leaderboards and rig names start empty.
- [ ] IP addresses (`ipconfig`): Hub PC `__________` Rig PC `__________`

## 1. Network and firewall (hub PC)

- [ ] Network profile is **Private**: Settings → Network & internet → (Ethernet / Wi-Fi) → Network profile
      type. Or PowerShell: `Get-NetConnectionProfile` (NetworkCategory). To change it (Administrator):
      `Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private`.
- [ ] Inbound rules (Administrator Command Prompt or PowerShell):
      ```bat
      netsh advfirewall firewall add rule name="Sim Telemetry UDP 20777" dir=in action=allow protocol=UDP localport=20777 profile=private
      netsh advfirewall firewall add rule name="Sim Telemetry HTTP 8000" dir=in action=allow protocol=TCP localport=8000 profile=private
      ```
      (TCP 8000 is only needed if the dashboard is opened from another device.)
- [ ] If Windows asks *"Windows Defender Firewall has blocked some features of Python"* on the first run:
      tick **Private networks** only and allow. The port rules above work either way. (The hub PC's Python
      is the Microsoft Store build, whose program rules are unreliable; that's why the plan uses port rules.)

## 2. Rig PC: game settings

- [ ] F1 25 → Settings → Telemetry Settings, per [RIG_SETUP.md](RIG_SETUP.md): UDP Telemetry **On**, UDP IP
      Address = **hub PC's IP**, Port **20777**, Send Rate **60 Hz** (or 30), UDP Format noted: `____`.
- [ ] Time Trial, one track you know well. Track: `______________`

## 3. First contact: `listen`

On the hub PC: `.venv\Scripts\python -m simtelemetry listen --no-record`

- [ ] `New rig detected: <rig PC IP> -> Rig 1`, and `fmt=` matches the UDP Format above.
- [ ] 10 s summary: `drops: none`. (`size_mismatch`, `unsupported_format` or `unknown_packet_id` is a
      blocker: stop and record it.)
- [ ] While driving: `Motion`, `LapData`, `CarTelemetry` close to the send rate; `Session` about 2/s.
- [ ] State follows the game: `driving` on track, `in_menu_paused` in menus/paused, `no_data` 5 s after
      quitting.
- [ ] Driver name and track name are right; lap number, lap time and speed match the HUD.

Stop with **Ctrl+C**.

## 4. The TV: views, map orientation, smoothness

Start the hub the way the rest of the test runs it, **recording and with lap debug on**:

```powershell
.venv\Scripts\python -m simtelemetry run --record --lap-debug
```

The log shows `Dashboard on http://localhost:8000/`, `Lap debug log: data\logs\lap-debug-...log` and
`Recording raw packets to data\recordings\...f1rec`. Note both file names:
`______________________` `______________________`

Open `http://localhost:8000/` on the TV (or `http://<hub IP>:8000/` from another device), full screen (F11).

- [ ] **Status bar:** cafe name, `Rig 1  On track  F1 <format>  <track>`, `Live`. No warnings.
- [ ] **Race view while driving:** the map shows your dot with a fading trail, and a faint line of the path
      driven so far builds up the track shape. The timing strip row shows your name, tyre, a running lap
      clock and speed/gear.
- [ ] **Smoothness:** at normal viewing distance the dot glides without jumps or stutter. Notes:
      `______________________`
- [ ] **Map orientation:** once a lap's shape is visible, compare it with the in-game track map. If it is
      mirrored or rotated, reload with `?map=` until it matches. Try `?map=flipz`, `?map=flipx`,
      `?map=flipx,flipz`, `?map=rot90`, `?map=flipz,rot90`, … (any of `flipx`, `flipz`, `rotN`; the active
      setting shows in orange on the map). **Matching value:** `______________`
      Then put it in `config\hub.toml` under `[map]` (e.g. `?map=flipz,rot90` → `flip_z = true`,
      `rotate_deg = 90`). It takes effect at the next hub start (section 6).
- [ ] **Views:** press `2`: the leaderboard view (today / this week / all time). Press `1`: race view.
      Press `0`: back to auto. `?view=board` and `?view=race` fix a view the same way.
- [ ] **Attract mode:** go to the game's menu and wait. After about 10 s the TV shows `Attract mode` and
      alternates between the leaderboard view (20 s) and the race view (10 s). Back on track, it returns to
      the race view.
- [ ] **Reconnect:** turn the TV device's network off for about 10 s and back on (skip this if the TV is
      connected to the hub PC itself): `Reconnecting to hub`, then `Live` again, without a reload.

## 5. Lap behaviour (keep the hub running from section 4)

Drive this sequence in Time Trial. Write down the in-game times and keep an eye on the hub window; every
step lists the assumptions it checks. Afterwards, fill in the results table in
[LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md) from the lap debug log (each assumption says what to look for).

| # | Do this | Write down | Checks |
|---|---|---|---|
| 1 | Leave the garage and drive the out lap to the line. | — | A8, A13 |
| 2 | Drive **3 clean timed laps**. | Lap time, S1, S2, S3 for each lap | A1, A2, A3, A4, A12, A15 |
| 3 | Drive **one lap cutting a corner** (invalid). | Its lap number | A11 |
| 4 | Mid-lap, use **one flashback** (no line crossing in between). | Lap number | A6 |
| 5 | Just after crossing the line, **flashback to before the line**. | Lap number | A6 |
| 6 | Pause → **Restart lap** (or restart the Time Trial). | What the game did | A7 |
| 7 | Drive 2 more clean laps. | Times | A2, A7 |
| 8 | Go to the menu for ~15 s, then back on track. | — | attract mode, state |

While you drive, check on the TV:

- [ ] **Lap clock and sectors:** the clock matches the in-game timer, and S1 and S2 turn coloured as you
      cross the sector lines. Purple = fastest on this track today (all rigs); green = your own best this
      session; yellow = slower. Grey = the lap is invalid.
- [ ] **Invalid lap:** the row shows `Invalid` and the clock is struck through from the moment of the cut.
- [ ] **Last / Best:** after each lap, `Last` shows the lap time from the HUD, and `Best` your best valid lap
      (purple when it's the fastest today, green otherwise).
- [ ] **Track outline:** after the first clean lap the faint path is replaced by the solid track outline,
      with the start/finish line and two sector marks in the right places.
- [ ] **Leaderboard:** each clean lap that beats your best updates "Fastest today" and the leaderboard view.
      The invalid lap and the out lap never appear.
- [ ] **Hub window:** with `--lap-debug`, each line crossing logs `lap_started`, `session_history_update`
      and `lap_completed ... source=session_history`. Note any `lap_data_fallback` or `lap_retracted` lines.

## 6. Restart: leaderboard persistence and a hub restart mid-session

- [ ] Stay on track, mid-lap. In the hub window press **Ctrl+C**. The hub stops; the recording is closed.
- [ ] Start it again the same way (`run --record --lap-debug`); it starts a new recording and a new lap
      debug log (note the names: `______________________`).
- [ ] The TV reconnects by itself. The **leaderboard view still shows the laps from section 5** (today,
      this week, all time). The map uses the `[map]` value you set in section 4, and the outline is there
      straight away.
- [ ] Finish the lap you were on: it's recorded normally, and no burst of old laps appears (A9).
- [ ] Change to **another track** (new Time Trial session): the hub logs one `reset reason=session_changed`
      (A10); the TV shows the new track; boards for the new track start empty.
- [ ] Stop the hub with **Ctrl+C**.

## 7. Two rigs: live drive + your recording as Rig 2

Back on the **track from section 5**. The hub replays your first recording as a second PC while you drive:

```powershell
.venv\Scripts\python -m simtelemetry replay data\recordings\<file from section 4>.f1rec --as-ip 192.0.2.2 --live --lap-debug
```

(`192.0.2.2` is a documentation-only address, so it can't clash with a real PC. The replay starts at the
beginning of the recording, menus included, and plays in real time. It doesn't add its laps to the
leaderboards unless you add `--save-laps`.)

- [ ] **Two rigs:** `Rig 1` (live) and `Rig 2` (192.0.2.2) in the status bar and the timing strip, with
      different colours, both on the same track.
- [ ] **Map:** two numbered dots, each with its own trail colour, both moving smoothly.
- [ ] **Head-to-head (Δ column):** once both rigs have a best lap, Δ shows each rig's live gap to the other
      rig's best lap at the same point on track: green when ahead, red when behind. It matches your sense
      of the gap (e.g. compare with the in-game delta to your PB if you drive the same pace).
- [ ] **Replay ends:** about 5 s after the recording finishes, Rig 2 shows `No data`; your live rig carries on.
- [ ] If the hub warns `Live packets are arriving from 192.0.2.2`, something really uses that address:
      rerun with another `--as-ip` from `192.0.2.x`.

## 8. Wrap up

- [ ] Fill in the results table in [LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md) (confirmed, or what you saw).
- [ ] Send: the recordings, the lap debug logs, `data\logs\hub.log`, this checklist with your notes, and the
      `[map]` value that matched.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Nothing printed, no "New rig detected" | Firewall (section 1); network profile Public; UDP Telemetry off; wrong IP or port in the game; a VPN adapter on the rig PC. |
| `ERROR: UDP port 20777 is already in use` | Another program (SimHub, another telemetry app, a second hub) holds the port. Close it, or use `--port 20778` and set 20778 in the game. |
| `ERROR: HTTP port 8000 is already in use` | Close the other program, or use `--http-port 8001` and open that port on the TV. |
| `drops: unsupported_format=...` | The game sends a format other than 2025/2026. Fix UDP Format in the game. |
| `drops: size_mismatch=...` | Packet size differs from the spec (e.g. a game patch). Keep the recording and report it. |
| Stuck on `in_menu_paused` while driving | No Motion packets for the player's car. Check the `Motion=` rate in the summary; report with the recording. |
| No `lap_completed` after crossing the line | Look for `session_history_update` and `lap_data_fallback` in the lap debug log; report with the log. |
| TV shows "The dashboard hasn't been built yet" | Run `npm run build` in `dashboard\` (section 0), then reload. |
| TV can't open the page | Firewall rule for TCP 8000; use the hub's IP, not `localhost`, on another device. |
| TV stuck on `Connecting to hub` | `/ws` blocked, e.g. by a proxy or browser extension. Try another browser. |

Add `-v` for debug logging; the full log is in `data\logs\hub.log`.
