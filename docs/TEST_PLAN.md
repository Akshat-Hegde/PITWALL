# Test plan: single-rig capture, then live + replay

Goal: confirm one real rig's telemetry reaches the hub correctly, capture a recording for golden tests, and
check the TV dashboard. Then simulate a second rig by replaying that recording next to a live drive.
Work through the sections in order and tick each box; don't move on until the current section passes.

Setup for this milestone: **one** PC with F1 25, plus the hub. The hub can run on the same PC as the game
or on a second PC, and the TV shows the dashboard in a browser.

- **Pass 1 (sections 2–4):** you drive alone, the hub records. **Golden tests come from this recording.**
- **Pass 2 (section 5):** you drive live while the hub replays the pass 1 recording as "Rig 2", so the
  dashboard shows two rigs on the same track.

---

## 0. Before you start

- [ ] The rig is configured per [RIG_SETUP.md](RIG_SETUP.md). If the hub runs on the **same PC** as the game,
      set UDP IP Address to `127.0.0.1`. Note the **UDP Format** you chose: `____`
- [ ] Hub PC has the project installed (see README: `python -m venv .venv`, `pip install -e ".[dev]"`).
- [ ] The dashboard is built on the hub PC (needs Node.js 20+), once:
      ```powershell
      cd dashboard
      npm install
      npm run build
      cd ..
      ```
- [ ] **Check free space before capture**, on the recordings drive *and* on C: (Windows, the game and Python
      need it too). Recording uses about 0.75 GB per rig per hour; plan for at least 10 GB free on the
      recordings drive. In PowerShell: `Get-PSDrive -PSProvider FileSystem` (see the `Free` column).
      Recordings go to `data\recordings\` in the project folder unless `[recorder] directory` (or `data_dir`)
      in `config\hub.toml` points elsewhere; use that to put them on a drive with space. Below 5 GB free the
      hub warns; below 1 GB it stops recording (`recording stopped: low disk`) but keeps running.
- [ ] Note the IPv4 addresses (`ipconfig`) if more than one device is involved:
  - Hub: `__________` Rig: `__________` TV / browser: `__________`

## 1. Windows Firewall on the hub PC

Skip this section if the game and the hub run on the same PC and you open the dashboard on that PC too.
Otherwise inbound UDP 20777 (from the rig) and TCP 8000 (for the TV) must be allowed. Without this the
hub receives nothing and shows no errors.

### 1a. Network profile must be Private

Windows blocks most inbound traffic on **Public** networks.

- [ ] Settings → Network & internet → (Ethernet / Wi-Fi) → **Network profile type = Private**.
- Or check in PowerShell:
  ```powershell
  Get-NetConnectionProfile          # NetworkCategory should be Private
  # To change it (Administrator PowerShell):
  Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
  ```

### 1b. Add inbound rules for the ports (recommended)

Run in an **Administrator** Command Prompt or PowerShell:

```bat
netsh advfirewall firewall add rule name="Sim Telemetry UDP 20777" dir=in action=allow protocol=UDP localport=20777 profile=private
netsh advfirewall firewall add rule name="Sim Telemetry HTTP 8000" dir=in action=allow protocol=TCP localport=8000 profile=private
```

Check or remove the rules:

```bat
netsh advfirewall firewall show rule name="Sim Telemetry UDP 20777"
netsh advfirewall firewall delete rule name="Sim Telemetry UDP 20777"
```

If you change `udp_port` or `http_port` in the config, use those ports here too.

### 1c. First-run prompt

The first time the hub starts, Windows may show **"Windows Defender Firewall has blocked some features of
Python"**. Tick **Private networks** only, and click **Allow access**.

> On this hub PC Python is the Microsoft Store build, and the venv's `python.exe` is only a launcher. Firewall
> rules tied to a program are unreliable in that case, so rely on the port rules from 1b. If you dismissed
> the prompt or chose "Public", the port rules still work. (Before packaging, a later milestone, the hub
> moves to a python.org 3.11 install; Store Python is also unreliable with PyInstaller.)

## 2. First contact: `listen` mode

On the hub PC, from the project folder:

```powershell
.venv\Scripts\python -m simtelemetry listen
```

This prints one line per rig per second, plus a health summary every 10 s. It has no dashboard; that comes
in section 3. Stop with **Ctrl+C**. (`listen` also records; you can delete that file, the capture is in
section 4.)

Example status line:

```
14:02:11 Rig 1    192.168.1.21    fmt=2025  Silverstone            lap 3   1:23.456 287 km/h driving
```

Start F1 25 and go into Time Trial. Check, in this order:

- [ ] **Packets arrive.** The log shows `New rig detected: <ip> -> Rig 1`. The IP is the rig PC's
      (or `127.0.0.1 (this PC)` when the game runs on the hub PC).
- [ ] **Correct format detected.** The line shows `fmt=` matching the UDP Format noted in section 0.
- [ ] **Zero size mismatches.** The 10 s summary shows `drops: none`. Any `size_mismatch`,
      `unsupported_format` or `unknown_packet_id` here is a blocker: note it and keep the recording.
- [ ] **Rates look right.** In the summary, `Motion`, `LapData` and `CarTelemetry` are roughly the send rate
      (20 or 30 per second) while driving, and `Session` is about 2.
- [ ] **State follows the game.** In menus or paused the line shows `in_menu_paused`; on track,
      `driving`; with the game closed it shows `no_data` after 5 s.
- [ ] **Driver name.** The log shows `Rig 1 (<ip>) driver: <name>`.
- [ ] **Track name** is correct (e.g. `Silverstone`).
- [ ] **Lap number, lap time and speed match the in-game HUD** while driving (the line updates once per second).

## 3. Dashboard on the TV

Stop `listen` (Ctrl+C) and start the hub in `run` mode **with recording on**. This is also the capture
for section 4, so keep it running from here on:

```powershell
.venv\Scripts\python -m simtelemetry run --record
```

The log shows `Dashboard on http://localhost:8000/`. Open `http://<hub IP>:8000/` in the TV's browser
(`http://localhost:8000/` on the hub PC itself), full screen (F11).

The dashboard doesn't time laps yet (lap tracking is built from this capture), so the lap clock, sectors,
head-to-head and best laps stay empty. Check:

- [ ] **Status bar:** `Rig 1  On track  F1 <format>  <track>`, and `Live` on the right. No warnings.
- [ ] **Rig panel:** driver name, speed, gear, throttle/brake bars and tyre match the game.
- [ ] **State changes:** going to the menu shows `In menu`, and the car dot disappears; back on track it returns.
- [ ] **Map:** the car dot moves with a fading trail, and a faint line of the path driven so far builds up
      the track shape (the full outline comes with lap tracking).
- [ ] **Smoothness:** the dot glides without visible jumps or stutter at normal TV viewing distance.
      Note anything odd: `______________________`
- [ ] **Map orientation:** after a full lap, compare the drawn shape with the in-game minimap / track
      map. If it's mirrored or rotated, try these until it matches, and note the one that does:
      `http://<hub IP>:8000/?map=flipz`, `?map=flipx`, `?map=flipx,flipz`, `?map=rot90`, `?map=flipz,rot90`, ...
      (any combination of `flipx`, `flipz`, `rotN`; the active setting is shown in orange on the map).
      Matching value: `______________`
- [ ] **Reconnect:** unplug the TV's network cable or turn its Wi-Fi off for ~10 s, then reconnect: the
      dashboard shows `Reconnecting to hub` and comes back to `Live` by itself, without a page reload.
      (Don't restart the hub here; that would split the capture into two recordings.)

## 4. Capture for golden tests

With `run --record` still running, check the 10 s summary in the hub window shows no `low disk space`
warning and no `recording stopped` line. Then:

- [ ] Drive at least **3 timed laps**. Write down from the HUD / Time Trial screen: lap time and S1/S2/S3
      for each lap, and which laps were **invalid**.
- [ ] Drive **one deliberately invalid lap** (cut a corner) and note its number.
- [ ] Use **one flashback** during a lap, and note the lap.
- [ ] Return to the menu for ~10 s, then back on track.
- [ ] Stop the hub with **Ctrl+C**. This flushes and closes the recording.

Recordings are in `data\recordings\` (`YYYYMMDD-HHMMSS-NNN.f1rec`; a new file starts every 256 MB, and the
newest 24 files are kept). Note the file name: `______________________`. You can check it plays back:

```powershell
.venv\Scripts\python -m simtelemetry replay data\recordings\<file>.f1rec --speed 4 --no-api
```

## 5. Second pass: live drive + recording as Rig 2

Same track as pass 1. The hub replays your pass 1 recording as if it came from a second PC, and listens
for your live drive at the same time:

```powershell
.venv\Scripts\python -m simtelemetry replay data\recordings\<file>.f1rec --as-ip 192.0.2.2 --live
```

- `--as-ip 192.0.2.2` makes the recording show up as a separate rig. `192.0.2.2` is a documentation-only
  address that no real PC uses, so it can't clash with your rig (including `127.0.0.1`).
- The recording plays in real time from the start, including any time spent in menus. Start driving when
  the replayed car is on track.
- `--live` keeps the hub and dashboard running after the replay ends. Stop with **Ctrl+C**.
- This pass doesn't record. The golden tests come from pass 1 only.

On the TV (refresh the page if it was open):

- [ ] **Two rigs:** the status bar shows `Rig 1` (live) and `Rig 2` (192.0.2.2, the replay), both
      `On track` on the same track, with different colours. No format warning.
- [ ] **Map:** two numbered dots move independently and smoothly, each with its own trail colour.
- [ ] **Rig panels:** the live panel follows your driving; the replay panel shows the recorded driver,
      speed and gear.
- [ ] **Replay ends:** about 5 s after the recording finishes, Rig 2 changes to `No data` and its dot
      disappears; your live rig carries on.
- [ ] If a warning `Live packets are arriving from 192.0.2.2 ...` appears in the hub window, something on
      the network really uses that address: rerun with another `--as-ip` from `192.0.2.x`.

Send the pass 1 recording together with your notes from sections 3 and 4 (lap times, the invalid lap,
the flashback lap, smoothness and the matching `?map=` value).

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Nothing printed, no "New rig detected" | Firewall (section 1); network profile Public; UDP Telemetry off; wrong port or IP in the game; rig on another subnet or Wi-Fi blocking broadcast (use direct-IP mode, see RIG_SETUP.md); a VPN adapter on the rig. |
| `ERROR: UDP port 20777 is already in use` | Another program (SimHub, another telemetry app, a second hub) holds the port. Close it, or run with `--port 20778` and set 20778 in the game. |
| `ERROR: HTTP port 8000 is already in use` | Close the other program, or run with `--http-port 8001` and open that port on the TV. |
| `drops: unsupported_format=...` | The rig sends a format other than 2025/2026 (e.g. 2024). Fix UDP Format in the game. |
| `drops: size_mismatch=...` | Packet size differs from the spec for that format and ID (e.g. a game patch changed the format). Keep the recording and report it. |
| Rig stuck on `in_menu_paused` while driving | No Motion packets for the player's car. Check the summary's `Motion=` rate, and report with a recording. |
| Status line shows `track ?` / `lap -` | Session or Lap Data packets not received yet; wait a few seconds after entering the track. |
| TV shows "The dashboard hasn't been built yet" | Run `npm run build` in `dashboard\` (section 0), then reload. |
| TV can't open the page at all | Firewall rule for TCP 8000 (section 1b); use the hub's IP, not `localhost`, on the TV. |
| TV stuck on `Connecting to hub` | The page loads but `/ws` is blocked, e.g. by a proxy or browser extension. Try another browser on the TV. |

Run with `-v` for debug logging; the full log is in `data\logs\hub.log`.
