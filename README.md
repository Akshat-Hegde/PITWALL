# Sim Telemetry Hub

Local LAN telemetry hub and TV dashboard for sim racing cafes. Milestone 1: F1 25 (UDP formats 2025 and 2026).

Status: milestone 1 is feature-complete and awaiting its end-to-end test on real devices
([docs/TEST_PLAN.md](docs/TEST_PLAN.md)). The hub receives F1 25 telemetry from every rig on the LAN, tracks
laps, sectors and bests, stores laps in SQLite, and serves the TV dashboard (race view, leaderboard view,
attract mode) with a live WebSocket feed. Lap tracking was built from the UDP spec; what it assumes about the
real game is listed in [docs/LAP_ASSUMPTIONS.md](docs/LAP_ASSUMPTIONS.md), to be confirmed in that test.

## Setup (Windows, Python 3.11+)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy config\hub.example.toml config\hub.toml   # optional: edit cafe name, rig names, port
```

## Commands

```powershell
.venv\Scripts\python -m simtelemetry listen                  # debug: one status line per rig per second (records by default)
.venv\Scripts\python -m simtelemetry run                     # hub + dashboard at http://localhost:8000/ (no recording by default)
.venv\Scripts\python -m simtelemetry record                  # capture raw packets only
.venv\Scripts\python -m simtelemetry replay FILE [--speed N] # replay a capture through the pipeline (0 = max speed)
.venv\Scripts\python -m pytest                               # tests
```

Add `--lap-debug` to any of `run`, `listen` or `replay` to log every lap event (started, completed,
invalidated, reset, flashback, session history update) with the game's session time, also to
`data\logs\lap-debug-<date>-<time>.log`. See [docs/LAP_ASSUMPTIONS.md](docs/LAP_ASSUMPTIONS.md).

Replay options:

- `--from-ip IP`: only replay packets the recording received from that source IP.
- `--as-ip IP`: replay them as if sent from another IP (i.e. as a different rig). If the recording holds
  several source IPs, pick one with `--from-ip`.
- `--live`: also listen for live UDP rigs, so the recording plays **alongside** them in the same hub,
  e.g. drive one real rig while a capture plays as Rig 2. Keeps running after the replay ends:

  ```powershell
  .venv\Scripts\python -m simtelemetry replay data\recordings\<file>.f1rec --from-ip 192.168.1.21 --as-ip 192.168.50.2 --live
  ```

  Use this instead of a separate `listen`/`run` (one hub process owns the UDP port). Choose an `--as-ip`
  that no live rig uses; the hub warns if a live rig sends from it.

Common options: `--config PATH`, `--port N` (UDP), `--http-port N`, `--data-dir PATH`,
`--record` / `--no-record`, `--duration SECONDS`, `-v`.

### Raw packet recording

The recorder captures every datagram for debugging and replay. It is **off by default in `run`** (production):
at ~0.75 GB/hour per rig, 10 rigs would write ~7.5 GB/hour. It is **on by default in `listen`** (dev/debug).
Change the defaults in `config/hub.toml`:

```toml
[recorder]
enabled_in_run = false     # production
enabled_in_listen = true   # dev / first tests
```

`--record` / `--no-record` override the config for a single run. Files rotate at `max_file_mb` and only the
newest `keep_files` are kept.

**Where recordings go and disk safety.** Recordings are written to `[recorder] directory`, or to
`<data_dir>/recordings` if that isn't set. Either can point to another drive (`data_dir = "D:/simtelemetry"`
moves everything, including logs and the database; `directory` moves only recordings). The recorder checks free
space on that drive at start and every `disk_check_interval_s` (30 s):

- below `warn_free_gb` (default 5 GB): a warning in the log and in the 10 s console summary;
- below `stop_free_gb` (default 1 GB): recording stops cleanly (current file flushed and closed) while the hub
  keeps running; `/api/health` → `recorder.message` and the console summary show
  `recording stopped: low disk`. Restart the hub after freeing space to record again.

A write error (e.g. the drive filling up between checks) stops recording the same way.

## Dashboard (TV screen)

React + Vite + TypeScript in `dashboard/`, built for a full-screen 1080p or 4K TV. Needs Node.js 20+.

```powershell
cd dashboard
npm install
npm run dev        # http://localhost:5173: uses the built-in mock data, no hub needed
npm test           # schema conformance of the mock, state, formatting, map geometry
npm run build      # production files in dashboard/dist (fonts bundled: works offline on the LAN)
```

The dashboard reads only the WebSocket messages described in [docs/WS_SCHEMA.md](docs/WS_SCHEMA.md).
Data source: `?source=mock` (default in `npm run dev`) or `?source=ws` (default when served by the hub; in dev
it is proxied to a hub on `localhost:8000`). `run` serves `dashboard/dist` at `http://<hub>:8000/` (configurable
with `[dashboard] directory`), and the feed rate with `[dashboard] frame_hz` (10–20, default 15). Until lap
tracking exists, the hub sends `null` lap fields and no track outline; the map then draws the path driven so far.

`?map=flipx,flipz,rotN` (any combination) overrides the map orientation, for matching the in-game minimap
during testing; the active setting is shown on the map.

Mock options, combined in the URL, e.g. `http://localhost:5173/?outline=late&mismatch=1`:

| Option | Effect |
|---|---|
| `speed=N` | Run the simulation N times faster (e.g. `speed=8` to reach a leaderboard quickly). |
| `outline=late` | No track outline until the first valid lap: trail-only map. |
| `mismatch=1` | Rig 2 reports UDP format 2026: format warning. |
| `recorder=recording\|low\|stopped` | Recorder status / low-disk warnings in the status bar. |
| `offline=0` | Hide the configured-but-offline Rig 3. |
| `board=N` | Add N earlier drivers to the leaderboard (e.g. `board=8` for a full board of 10, `board=12` to see paging). |
| `rigs=N` | Number of driving rigs, 1–10 (default 2). |
| `idle=1` | Every rig stays in the menu: shows attract mode. |

**TV views.** Two views, sized for 1080p and 4K:

- **Race view:** large track map and a timing strip, one row per rig (up to 10): driver, lap clock, sector
  colours, last and best lap, and the live gap to the fastest other rig's best lap (Δ). With three rigs or
  fewer, rows are larger and also show speed and gear. Today's top 3 fills the space below when there is room.
- **Leaderboard view:** today, this week and all time side by side, ten rows each, paging every 8 s when a
  board has more than ten drivers.

`?view=race` or `?view=board` fixes the view; the default `?view=auto` shows the race view while anyone is
driving and switches to attract mode after 10 s with nobody driving (leaderboard view 20 s, race view 10 s,
repeating). On the TV PC's keyboard: `1` race view, `2` leaderboard view, `0` auto.

Branding comes from `[cafe]` in the hub config: `name`, plus CSS variables in `[cafe.branding]` (e.g.
`"--brand-accent" = "#0a7cff"`), applied to the page as-is.

## Driver names (staff page)

Open `http://<hub>:8000/staff` on a phone or tablet to set who is driving each rig: the driver's name and,
optionally, a phone number and email (stored with the driver session for later reports; not used yet).
**End session** clears the name when the customer leaves. Laps are saved under the name that applies when
they complete: the staff-set name, else the game's player name, else the rig name; changing the name later
doesn't rename earlier laps. The TV shows the name and that driver's best lap on the track ("PB").

Set `[staff] pin` in `config\hub.toml` so customers can't change names: the page then asks for the PIN, and
five wrong PINs in a minute lock that device out for a minute. Without a PIN anyone on the LAN can use the
page.

## Lap database

Every recorded lap goes into SQLite at `<data_dir>/laps.db` (default `data\laps.db`), together with each
track's outline. The TV's leaderboards (today, this week, all time) are read from it, so they survive hub
restarts. "Today" starts at `[leaderboard] day_start_hour` (local time, default 0); the week starts on
Monday. To start the boards from scratch, stop the hub and delete or rename `laps.db`.

`replay` keeps its laps in memory, so replaying a capture never changes the real boards; add `--save-laps`
to store them.

## Python on the dev machine

The current dev machine uses the **Microsoft Store** build of Python 3.11. That's fine for development, but
before packaging (Windows installer, background service, tray icon: a later milestone) we will switch to a
**python.org 3.11 install**. Store Python is unreliable with PyInstaller and with Windows Firewall
*program* rules (the real executable is hidden under `WindowsApps` and the venv's `python.exe` is only a
launcher). Until then, use the port-based firewall rule in [docs/TEST_PLAN.md](docs/TEST_PLAN.md).

## Docs

- [docs/RIG_SETUP.md](docs/RIG_SETUP.md): in-game UDP settings for each rig.
- [docs/TEST_PLAN.md](docs/TEST_PLAN.md): firewall setup and the 2-device end-to-end test checklist.
- [docs/WS_SCHEMA.md](docs/WS_SCHEMA.md): hub → dashboard WebSocket message format (v1, frozen).
- [docs/LAP_ASSUMPTIONS.md](docs/LAP_ASSUMPTIONS.md): what lap tracking assumes about the game, and how to
  check each assumption with `--lap-debug`.

- Specs (source of truth for the parser): `docs/F1_25_structures.txt`, `docs/F1_2026_SeasonPack_structures.txt`,
  `docs/F1_25_UDP_Spec.pdf`.

## Layout

```
hub/simtelemetry/
  adapters/f1/   spec layouts (f2025, f2026), validation, decoding, appendix tables, lap tracker, adapter
  core/          game-agnostic: adapter interface, rig registry, health, lap book, lap store, dashboard feed
  net/           asyncio UDP listener
  api/           FastAPI app: /api/health, /ws, dashboard files
  tools/         raw packet recorder and replay
  hub.py         packet pipeline
hub/tests/       pytest suite (spec conformance, decoding, lap scenarios, feed, store, pipeline, CLI)
config/          hub.example.toml
dashboard/src/
  schema.ts      TypeScript twin of docs/WS_SCHEMA.md
  data/          data sources: mock, WebSocket (reconnect, resync on seq gap)
  mock/          simulated track and rigs that emit schema messages
  state/         reducer, store, position trails
  map/           map geometry (display transform, fit)
  components/    status bar, track map, timing strip, leaderboards, race and leaderboard views
  views.ts       view selection: race / leaderboard / auto (attract mode)
```
