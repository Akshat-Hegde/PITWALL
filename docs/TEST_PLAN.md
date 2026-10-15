# Test plan: end-to-end test with 2 PCs, 2 copies of F1 25

Goal: run the whole system against the real game once, end to end, with two real rigs: telemetry in from
both, laps and sectors, head-to-head, the TV dashboard, driver names, leaderboards that survive a restart,
and the lap-tracking assumptions in [LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md). Work through the parts in
order and tick each box. Note anything unexpected next to the box; that note matters more than the tick.

**Setup**

| Device | Role |
|---|---|
| **Hub PC** | Runs the hub **and** F1 25 as **Rig 1** (sends telemetry to the hub PC's own network address, not `127.0.0.1`). |
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
      The last line says `passed` with no failures. If anything fails, stop and send the output.
- [ ] Build the dashboard (needs Node.js 20+):
      ```powershell
      cd dashboard
      npm install
      npm run build
      cd ..
      ```
- [ ] Config: `Copy-Item config\hub.example.toml config\hub.toml`. Leave it as it is for now (the cafe name,
      PINs and opening hours are chosen on the setup page; `[map]` comes in Part F).
- [ ] Setup: start the hub once (`.venv\Scripts\python -m simtelemetry run`), open `http://localhost:8000/setup`,
      enter the setup code from the hub window, and choose a cafe name, opening hours, an owner PIN and a staff
      PIN. Stop the hub with **Ctrl+C**.
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

In F1 25: **Game Options › Settings › UDP Telemetry Settings** (the same on both PCs, see
[RIG_SETUP.md](RIG_SETUP.md)):

| Setting | Both PCs (Rig 1 and Rig 2) |
|---|---|
| UDP Telemetry | On |
| UDP Broadcast Mode | Off |
| UDP IP Address | **the hub PC's IP** (also on the hub PC itself, not 127.0.0.1) |
| UDP Port | 20777 |
| UDP Send Rate | 20Hz |
| UDP Format | **2025** |

Your Telemetry may stay Restricted.

- [ ] Both settings done. Both go into **Time Trial on the same track**: `______________`

## Part C: Connection check

On the hub PC: `.venv\Scripts\python -m simtelemetry listen --no-record`. Both drivers drive.

- [ ] `New rig detected: <hub PC IP> (this PC) -> Rig 1` and `New rig detected: <second PC IP> -> Rig 2`.
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

- [ ] **TV:** cafe name and both drivers on the LIVE page. The TV never shows addresses, warnings or connection
      text; the staff page's **Health** tab shows Rig 1 and Rig 2 **On track** and no warnings.
- [ ] **Today's board and focus card:** each game's player name; the focus card shows the running lap,
      speed and gear of the hottest lap (MULTIVIEW, key `2`, shows both rigs' speed, gear and lap time).
- [ ] **Map:** two numbered dots in different colours with fading trails; a faint line of the path driven
      builds up the track shape.
- [ ] **Smoothness:** at normal viewing distance both dots glide without jumps or stutter. Notes:
      `______________________`
- [ ] **Map orientation:** after a full lap, compare the drawn shape with the in-game track map. If it is
      mirrored or rotated, reload with `?map=` until it matches: `?map=flipz`, `?map=flipx`,
      `?map=flipx,flipz`, `?map=rot90`, `?map=flipz,rot90`, … (any of `flipx`, `flipz`, `rotN`; the active
      setting shows in orange on the map). **Matching value:** `______________`
- [ ] **Pages:** on the TV PC's keyboard, `1` = LIVE, `2` = MULTIVIEW; or choose the page on `/staff` (Rigs tab,
      **TV** panel). On a phone use `?view=live` / `?view=multi` / `?view=board` / `?view=attract`.
- [ ] **Attract mode:** both drivers go to the menu. After about 60 s the TV shows the welcome and leaderboard
      screens. Back on track, it returns to the page.
- [ ] **Reconnect** (if the screen is a separate device): turn its network off for ~15 s and back on. No
      connection text appears; after about 10 s the cars leave the screen (waiting or attract screen), and once
      the network is back the live cars return by themselves, without a reload.

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
- [ ] **Live delta:** once both rigs have a clean lap, the focus card shows the live gap to today's record at
      the same point on track. It matches who is actually quicker. On `/staff`, **Show head to head** shows
      the two drivers' mini-sectors and speed traces.
- [ ] **Leaderboards** (today's board on LIVE and the attract leaderboard) list both drivers, fastest first, with
      correct gaps.
- [ ] **Hub window:** with `--lap-debug`, each line crossing logs `lap_started`, `session_history_update`
      and `lap_completed ... source=session_history` for that rig. Note any `lap_data_fallback` or
      `lap_retracted` lines.

**Staff page.** On a phone, open `http://<hub PC IP>:8000/staff`.

- [ ] Both rigs are listed under **Rigs** with "Laps now saved as <game name> (name from the game)".
- [ ] Type a walk-in name for Rig 2, choose **10 min**, **Start session**: the TV shows **Now driving** with the
      name (no timer on the TV; the time left is on the staff page). Driver 2's next lap is saved under that
      name; earlier laps keep the game name.
- [ ] **Queue** tab: add two names. The TV's attract screen shows them as **Next up**.
- [ ] **Drivers** tab: create a profile with your own phone number. Without ticking the consent box you get
      an error; with it the profile is created. Search for it by the last 4 digits.
- [ ] On the profile, **Use for the next free rig**, then on **Rigs** press the ★ name on Rig 1 with
      **5 min**: the rig card shows "5 minutes left. Extend?"; **+5 min** makes it 10.
- [ ] Drive a lap, then open the profile again: the visit and the best lap are listed.
- [ ] **End session** on both rigs: it asks "End <name>'s session on Rig 1? Their card will be made now." first;
      then the names go back to the game's names.
- [ ] **End session** on a rig whose driver set a clean lap: the staff page shows a QR code and the TV shows one
      bottom left for 30 seconds. Scan it with a phone on the same Wi-Fi: the card opens with the best lap,
      top speed and the mini-sector map. **Save image** downloads it; **Share on WhatsApp** opens WhatsApp.
- [ ] **Compete** tab: create a challenge on the track you're driving, Pro, today to today, prize "Test".
      The TV's leaderboard view shows it; a Pro lap puts the driver on it.
- [ ] Start a corporate event (any name, company colour blue, best N = 1), add two teams with one driver each,
      upload any PNG as the logo. Add drivers by searching their profile, or with **Add walk-in** (quick profile).
      Start a session for that driver from the profile (★ on the Rigs tab) so their laps count for the team. The TV turns blue and shows the company next to the cafe name;
      **Show teams** on `/staff` puts the team board on the TV. After a lap from each driver the teams are ranked. **End event**.
- [ ] Open `/owner` and enter the owner PIN: today's sessions and laps appear; **Daily CSV** downloads a file.
- [ ] At the end of the test: **Delete profile** on your test profile; its laps disappear from the boards.
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
- [ ] Open the TV with `?view=attract`: the welcome screen. Remove it to go back to normal.

## Part E3: LAN race, podium and race card (both rigs)

- [ ] Optional: in `/setup` add a guest Wi-Fi name and password; a phone on that network can join via the TV QR
      (the network must reach the hub PC: see Part H, phone test).
- [ ] The hub from Part B is still running and recording (`.venv\Scripts\python -m simtelemetry run --record
      --lap-debug` holds UDP 20777), so do not start `listen` or a second hub. That recording is the regression
      fixture for Final Classification: keep the `.f1rec` from this race in `data\recordings\` (note its name:
      `______________________`).
- [ ] Both rigs join ONE F1 25 LAN lobby race (Multiplayer > LAN, one hosts, the other joins; AI on, any
      length) on the same track. Two separate single-player races on the same track do not count.
- [ ] Finish the race on both rigs. Within about 10 seconds the TV shows the race podium for 15 s, with a QR
      beside each name, then "Grab your card" for 25 s with the Wi-Fi tile (SSID only, no password).
- [ ] Scan a QR from a phone on the cafe Wi-Fi: the race card shows position (real race position), grid,
      places gained, laps, best lap, total time, result, and "1st of 2 at <cafe>". **Save for Instagram story** works.
- [ ] Repeat with only one rig racing: no podium, but the corner card QR shows a race card.
- [ ] Time Trial and Practice sessions produce no podium.
- [ ] Note any wrong Final Classification fields (position, grid, status, total time) and keep the `.f1rec`.

## Part E4: Phone check-in (one rig, hub still running)

- [ ] Staff -> **Check-in QR**: print the sheet (or open it on screen). It has one sticker per rig.
- [ ] Phone on the cafe Wi-Fi: scan the Rig 1 sticker. The page says "Drive this rig" and asks for a name.
- [ ] Enter a name and tap **Start**: the TV shows **Now driving** with that name. The phone shows
      "You're on Rig 1. Drive!".
- [ ] Drive a lap: the phone's Laps and Best lap update within a few seconds; the lap is saved under that name.
- [ ] Tap **I'm done** and confirm: the phone shows "Nice driving" and **Save for Instagram story** opens the card.
- [ ] Busy rig: start a session from the staff page, then scan that rig's sticker: "Someone is driving", no way to check in.
- [ ] Staff session is never taken over: start a session from the staff page, leave the game in the menu (not
      driving) for over 5 minutes, then scan the sticker from a phone: still "Someone is driving", no name form.
      End it from the staff page.
- [ ] Takeover: on phone A check in as one name and drive one lap (so a card exists), then go back to the game
      menu and leave it there for over 5 minutes. Scan the same sticker on phone B (a different phone, or a
      private/incognito tab so it has no saved session): it says "This rig looks free" with the name form.
      Enter a second name and tap **Start**: phone B shows "You're on Rig 1", the TV shows the new name, and
      within a few seconds phone A shows "Nice driving" with **Save for Instagram story** for its lap.
- [ ] Try a rude name: it is refused with a friendly message.
- [ ] **New code** on Rig 1: scanning the old sticker says the code is no longer valid.

## Part F: Restart (leaderboard persistence) and track change

- [ ] Both drivers stay on track, mid-lap. In the hub window press **Ctrl+C**.
- [ ] Put the matching map value in `config\hub.toml`, e.g. `?map=flipz,rot90` becomes:
      ```toml
      [map]
      flip_x = false
      flip_z = true
      rotate_deg = 90
      ```
- [ ] Start the hub again: `.venv\Scripts\python -m simtelemetry run --record --lap-debug` (a new recording
      and lap debug log; note the names: `______________________`).
- [ ] The dashboard reconnects by itself (remove `?map=` from its address). The **leaderboards still show
      both drivers' laps** with the same names; a name set on `/staff` is still set; the map is drawn the
      right way round and the outline is there straight away.
- [ ] Both finish the lap they were on: recorded normally, no burst of old laps (A9).
- [ ] `/staff` asks for the staff PIN; a wrong PIN shows `Wrong PIN.`, the right one opens the page.
- [ ] Both change to **another track** (new Time Trial session): one `reset reason=session_changed` per rig
      in the hub window (A10); the dashboard follows; the new track's boards start empty.
- [ ] Stop the hub with **Ctrl+C**.

## Part G: Wrap up

- [ ] Fill in the results table in [LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md) from the lap debug logs (each
      assumption says which lines to look for). If that's too fiddly, just send the logs.
- [ ] Send: everything in `data\recordings\` and `data\logs\`, this checklist with your notes, both drivers'
      in-game times, and the matching `[map]` value.

## Part H: Commercial checks (version 0.5.0)

These check the behaviour added for cafes. Use the installed hub (docs/INSTALL-TEST.md) or the hub from source.
The installer's own checks are in [INSTALL-TEST.md](INSTALL-TEST.md), step 11.

**Sessions end automatically (U2)**

- [ ] On `/setup`, set the closing time to the next full hour (or the next hour that is a few minutes away).
      Start a staff session on Rig 1 and a phone check-in on Rig 2, and drive a clean lap on each. At closing
      time both end by themselves; the staff page says "Ended automatically at closing time", and the TV and
      staff page show the card QR codes.
- [ ] Start a **10 min** session and keep driving past 10 minutes: it is not ended while the car is on track.
      Go to the menu: about 5 minutes later it ends with "Ended automatically: time was up".
- [ ] A session with no timer and a phone check-in session are not ended for being long; only at closing time.
- [ ] Optional, overnight: leave a session open and switch the hub PC off before closing time. Start it the next
      day: the session ends straight away, with a card if there was a clean lap.
- [ ] With `[features] auto_end_sessions = false` in `hub.toml` (restart the hub), nothing ends by itself.

**Staff PIN (U3)**

- [ ] On a fresh setup, saving `/setup` without a staff PIN is refused: "Choose a staff PIN (4 to 8 digits). It
      may be the same as the owner PIN."
- [ ] Optional, with a backup or data folder from before 0.5.0 that has no staff PIN: the staff page accepts the
      owner PIN and shows the red "Set a staff PIN on the setup page" banner until one is set.
- [ ] Type a wrong PIN on `/staff` five times: that device is locked out for a minute. Do it three times within
      an hour: locked out for 15 minutes, and the owner page shows "Someone tried wrong PINs 15 times at …".

**Phone test and guest Wi-Fi (U4)**

- [ ] On `/setup`, scan **Test from your phone** with a phone on the guest Wi-Fi: the phone says "Your phone can
      reach Pitwall. Check-in and cards will work.", and `/setup` shows "A phone reached the hub at <time>".
      The staff page's Health tab has the same QR.
- [ ] If you have a guest network with client isolation on: the page doesn't open on a phone on it. Note what
      the router calls the isolation setting.

**Hub address change (K4)**

- [ ] Give the hub PC a different address (change its reservation in the router and restart the PC, or switch it
      to another network port). The staff page and `/setup` show "This PC's network address changed from A to
      B. On every rig set UDP IP Address to B, and reprint the check-in stickers. …". The TV shows nothing about
      it. **OK, done** removes it. The check-in sticker sheet shows the new address. Put the address back after.
- [ ] Unplug the hub PC's network cable and open the sticker sheet on the hub PC: it warns that the address is
      missing. Plug it back in.

**Rigs (K5, K6)**

- [ ] On `/setup`, drive on Rig 2: it says **Moving now**. Rename it (a 17th character can't be typed); the TV
      shows the new name.
- [ ] Set Rig 2's UDP Format to 2024 (or anything but 2025): the rig shows **Wrong game settings** on the staff
      Health tab, not "In menu". Set it back to 2025.
- [ ] From a PC that has never sent telemetry, send in the wrong format: no new rig appears; the Health tab says
      "A PC at <address> is sending telemetry in the wrong format: set UDP Format to 2025."
- [ ] Give Rig 2's PC a new address: it shows up as a new rig. On `/setup` choose **Same rig as…** and its old
      entry: the name, colour, number and check-in sticker move over, and the old entry is gone.
- [ ] **Forget** a rig that no longer exists: it leaves `/setup`, the staff page and the sticker sheet.
- [ ] During opening hours, switch Rig 2's game off for over 10 minutes: the Health tab shows "On Rig 2 check:
      UDP Telemetry On · UDP IP Address = <hub address> · Port 20777 · Format 2025, then drive out of the
      garage." once that day.

**Pause, replay and spectating (K7)**

- [ ] In a single-player **Time Trial**, pause the game for 20 s: within a few seconds the Health tab shows Rig 1
      **In menu**, not On track, and the rig no longer counts as driving (with every rig paused, the TV goes to
      attract mode after 60 s). Unpause and drive on: **On track** again, and the lap continues normally.
- [ ] Watch a replay (instant replay, or the replay after a session): the rig does not count as driving. Note
      what the Health tab shows.
- [ ] In the LAN race, after finishing, spectate the other car: that rig is not driving.
- [ ] Pull Rig 2's network cable for 10 s while driving, then plug it back in: the car comes back on the TV with
      its laps, bests and trail; no `reset reason=session_changed` in the lap debug log.

**Staff page (K8, K10)**

- [ ] **Remove** in the queue and **×** on a team member ask before removing.
- [ ] Start a name that is already on today's board: it asks "There's already a <name> today. Same person?"
      with **Same person** and **Add a letter**.
- [ ] End a session with no clean lap: "No card this time: no clean lap was completed."
- [ ] Stop the hub while the staff page is open: "Can't reach the hub …" appears; start the hub: it goes away by
      itself.
- [ ] Names longer than 16 characters can't be entered on the staff page or at check-in. "Lauda" is accepted.
- [ ] On an iPhone, **Save for Instagram story** shows the picture full screen with "Press and hold the
      picture, then tap Save to Photos".

**Open past midnight (K9)**

- [ ] On `/setup`, the closing time can be 01:00 to 06:00 "(next day)" and the page says "Closes at 02:00 (next
      day)". If you can test after midnight: with closing at 02:00, a lap at 00:30 is on the same "today" board
      as the evening's laps, and sessions end at 02:00.

**Backups (K11)**

- [ ] On `/owner`, Backups card: type a folder on a USB stick (for example `E:\Backups`), **Use this folder**,
      **Back up now**: a zip appears there. It contains the laps, settings, check-in codes and logos.
- [ ] Unplug the stick and press **Back up now**: "The USB stick isn't plugged in (drive E: not found)."
- [ ] Type a network folder (`\\server\share`): refused, "Network folders aren't supported …".
- [ ] Restore that backup by following [INSTALL.md](INSTALL.md), "Restoring a backup": laps, rig names and the
      logo come back.
- [ ] Optional: with backups failing for over 2 days, the owner page and the staff Health tab show "Last backup:
      N days ago. Check the backup folder or USB stick." (never on the TV).

**TV (K12)**

- [ ] Restart the hub with the TV open: the TV comes back by itself, without anyone touching the TV PC.
- [ ] Upgrade the hub (or run a newer build): the TV reloads itself within a minute. From 0.5.0 on, TVs reload
      themselves after an update; when upgrading from 0.4, restart each TV PC once (or press F5 on the TV) first.
- [ ] Set the TV PC's clock 5 minutes wrong: lap times, moments and the session story still look right.
- [ ] With 7 or more rigs (real or `?source=mock&rigs=9`), MULTIVIEW shows every rig in a grid.

**Start-up problems (K1)**

- [ ] Put a mistake in `hub.toml` (for example `http_port = "abc"`) and restart the hub: it starts; the staff
      and setup pages say "Your settings file (hub.toml) has a mistake … The hub started with default
      settings." (with the line number when the file itself can't be read). Fix it and restart: the message is gone.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Rig 2 never detected | Wrong UDP IP Address in Rig 2's game; UDP firewall rule missing; network profile Public; PCs on different networks (guest Wi-Fi); a VPN on either PC. |
| Rig 1 never detected | UDP IP Address on the hub PC must be the hub PC's network address (not `127.0.0.1`); UDP Telemetry off. |
| `WARNING: rigs are sending different packet formats` | Set UDP Format to 2025 on both games. |
| "Another program is using port 20777 (often SimHub)" | Another program (SimHub, another telemetry app, a second hub) holds the port. Close it, or change that program's port (RIG_SETUP.md, SimHub). The hub keeps the pages running and tries again every 30 s. |
| `ERROR: HTTP port 8000 is already in use` | Close the other program, or use `--http-port 8001` and use that port in the dashboard address. |
| `drops: size_mismatch=...` / `unsupported_format=...` | Packet format differs from the spec, or not 2025/2026. Keep the recording and report it. |
| Stuck on `in_menu_paused` while driving | No Motion packets for that car. Check the `Motion=` rate in the summary; report with the recording. |
| No `lap_completed` after crossing the line | Look for `session_history_update` and `lap_data_fallback` in the lap debug log; report with the log. |
| Dashboard says "The dashboard hasn't been built yet" | Run `npm run build` in `dashboard\` (Part A), then reload. |
| Dashboard page doesn't load on another device | TCP 8000 firewall rule; use the hub PC's IP, not `localhost`. |
| TV stays on the waiting screen while cars are driving | `/ws` blocked, e.g. by a proxy or browser extension. Try another browser. |

Add `-v` for debug logging; the full log is in `data\logs\hub.log`.
