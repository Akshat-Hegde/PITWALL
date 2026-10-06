# Sim Telemetry Hub

Local LAN telemetry hub and TV dashboard for sim racing cafes. Milestone 1: F1 25 (UDP formats 2025 and 2026), two rigs.

Status: step 3 of 6. Packet parsing, UDP listener, rig registry, health, recorder/replay and the health API
are done; normalisation, WebSocket and the dashboard are next.

## Setup (Windows, Python 3.11+)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy config\hub.example.toml config\hub.toml   # optional: edit cafe name, rig names, port
```

## Commands

```powershell
.venv\Scripts\python -m simtelemetry listen                  # debug: one status line per rig per second (records by default)
.venv\Scripts\python -m simtelemetry run                     # hub + API at http://localhost:8000/api/health (no recording by default)
.venv\Scripts\python -m simtelemetry record                  # capture raw packets only
.venv\Scripts\python -m simtelemetry replay FILE [--speed N] # replay a capture through the pipeline (0 = max speed)
.venv\Scripts\python -m pytest                               # tests
```

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

## Python on the dev machine

The current dev machine uses the **Microsoft Store** build of Python 3.11. That's fine for development, but
before packaging (Windows installer, background service, tray icon: a later milestone) we will switch to a
**python.org 3.11 install**. Store Python is unreliable with PyInstaller and with Windows Firewall
*program* rules (the real executable is hidden under `WindowsApps` and the venv's `python.exe` is only a
launcher). Until then, use the port-based firewall rule in [docs/TEST_PLAN.md](docs/TEST_PLAN.md).

## Docs

- [docs/RIG_SETUP.md](docs/RIG_SETUP.md): in-game UDP settings for each rig.
- [docs/TEST_PLAN.md](docs/TEST_PLAN.md): firewall setup and the 2-PC test checklist.
- Specs (source of truth for the parser): `docs/F1_25_structures.txt`, `docs/F1_2026_SeasonPack_structures.txt`,
  `docs/F1_25_UDP_Spec.pdf`.

## Layout

```
hub/simtelemetry/
  adapters/f1/   spec layouts (f2025, f2026), validation, decoding, appendix tables, adapter
  core/          game-agnostic adapter interface, rig registry, health
  net/           asyncio UDP listener
  api/           FastAPI app
  tools/         raw packet recorder and replay
  hub.py         packet pipeline
hub/tests/       pytest suite (spec conformance, decoding, pipeline, CLI)
config/          hub.example.toml
```
