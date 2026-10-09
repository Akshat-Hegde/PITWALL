# Dashboard WebSocket schema: v1 (draft)

The hub pushes live state to dashboards over one WebSocket. The format is **game-agnostic**: nothing in it
is specific to F1, and each game adapter fills the same fields. The dashboard is built only against this
document (and its TypeScript twin, `dashboard/src/schema.ts`), never against hub internals.

Status: **v1 draft.** Fields marked **(provisional)** depend on lap-tracking behaviour that will be
confirmed against the first real capture; they may still change within v1 before milestone 1 is
frozen. Everything else is intended to be stable.

Hub implementation: `hub/simtelemetry/core/feed.py` sends every message type below, with lap data from
the lap book (`core/laps.py`; F1 rules and their assumptions in [LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md)).
`hub/tests/test_feed.py` writes a sample of real hub output to `dashboard/src/testing/hub-feed.sample.json`,
which the dashboard tests validate against this schema.

**Shown track.** The hub picks one track for the TV: the one most rigs are on, with driving rigs counting
double. `comparison`, the snapshot's `leaderboards` and `leaderboard` messages are for that track. When
that track's boards may have changed (a lap was recorded or retracted), the shown track changes, or a new
day or week starts, the hub sends one `leaderboard` message per period.

## 1. Transport

| | |
|---|---|
| Endpoint | `ws://<hub-host>:<http_port>/ws` (default port 8000) |
| Direction | Server → client. Clients send nothing in v1 (anything received is ignored). |
| Encoding | One JSON object per text frame, UTF-8. |
| Frame rate | `frame` messages at a fixed rate, 15 Hz by default (configurable 10–20 Hz). |
| On connect | The hub sends a `snapshot` first, then live messages. |
| Reconnect | Clients reconnect with backoff (e.g. 0.5 s doubling to 5 s). Every (re)connect starts with a fresh `snapshot` that **replaces** all client state. |

## 2. Envelope and versioning

Every message has:

```json
{ "v": 1, "type": "frame", "seq": 1042, "ts": 1791302400123, "...": "type-specific fields" }
```

| Field | Type | Meaning |
|---|---|---|
| `v` | int | Schema major version. Currently `1`. |
| `type` | string | Message type (section 3). |
| `seq` | int | Increases by 1 per message on this connection, starting at 0 (the snapshot). A gap means messages were lost: reconnect. |
| `ts` | int | Hub wall-clock time when the message was built, Unix **milliseconds**. |

Compatibility rules:

- **Additive changes stay in v1:** new optional fields, new enum values, new message types. Clients
  **must ignore** unknown fields and unknown `type`s, and treat unknown enum values as "other/unknown".
- **Breaking changes bump `v`:** removing or renaming a field, changing a type or unit. A client that receives
  a `v` it doesn't support shows "Dashboard and hub versions don't match" and doesn't render data.

## 3. Message types

| `type` | When | Payload |
|---|---|---|
| `snapshot` | First message on every connection | Full state (3.1) |
| `frame` | Every tick (15 Hz) | All rigs' live data + comparison (3.2) |
| `rig_info` | A rig appears, or its name/colour/format changes | `{ "rig": RigInfo }` |
| `status` | Once per second, and immediately on change | `{ "status": HubStatus }` |
| `session_changed` | A rig starts a new game session (e.g. new track, restart) | `{ "rig_id", "session": SessionInfo }` |
| `track_outline` | An outline becomes available (generated or loaded) | `{ "outline": TrackOutline }` |
| `lap_completed` **(provisional)** | A rig finishes a lap | `{ "lap": LapRecord }` |
| `leaderboard` **(provisional)** | A board of the shown track changes | `{ "leaderboard": Leaderboard }`: full replacement of the board for its `period`. Boards for another track replace all boards. |

### 3.1 `snapshot`

```json
{
  "v": 1, "type": "snapshot", "seq": 0, "ts": 1791302400000,
  "hub": { "version": "0.1.0", "games": ["F1"], "frame_hz": 15 },
  "cafe": { "name": "Sim Racing Cafe", "branding": { "--brand-accent": "#e10600" } },
  "status": { "...": "HubStatus" },
  "rigs": [ { "...": "RigInfo" } ],
  "frame": { "rigs": [ { "...": "RigFrame" } ], "comparison": { "...": "Comparison or null" } },
  "outlines": [ { "...": "TrackOutline" } ],
  "leaderboards": [ { "...": "Leaderboard, one per period: today, week, all_time" } ],
  "recent_laps": [ { "...": "LapRecord, newest first, at most 20" } ]
}
```

- `cafe.branding`: CSS custom properties from `[cafe.branding]` in the hub config. The dashboard applies
  them to `:root` as-is (keys must start with `--`; others are ignored).
- `outlines`: every outline the hub has (one per track that has had a complete valid lap).

### 3.2 `frame`

```json
{ "v": 1, "type": "frame", "seq": 1042, "ts": 1791302460123,
  "rigs": [ { "...": "RigFrame" } ],
  "comparison": { "...": "Comparison or null" } }
```

`rigs` contains **every known rig**, including those with `state: "no_data"`, so the client never has to
infer removals. Rigs are ordered by `rig_id`.

## 4. Objects

Conventions: times are integer **milliseconds**; distances **metres**; speed **km/h**; pedal inputs
**0.0–1.0**; colours `#rrggbb`. Unknown or not-yet-available values are `null`, **never** a sentinel such as
`0` or `-1`.

### RigInfo

| Field | Type | Notes |
|---|---|---|
| `rig_id` | string | Stable, opaque ID. Clients must not parse it (today it's derived from the source IP). |
| `name` | string | Config name, else auto name ("Rig 1"). |
| `colour` | string | Config colour, else assigned by the hub from a fixed palette in order of discovery. |
| `address` | string | Source IP, shown on the status bar. |
| `game` | string | Adapter name, e.g. `"F1"`. |
| `data_format` | string \| null | Wire format the rig sends, e.g. `"2025"`. |
| `format_supported` | bool | `false` if the adapter can't decode that format (packets are dropped). |

### HubStatus

| Field | Type | Notes |
|---|---|---|
| `format_mismatch` | bool | Active rigs send different `data_format`s. |
| `formats` | object | `rig_id → data_format` for active rigs. |
| `recorder` | object \| null | `null` = recording disabled. Else `{ "state": "recording" \| "low_disk_warning" \| "stopped", "message": string \| null, "free_gb": number \| null }`. |
| `warnings` | array | `[{ "code": string, "message": string, "rig_id": string \| null }]`, human-readable, for the status bar. Codes in v1: `format_mismatch`, `format_unsupported`, `size_mismatch`, `recorder_low_disk`, `recorder_stopped`. |

### SessionInfo

| Field | Type | Notes |
|---|---|---|
| `session_id` | string \| null | Opaque; changes when the game starts a new session. |
| `track_key` | string \| null | `"<game>:<track id>"`, e.g. `"F1:7"`. Key for outlines and leaderboards. |
| `track_name` | string \| null | Display name (config overrides applied). |
| `track_length_m` | number \| null | |
| `session_type` | string \| null | Display name, e.g. `"Time Trial"`. |

### RigFrame

| Field | Type | Notes |
|---|---|---|
| `rig_id` | string | |
| `state` | string | `"driving"`, `"in_menu_paused"` (packets arriving, car not on track), `"no_data"`. |
| `last_seen_ms` | int \| null | Milliseconds since the last packet from this rig. |
| `driver` | string \| null | Player name from the game. |
| `session` | SessionInfo | |
| `position` | `{ "x": number, "z": number }` \| null | World position in the track's coordinate space (metres). `null` when not driving. |
| `speed_kph` | number \| null | |
| `gear` | int \| null | `-1` reverse, `0` neutral, `1..n`. |
| `throttle` | number \| null | 0–1 |
| `brake` | number \| null | 0–1 |
| `rpm` | int \| null | |
| `tyre` | Tyre \| null | |
| `lap` | LiveLap \| null | **(provisional)** |
| `best` | BestLap \| null | **(provisional)** This rig's best valid lap on the current track in this hub session. |

### Tyre

| Field | Type | Notes |
|---|---|---|
| `compound` | string | Generic class: `"soft"`, `"medium"`, `"hard"`, `"inter"`, `"wet"`, `"other"`, `"unknown"`. Drives the tyre colour. |
| `label` | string | What to print, e.g. `"C3"`, `"soft"`, `"unknown(42)"`. |
| `age_laps` | int \| null | |

### LiveLap (provisional)

| Field | Type | Notes |
|---|---|---|
| `number` | int | Current lap number as the game counts it. |
| `distance_m` | number | Distance into the lap; **may be negative** before the line is first crossed. |
| `current_ms` | int | Time into the current lap. |
| `last_ms` | int \| null | Previous lap's time. |
| `valid` | bool | Current lap still valid. |
| `sector` | int | Current sector index, `0`–`2`. |
| `sectors` | `[SectorTime \| null, SectorTime \| null, SectorTime \| null]` | Sectors completed on the **current** lap. |
| `last_sectors` | same \| null | Sectors of the previous lap. |

### SectorTime (provisional)

| Field | Type | Notes |
|---|---|---|
| `ms` | int | |
| `rating` | string \| null | `"session_best"` (purple: fastest of any rig on this track), `"personal_best"` (green: this driver's fastest), `"normal"` (yellow: slower), `null` (not rated, e.g. invalid). |

### BestLap (provisional)

`{ "lap_ms": int, "sectors_ms": [int, int, int], "lap_number": int, "set_at": int }`; `set_at` is Unix ms.

### Comparison (provisional)

Live and best-lap deltas between rigs on the **same track**. For two rigs this is "my best vs yours" and "my
live lap vs your best lap at the same distance"; with more rigs, each rig is compared with the fastest
**other** rig.

```json
{ "track_key": "F1:7",
  "rigs": [
    { "rig_id": "r1", "reference_rig_id": "r2", "best_gap_ms": -412, "live_delta_ms": 180 },
    { "rig_id": "r2", "reference_rig_id": "r1", "best_gap_ms": 412,  "live_delta_ms": null } ] }
```

| Field | Type | Notes |
|---|---|---|
| `track_key` | string | |
| `rigs[].rig_id` | string | |
| `rigs[].reference_rig_id` | string \| null | Rig whose best lap is the reference. `null` if no other rig has a valid lap. |
| `rigs[].best_gap_ms` | int \| null | My best lap minus the reference best lap; negative = I'm faster. |
| `rigs[].live_delta_ms` | int \| null | My current lap time at my current `distance_m` minus the reference best lap's time at the same distance; negative = ahead. `null` when not driving, on an invalid lap, or before the line. |

`comparison` is `null` when fewer than two rigs are on the same track.

### TrackOutline

| Field | Type | Notes |
|---|---|---|
| `track_key` | string | |
| `track_name` | string \| null | |
| `points` | `[[x, z], ...]` | Closed loop in the same coordinate space as `RigFrame.position`; `points[0]` is the start/finish line, in driving direction. |
| `source` | string | `"first_valid_lap"` (recorded by the hub) or `"bundled"`. |
| `sector_starts` | `[int, int, int]` \| null | Indices into `points` where sectors 1–3 start. |
| `display` | `{ "flip_x": bool, "flip_z": bool, "rotate_deg": number }` | How to draw the world: screen right = +x, screen down = +z, **after** applying these. From the hub's `[map]` config, so the map matches the in-game minimap. **(provisional for F1** until checked in the real test; the dashboard's `?map=` URL option overrides it for that check.) |

### LapRecord (provisional)

| Field | Type | Notes |
|---|---|---|
| `rig_id` | string | |
| `driver` | string \| null | |
| `track_key` | string | |
| `session_id` | string \| null | |
| `lap_number` | int | |
| `lap_ms` | int | |
| `sectors_ms` | `[int, int, int]` \| null | |
| `valid` | bool | The game's own validity verdict. |
| `out_lap` | bool | The lap started from the pit/garage. Out laps never set bests or appear on the leaderboard, whatever `valid` says. |
| `tyre` | Tyre \| null | |
| `personal_best` | bool | New best for this driver on this track. |
| `session_best` | bool | New best of all rigs on this track. |
| `completed_at` | int | Unix ms. |

### Leaderboard (provisional)

Best counted lap (valid, not an out lap) per driver (per rig if the driver name is unknown) on one track
within a period. Laps are stored in the hub's database (`<data_dir>/laps.db`), so boards survive hub
restarts.

| Field | Type | Notes |
|---|---|---|
| `track_key`, `track_name` | string, string \| null | |
| `period` | string | `"today"`, `"week"` (from Monday) or `"all_time"`. Clients ignore boards with other values. |
| `since` | int \| null | Unix ms where the period starts, in the hub PC's local time; `[leaderboard] day_start_hour` sets when a day starts. `null` for all time. |
| `entries` | array | Fastest first, at most 100. |

```json
{ "track_key": "F1:7", "track_name": "Silverstone", "period": "today", "since": 1791237600000,
  "entries": [
    { "rank": 1, "rig_id": "r1", "rig_name": "Rig 1", "driver": "Akshat", "lap_ms": 88123,
      "sectors_ms": [28011, 33456, 26656], "gap_ms": 0, "tyre": { "compound": "soft", "label": "C3", "age_laps": 2 },
      "lap_number": 4, "set_at": 1791302455000 } ] }
```

## 5. Example: `frame`

```json
{ "v": 1, "type": "frame", "seq": 1042, "ts": 1791302460123,
  "rigs": [
    { "rig_id": "r1", "state": "driving", "last_seen_ms": 12, "driver": "Akshat",
      "session": { "session_id": "a1b2c3d4e5f60708", "track_key": "F1:7", "track_name": "Silverstone",
                   "track_length_m": 5891, "session_type": "Time Trial" },
      "position": { "x": -412.6, "z": 188.2 }, "speed_kph": 287, "gear": 7, "throttle": 1.0, "brake": 0.0,
      "rpm": 11240, "tyre": { "compound": "soft", "label": "C3", "age_laps": 2 },
      "lap": { "number": 5, "distance_m": 2310.4, "current_ms": 37120, "last_ms": 88412, "valid": true,
               "sector": 1, "sectors": [ { "ms": 28102, "rating": "personal_best" }, null, null ],
               "last_sectors": [ { "ms": 28305, "rating": "normal" }, { "ms": 33490, "rating": "normal" },
                                 { "ms": 26617, "rating": "session_best" } ] },
      "best": { "lap_ms": 88123, "sectors_ms": [28011, 33456, 26656], "lap_number": 4, "set_at": 1791302455000 } },
    { "rig_id": "r2", "state": "no_data", "last_seen_ms": null, "driver": null,
      "session": { "session_id": null, "track_key": null, "track_name": null, "track_length_m": null,
                   "session_type": null },
      "position": null, "speed_kph": null, "gear": null, "throttle": null, "brake": null, "rpm": null,
      "tyre": null, "lap": null, "best": null } ],
  "comparison": null }
```

## 6. Dashboard behaviour notes (non-normative)

- Interpolate `position` between frames for smooth dots; draw a fading trail from recent positions; clear
  the trail on `session_changed`.
- Until an outline exists for a track, draw only trails (the map auto-fits to the points seen so far).
- Sector colours: `session_best` purple, `personal_best` green, `normal` yellow.
- `no_data` rigs stay listed (greyed) so staff can see a rig is down.
