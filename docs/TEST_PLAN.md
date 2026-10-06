# Test plan: 2-PC real rig test

Goal: confirm both rigs' telemetry reaches the hub correctly, and capture a recording for golden tests.
Work through the sections in order and tick each box; don't move on until the current section passes.

Setup for this milestone: 2 rig PCs running F1 25 (each on its own Steam account) in Time Trial on the
**same track**, plus the hub PC (which may also be one of the rigs).

---

## 0. Before you start

- [ ] Both rigs configured per [RIG_SETUP.md](RIG_SETUP.md), with the **same UDP Format** on both.
- [ ] Hub PC has the project installed (see README: `python -m venv .venv`, `pip install -e ".[dev]"`).
- [ ] All PCs on the same LAN / subnet. Note each PC's IPv4 address (`ipconfig`):
  - Hub: `__________` Rig A: `__________` Rig B: `__________`

## 1. Windows Firewall on the hub PC

Inbound UDP on port 20777 must be allowed. Without this the hub receives nothing and shows no errors.

### 1a. Network profile must be Private

Windows blocks most inbound traffic on **Public** networks.

- [ ] Settings → Network & internet → (Ethernet / Wi-Fi) → **Network profile type = Private**.
- Or check in PowerShell:
  ```powershell
  Get-NetConnectionProfile          # NetworkCategory should be Private
  # To change it (Administrator PowerShell):
  Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
  ```

### 1b. Add an inbound rule for the port (recommended)

Run in an **Administrator** Command Prompt or PowerShell:

```bat
netsh advfirewall firewall add rule name="Sim Telemetry UDP 20777" dir=in action=allow protocol=UDP localport=20777 profile=private
netsh advfirewall firewall add rule name="Sim Telemetry HTTP 8000" dir=in action=allow protocol=TCP localport=8000 profile=private
```

The second rule is only needed if the dashboard will be opened from another device (e.g. the TV PC).
Check or remove the rules:

```bat
netsh advfirewall firewall show rule name="Sim Telemetry UDP 20777"
netsh advfirewall firewall delete rule name="Sim Telemetry UDP 20777"
```

If you change `udp_port` in the config, use that port here too.

### 1c. First-run prompt

The first time the hub starts, Windows may show **"Windows Defender Firewall has blocked some features of
Python"**. Tick **Private networks** only, and click **Allow access**.

> On this hub PC Python is the Microsoft Store build, and the venv's `python.exe` is only a launcher. Firewall
> rules tied to a program are unreliable in that case, so rely on the port rule from 1b. If you dismissed
> the prompt or chose "Public", the port rule still works.

## 2. First contact: `listen` mode

On the hub PC, from the project folder:

```powershell
.venv\Scripts\python -m simtelemetry listen
```

This prints one line per rig per second, plus a health summary every 10 s. Recording is **on** by default
(see section 4). Stop with **Ctrl+C**.

Example status line:

```
14:02:11 Rig 1    192.168.1.21    fmt=2025  Silverstone            lap 3   1:23.456 287 km/h driving
```

Start F1 25 on both rigs and go into Time Trial on the same track. Check, in this order:

- [ ] **Packets arrive from each rig's IP.** The log shows `New rig detected: <ip> -> Rig 1` and then `Rig 2`.
      The IPs match the rig PCs (a rig on the hub PC may show the hub's own IP).
- [ ] **Correct format detected.** Both lines show the same `fmt=` and it matches RIG_SETUP.md.
      No `WARNING: rigs are sending different packet formats` in the summary.
- [ ] **Zero size mismatches.** The 10 s summary shows `drops: none` for both rigs. Any `size_mismatch`,
      `unsupported_format` or `unknown_packet_id` here is a blocker: note it and keep the recording.
- [ ] **Rates look right.** In the summary, `Motion`, `LapData` and `CarTelemetry` are roughly the send rate
      (20 or 30 per second) while driving, and `Session` is about 2.
- [ ] **State follows the game.** In menus or paused the line shows `in_menu_paused`; on track,
      `driving`; with the game closed it shows `no_data` after 5 s.
- [ ] **Driver names.** The log shows `Rig N (<ip>) driver: <name>` for each rig.
- [ ] **Track name** is correct on both lines (e.g. `Silverstone`).
- [ ] **Lap number, lap time and speed match the in-game HUD** while driving (the line updates once per second).
- [ ] Health JSON also works with `run` mode: `.venv\Scripts\python -m simtelemetry run`, then open
      `http://localhost:8000/api/health`.

*Track map, timing panels, comparison and leaderboard checks will be added here as those steps are built.*

## 3. Capture for golden tests

Keep `listen` running (recording on) and on **each rig**:

- [ ] Drive at least **3 timed laps**. Write down from the HUD / Time Trial screen: lap time and S1/S2/S3
      for each lap, and which laps were **invalid**.
- [ ] Drive **one deliberately invalid lap** (cut a corner) and note its number.
- [ ] Use **one flashback** during a lap, and note the lap.
- [ ] Return to the menu for ~10 s, then back on track.
- [ ] Stop the hub with **Ctrl+C**. This flushes and closes the recording.

Recordings are in `data\recordings\` (`YYYYMMDD-HHMMSS-NNN.f1rec`; a new file starts every 256 MB, and the
newest 24 files are kept). Send the file(s) together with your notes. You can check a recording plays back:

```powershell
.venv\Scripts\python -m simtelemetry replay data\recordings\<file>.f1rec --speed 4 --no-api
```

## 4. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Nothing printed, no "New rig detected" | Firewall (section 1); network profile Public; UDP Telemetry off; wrong port; rig on another subnet or Wi-Fi blocking broadcast (use direct-IP mode, see RIG_SETUP.md); a VPN adapter on the rig. |
| `ERROR: UDP port 20777 is already in use` | Another program (SimHub, another telemetry app, a second hub) holds the port. Close it, or run with `--port 20778` and set 20778 on every rig. |
| `drops: unsupported_format=...` | The rig sends a format other than 2025/2026 (e.g. 2024). Fix UDP Format on that rig. |
| `drops: size_mismatch=...` | Packet size differs from the spec for that format and ID (e.g. a game patch changed the format). Keep the recording and report it. |
| Rig stuck on `in_menu_paused` while driving | No Motion packets for the player's car. Check the summary's `Motion=` rate, and report with a recording. |
| Status line shows `track ?` / `lap -` | Session or Lap Data packets not received yet; wait a few seconds after entering the track. |

Run `listen -v` for debug logging; the full log is in `data\logs\hub.log`.
