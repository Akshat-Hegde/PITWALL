# Test plan: end-to-end test with 2 PCs, 2 copies of F1 25

Goal: run the whole system against the real game once, end to end, with two real rigs: telemetry in from
both, laps and sectors, head-to-head, the TV dashboard, driver names, leaderboards that survive a restart,
and the lap-tracking assumptions in [LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md). Work through the parts in
order and tick each box. Note anything unexpected next to the box; that note matters more than the tick.

**Setup**

| Device | Role |
|---|---|
| **Hub PC** | Runs the hub **and** F1 25 as **Rig 1** (sends telemetry to `127.0.0.1`). |
| **Second PC** | F1 25 as **Rig 2** (sends telemetry to the hub PC over the LAN). |
| **Dashboard screen** | A phone, tablet or laptop browser, or a TV / second monitor. Both games run full screen, so a separate device is easiest. |

Two people drive: **Driver 1** on the hub PC, **Driver 2** on the second PC.

**What you send back afterwards:** the recording(s) from `data\recordings\`, the logs from `data\logs\`
(`lap-debug-*.log` and `hub.log`), this checklist with notes, both drivers' in-game lap times, and (if you
can) the filled-in results table at the end of [LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md).

---

## Part A: Prepare the hub PC (once)

Open PowerShell in the project folder (`cd "X:\SIM TELEMETRY APP"`).

- [ ] Install and test:
      ```powershell
      .venv\Scripts\python -m pip install -e ".[dev]"
      .venv\Scripts\python -m pytest
      ```
      The last line says about `408 passed`. If anything fails, stop and send the output.
- [ ] Build the dashboard (needs Node.js 20+):
      ```powershell
      cd dashboard
      npm install
      npm run build
      cd ..
      ```
- [ ] Config: `Copy-Item config\hub.example.toml config\hub.toml`, then `notepad config\hub.toml`. Set
      `[cafe] name` if you like. Leave `[map]` and `[staff] pin` as they are for now.
- [ ] Free space: `Get-PSDrive -PSProvider FileSystem`. At least 10 GB free on the drive with `data\`
      (recording uses about 0.75 GB per rig per hour), and some free on C:.
- [ ] Fresh start: if a `data\` folder exists from earlier experiments, rename it (e.g. `data-old`).
- [ ] Hub PC IP address: `ipconfig` → **IPv4 Address** of the Ethernet/Wi-Fi adapter: `__________`
- [ ] Second PC IP address (`ipconfig` on that PC): `__________`

**Network and firewall.** Right-click Start → **Terminal (Admin)**:

- [ ] `Get-NetConnectionProfile`. If `NetworkCategory` is **Public**:
      `Set-NetConnectionProfile -InterfaceAlias "<InterfaceAlias shown>" -NetworkCategory Private`
- [ ] Allow telemetry from the second PC and the dashboard from other devices:
      ```powershell
      netsh advfirewall firewall add rule name="Sim Telemetry UDP 20777" dir=in action=allow protocol=UDP localport=20777 profile=private
      netsh advfirewall firewall add rule name="Sim Telemetry HTTP 8000" dir=in action=allow protocol=TCP localport=8000 profile=private
      ```
- [ ] If Windows asks *"Windows Defender Firewall has blocked some features of Python"* on the first hub
      start: tick **Private networks** only and allow. (The hub PC's Python is the Microsoft Store build,
      whose program rules are unreliable; the port rules above are what matters.)
- [ ] Both PCs on the same router/network (not a guest Wi-Fi), no VPN running on either.

## Part B: Game settings on both PCs

F1 25 → Settings → **Telemetry Settings**:

| Setting | Hub PC (Rig 1) | Second PC (Rig 2) |
|---|---|---|
| UDP Telemetry | On | On |
| UDP Broadcast Mode | Off | Off |
| UDP IP Address | **127.0.0.1** | **hub PC's IP** |
| UDP Port | 20777 | 20777 |
| UDP Send Rate | 60Hz | 60Hz |
| UDP Format | **2025** | **2025** (must match) |

- [ ] Both settings done. Both go into **Time Trial on the same track**: `______________`

## Part C: Connection check

On the hub PC: `.venv\Scripts\python -m simtelemetry listen --no-record`. Both drivers drive.

- [ ] `New rig detected: 127.0.0.1 (this PC) -> Rig 1` and `New rig detected: <second PC IP> -> Rig 2`.
- [ ] Two status lines per second, both `fmt=2025`, both `driving` on track and `in_menu_paused` when paused.
- [ ] The 10 s summary shows `drops: none` for both rigs, and no
      `WARNING: rigs are sending different packet formats`.
- [ ] Driver and track names are right; lap number, lap time and speed match each game's HUD.

If Rig 2 never appears: recheck its UDP IP Address, the UDP firewall rule, the network profile (Private),
VPNs, and that both PCs are on the same network. `size_mismatch`, `unsupported_format` or
`unknown_packet_id` drops are blockers: stop and send the output. Stop with **Ctrl+C**.

## Part D: Main run, both rigs (keep it running through Part E)

```powershell
.venv\Scripts\python -m simtelemetry run --record --lap-debug
```

The log shows `Dashboard on http://localhost:8000/`, `Lap debug log: data\logs\lap-debug-...log` and
`Recording raw packets to data\recordings\...f1rec` (one recording holds both rigs). Note both file names:
`______________________` `______________________`

On the dashboard screen, open `http://<hub PC IP>:8000/` (F11 for full screen).

- [ ] **Status bar:** cafe name, Rig 1 and Rig 2 `On track` with `F1 2025` and the track, `Live`, no warnings.
- [ ] **Timing strip:** two rows with each game's player name, tyre, running lap clock, speed and gear.
- [ ] **Map:** two numbered dots in different colours with fading trails; a faint line of the path driven
      builds up the track shape.
- [ ] **Smoothness:** at normal viewing distance both dots glide without jumps or stutter. Notes:
      `______________________`
- [ ] **Map orientation:** after a full lap, compare the drawn shape with the in-game track map. If it is
      mirrored or rotated, reload with `?map=` until it matches: `?map=flipz`, `?map=flipx`,
      `?map=flipx,flipz`, `?map=rot90`, `?map=flipz,rot90`, … (any of `flipx`, `flipz`, `rotN`; the active
      setting shows in orange on the map). **Matching value:** `______________`
- [ ] **Views:** on a keyboard, `2` = leaderboard view, `1` = race view, `0` = auto. On a phone use
      `?view=board` / `?view=race` / no `view` for auto.
- [ ] **Attract mode:** both drivers go to the menu. After about 10 s the screen shows `Attract mode` and
      alternates the leaderboard view (20 s) and race view (10 s). Back on track, it returns to the race view.
- [ ] **Reconnect** (if the screen is a separate device): turn its network off for ~10 s and back on:
      `Reconnecting to hub`, then `Live` again, without a reload.

## Part E: Laps (both drivers, hub still running)

**Driver 1 (hub PC)** drives this sequence; every step lists the assumptions in
[LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md) it checks. **Driver 2** drives an out lap, 4–5 clean laps and one
cut lap at the same time. Both write down the in-game times.

| # | Driver 1 does this | Write down | Checks |
|---|---|---|---|
| 1 | Leave the garage and drive the out lap to the line. | — | A8, A13 |
| 2 | Drive **3 clean timed laps**. | Lap time, S1, S2, S3 for each lap | A1, A2, A3, A4, A12, A15 |
| 3 | Drive **one lap cutting a corner** (invalid). | Its lap number | A11 |
| 4 | Mid-lap, use **one flashback** (no line crossing in between). | Lap number | A6 |
| 5 | Just after crossing the line, **flashback to before the line**. | Lap number | A6 |
| 6 | Pause → **Restart lap** (or restart the Time Trial). | What the game did | A7 |
| 7 | Drive 2 more clean laps. | Times | A2, A7 |
| 8 | Go to the menu for ~15 s, then back on track. | — | attract mode, state |

On the dashboard, check:

- [ ] **Lap clocks and sectors** match each game. S1 and S2 turn coloured at the sector lines:
      purple = fastest of both rigs on this track today, green = that driver's own best this session,
      yellow = slower; grey when the lap is invalid.
- [ ] **Invalid laps** show `Invalid` with the clock struck through from the moment of the cut, and never
      reach the leaderboard. Out laps never reach it either.
- [ ] **Last / Best** after each lap match the game; `Best` is purple when it's the fastest lap today,
      green otherwise. `PB` in the row shows that driver's best ever on this track.
- [ ] **Track outline:** after the first clean lap from either rig, the faint path is replaced by the solid
      track with the start/finish line and two sector marks in the right places.
- [ ] **Head-to-head (Δ column):** once both rigs have a clean lap, each row shows the live gap to the other
      rig's best lap at the same point on track: green when ahead, red when behind. It matches who is
      actually quicker.
- [ ] **Leaderboards** ("Fastest today" and the leaderboard view) list both drivers, fastest first, with
      correct gaps.
- [ ] **Hub window:** with `--lap-debug`, each line crossing logs `lap_started`, `session_history_update`
      and `lap_completed ... source=session_history` for that rig. Note any `lap_data_fallback` or
      `lap_retracted` lines.

**Driver names (staff page).** On the dashboard device (or a phone), open `http://<hub PC IP>:8000/staff`.

- [ ] Both rigs are listed with "Laps saved as <game name> (name from the game)".
- [ ] Set a name for Rig 2 and **Save driver**: within a second the dashboard shows it. Driver 2's next lap
      is saved under that name; their earlier laps keep the game name.
- [ ] **End session**: the name goes back to the game's name, and the next lap is saved under it.
- [ ] If both games use the same generic player name, laps from both rigs merge into one leaderboard entry
      until names are set on `/staff`. Note whether that happened (A14).

## Part E2: Broadcast moments, Pro / Open (hub still running)

- [ ] On `/staff`, set a name for Rig 1 and save: the TV shows **Now driving** with that name for about
      4 seconds, then goes back.
- [ ] Driver 1 sets a clean lap faster than today's best: the TV shows **Record** with the new time, the
      gap and the old holder. (No record moment for the very first lap of the day: there's nothing to beat.)
- [ ] Turn every assist off on one rig (traction control, ABS, steering and braking assist, manual gears,
      racing line off) and drive a clean lap: in the hub's lap debug log the lap is `pro`; with ABS on it is
      `open` (A16).
- [ ] On `/staff` press **Show podium**: today's top three for about 10 seconds.
- [ ] When both drivers' best laps are within 0.3 s, a **Battle** pop-up appears bottom right.
- [ ] Open `http://192.168.1.64:8000/portrait` on a phone held upright: cafe name, track record, top 10.
- [ ] Press `5` on the TV PC: the welcome screen. Press `0` to go back to auto.

## Part F: Restart (leaderboard persistence) and track change

- [ ] Both drivers stay on track, mid-lap. In the hub window press **Ctrl+C**.
- [ ] Put the matching map value in `config\hub.toml`, e.g. `?map=flipz,rot90` becomes:
      ```toml
      [map]
      flip_x = false
      flip_z = true
      rotate_deg = 90
      ```
- [ ] Optional: set `[staff] pin = "1234"` too.
- [ ] Start the hub again: `.venv\Scripts\python -m simtelemetry run --record --lap-debug` (a new recording
      and lap debug log; note the names: `______________________`).
- [ ] The dashboard reconnects by itself (remove `?map=` from its address). The **leaderboards still show
      both drivers' laps** with the same names; a name set on `/staff` is still set; the map is drawn the
      right way round and the outline is there straight away.
- [ ] Both finish the lap they were on: recorded normally, no burst of old laps (A9).
- [ ] If you set a PIN: `/staff` asks for it; a wrong PIN shows `Wrong PIN.`, the right one opens the page.
- [ ] Both change to **another track** (new Time Trial session): one `reset reason=session_changed` per rig
      in the hub window (A10); the dashboard follows; the new track's boards start empty.
- [ ] Stop the hub with **Ctrl+C**.

## Part G: Wrap up

- [ ] Fill in the results table in [LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md) from the lap debug logs (each
      assumption says which lines to look for). If that's too fiddly, just send the logs.
- [ ] Send: everything in `data\recordings\` and `data\logs\`, this checklist with your notes, both drivers'
      in-game times, and the matching `[map]` value.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Rig 2 never detected | Wrong UDP IP Address in Rig 2's game; UDP firewall rule missing; network profile Public; PCs on different networks (guest Wi-Fi); a VPN on either PC. |
| Rig 1 never detected | UDP IP Address must be `127.0.0.1` on the hub PC; UDP Telemetry off. |
| `WARNING: rigs are sending different packet formats` | Set UDP Format to 2025 on both games. |
| `ERROR: UDP port 20777 is already in use` | Another program (SimHub, another telemetry app, a second hub) holds the port. Close it, or use `--port 20778` and set 20778 in both games. |
| `ERROR: HTTP port 8000 is already in use` | Close the other program, or use `--http-port 8001` and use that port in the dashboard address. |
| `drops: size_mismatch=...` / `unsupported_format=...` | Packet format differs from the spec, or not 2025/2026. Keep the recording and report it. |
| Stuck on `in_menu_paused` while driving | No Motion packets for that car. Check the `Motion=` rate in the summary; report with the recording. |
| No `lap_completed` after crossing the line | Look for `session_history_update` and `lap_data_fallback` in the lap debug log; report with the log. |
| Dashboard says "The dashboard hasn't been built yet" | Run `npm run build` in `dashboard\` (Part A), then reload. |
| Dashboard page doesn't load on another device | TCP 8000 firewall rule; use the hub PC's IP, not `localhost`. |
| Dashboard stuck on `Connecting to hub` | `/ws` blocked, e.g. by a proxy or browser extension. Try another browser. |

Add `-v` for debug logging; the full log is in `data\logs\hub.log`.
