# Dashboard WebSocket schema: v1

The hub pushes live state to dashboards over one WebSocket. The format is **game-agnostic**: nothing in it
is specific to F1, and each game adapter fills the same fields. The dashboard is built only against this
document (and its TypeScript twin, `dashboard/src/schema.ts`), never against hub internals.

Status: **v1, frozen.** From here on v1 only changes additively (section 2): new optional fields, new
enum values and new message types. Anything else is v2. How the F1 game actually behaves around laps is
documented separately in [LAP_ASSUMPTIONS.md](LAP_ASSUMPTIONS.md); if the real test shows an assumption
is wrong, the hub's rules change, not this format.

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
| `lap_completed` | A rig finishes a lap | `{ "lap": LapRecord }` |
| `head_to_head` *(added in v1, optional)* | The closest pair on the shown track changes | `{ "head_to_head": HeadToHead \| null }` |
| `competition` *(added in v1, optional)* | The challenge or the corporate event changes (also when their boards change) | `{ "competition": Competition }` |
| `tv` *(added in v1, optional)* | Staff change the TV page, the pinned rig or the view over the page | `{ "tv": TvSetting }` |
| `cafe` *(added in v1, optional)* | The cafe name, tagline, colour or logo changes (owner saved `/setup`) | `{ "cafe": { "name", "branding", "tagline", "logo" } }`: full replacement |
| `queue` *(added in v1, optional)* | The waiting queue changes | `{ "queue": [QueueEntry] }`: full replacement |
| `moment` *(added in v1, optional)* | A broadcast moment: a driver starts, a record falls, the podium | `{ "moment": Moment }` |
| `leaderboard` | A board of the shown track changes | `{ "leaderboard": Leaderboard }`: full replacement of the board for its `period`. Boards for another track replace all boards. |

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

- `hub.udp_port`, `hub.lan_address` *(added in v1, optional)*: where games should send telemetry (this PC's
  network address, `null` if unknown); shown on the dashboard's waiting screen.
- `hub.features` *(added in v1, optional)*: `[features]` from the hub config, e.g.
  `{ "moments": true, "battles": true, "podium": true, "attract": true, "portrait": true, "head_to_head": true,
  "onboard": true }`. A feature that is `false` is not shown. Missing keys mean on.
- `hub.moments` *(added in v1, optional)*: `{ "battle_margin_ms": 300 }`, the gap under which two best laps
  make a battle pop-up.
- `hub.sounds` *(added in v1, optional)*: `{ "enabled": false, "volume": 0.6 }`.
- `hub.steering_rotation_deg` *(added in v1, optional, default 360)*: lock-to-lock wheel rotation for the
  steering wheel graphic, from `[dashboard] steering_wheel_rotation_deg`.
- `cafe.branding`: CSS custom properties from `[cafe.branding]` in the hub config. The dashboard applies
  them to `:root` as-is (keys must start with `--`; others are ignored).
- `cafe.tagline` *(added in v1, optional, default `""`)*: the line shown on the attract and portrait screens; empty means the built-in line.
- `cafe.logo` *(added in v1, optional)*: `"/api/cafe/logo?v=<file name>"` or `null`. The TV shows it in the header badge in place of the cafe's first letter.
- `outlines`: every outline the hub has (bundled track files, and tracks where a full lap was driven).
- `session_story` *(added in v1, optional)*: laps on the shown track in the last hour, oldest first: `{ "rig_id", "driver", "track_key", "lap_ms", "valid", "out_lap", "lap_class", "completed_at" }` (the LIVE page's session story; later laps arrive as `lap_completed`).
- `tv` *(added in v1, optional)*: TvSetting, what staff chose for the TV: `page` (`"live"` or `"multi"`),
  `pinned_rig` (rig id for the LIVE trace strip, or null for automatic), `overlay` (`"head_to_head"`,
  `"teams"` or null: a view shown over the page) and `updated_at` (Unix ms). The page and pinned rig are
  kept across hub restarts; the overlay is not.
- `head_to_head` *(added in v1, optional)*: the two drivers on the shown track whose best traced laps today
  are closest, or null. `{ "track_key", "track_name", "day", "a", "b" }`, `a` the faster; each side: `rig_id`,
  `driver`, `lap_ms`, `lap_number`, `lap_class`, `minis` (24 mini-sector times, ms), `speed` (200 values,
  km/h per 0.5 % of the lap, null where unknown), `share` (`full_throttle`, `heavy_braking`, `cornering`,
  % of the lap). The hub keeps each driver's best traced lap per track and day in its database, so the view
  survives TV reloads and hub restarts.
- `competition` *(added in v1, optional)*: `{ "challenge": Challenge | null, "event": Event | null }`.
  Challenge: `id`, `title`, `track_key`, `track_name`, `lap_class`, `starts_at`, `ends_at` (Unix ms, end
  exclusive), `prize`, `state` (`"upcoming"`, `"running"`, `"ended"`), `entries` (`rank`, `driver`, `lap_ms`,
  `gap_ms`, at most 5). Event: `id`, `name`, `company`, `accent` (`#rrggbb` \| null), `logo` (URL \| null),
  `track_key`, `track_name`, `best_n`, `starts_at`, `teams` (`id`, `rank`, `name`, `logo`, `members`
  (`id`, `name`, `best_ms`), `counted`, `average_ms`), complete teams first.
- `queue` *(added in v1, optional)*: who's waiting for a rig, first first: `[{ "id": 3, "name": "Jordan P" }]`.
  Names only; contact details never leave the hub.

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
| `warnings` | array | `[{ "code": string, "message": string, "rig_id": string \| null }]`, human-readable, for the status bar. Codes in v1: `format_mismatch`, `format_unsupported`, `size_mismatch`, `recorder_low_disk`, `recorder_stopped`, `port_shadowed` (added: another program on the hub PC listens on the telemetry port at a specific address, e.g. wheel software on 127.0.0.1, and takes the packets sent there). |

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
| `driver` | string \| null | The driver's name: set by staff on the hub's `/staff` page, else the player name from the game; `null` if neither is known. |
| `session` | SessionInfo | |
| `position` | `{ "x": number, "z": number }` \| null | World position in the track's coordinate space (metres). `null` when not driving. |
| `speed_kph` | number \| null | |
| `gear` | int \| null | `-1` reverse, `0` neutral, `1..n`. |
| `throttle` | number \| null | 0–1 |
| `brake` | number \| null | 0–1 |
| `rpm` | int \| null | |
| `max_rpm` | int \| null | *(Added in v1, optional.)* The car's rev limit, for a rev bar. Known while the rig sends data, also when not driving. |
| `tyre` | Tyre \| null | |
| `lap` | LiveLap \| null | The lap in progress; `null` when not driving. |
| `best` | BestLap \| null | This rig's best valid lap on the current track in this hub session. |
| `personal_best` | BestLap \| null | *(Added in v1, optional.)* The current driver's fastest valid lap on this track ever, from the lap database. Laps are stored under the staff-assigned name, else the game's player name, else the rig name. |
| `booking` | object \| null | *(Added in v1, optional.)* The staff session on the rig: `{ "driver", "started_at", "ends_at" }` (Unix ms; `ends_at` null = no timer). The TV shows the time left. |
| `car` | CarDetail \| null | *(Added in v1, optional.)* Car systems, tyres, brakes, damage, g-forces and slides; see below. |

### CarDetail *(added in v1, optional)*

Per-wheel values (`PerWheel`) are four numbers in the order **front-left, front-right, rear-left, rear-right**.
Fields marked *live* are `null` when the car is not driving. Any field may be `null` when the game has not sent it.

| Field | Type | Notes |
|---|---|---|
| `drs_open`, `drs_allowed` | bool \| null | *Live.* |
| `rev_lights_pct` | number \| null | *Live.* 0–100. |
| `ers_pct` | number \| null | ERS store, 0–100. |
| `ers_mode` | string \| null | `"none"`, `"medium"`, `"hotlap"`, `"overtake"`. |
| `fuel_kg`, `fuel_laps` | number \| null | Fuel in the tank, and laps of fuel left over the race distance (the game's figure). |
| `pit_limiter` | bool \| null | *Live.* |
| `steer` | number \| null | *Live.* −1 (full left) to 1 (full right). The wheel graphic turns `steer × hub.steering_rotation_deg / 2` degrees. |
| `g_lat`, `g_long` | number \| null | *Live.* Lateral and longitudinal g. |
| `tyre_surface_c`, `tyre_inner_c` | PerWheel \| null | Tyre temperatures, °C. |
| `tyre_pressure_psi` | PerWheel \| null | |
| `tyre_wear_pct` | PerWheel \| null | 0–100. |
| `brake_c` | PerWheel \| null | Brake temperatures, °C. |
| `damage` | object \| null | Percent per part: `front_wing_left`, `front_wing_right`, `rear_wing`, `floor`, `diffuser`, `sidepod`, `gearbox`, `engine`. |
| `top_speed_lap_kph`, `top_speed_kph` | number \| null | Top speed this lap and this session. |
| `slide_deg` | number \| null | *Live.* Degrees the car points away from its direction of travel (positive = nose right). |
| `saves` | int | Big slides caught this session (peak 15–70°, caught within 3 s, still above 40 km/h). |
| `last_save_at` | int \| null | Hub clock (Unix ms) of the latest save; the TV flashes "SAVE!" for a couple of seconds after it. |
| `last_save_peak_deg` | number \| null | Peak angle of the latest save. |

### Tyre

| Field | Type | Notes |
|---|---|---|
| `compound` | string | Generic class: `"soft"`, `"medium"`, `"hard"`, `"inter"`, `"wet"`, `"other"`, `"unknown"`. Drives the tyre colour. |
| `label` | string | What to print, e.g. `"C3"`, `"soft"`, `"unknown(42)"`. |
| `age_laps` | int \| null | |

### LiveLap

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

### SectorTime

| Field | Type | Notes |
|---|---|---|
| `ms` | int | |
| `rating` | string \| null | `"session_best"` (purple: equal to or faster than the fastest time for this sector on this track **today**, all rigs, from the lap database with the "today" board's day boundary), `"personal_best"` (green: equal to or faster than this driver's own best in their current session: same rig, game session and driver), `"normal"` (yellow: slower), `null` (not rated: invalid lap or out lap). |

### BestLap

`{ "lap_ms": int, "sectors_ms": [int, int, int], "lap_number": int, "set_at": int }`; `set_at` is Unix ms.

### Comparison

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
| `source` | string | `"laps"` (learned by the hub from driven laps), `"bundled"` (a track file shipped with the hub) or, from older hubs, `"first_valid_lap"`. |
| `laps` | int (optional) | `"laps"` outlines: how many laps were averaged into it (up to 5). Added in v1. |
| `step_m` | number (optional) | `"laps"` outlines: lap distance between points. Added in v1. |
| `length_m` | number (optional) | Lap length the points span. Added in v1. |
| `sector_starts` | `[int, int, int]` \| null | Indices into `points` where sectors 1–3 start. |
| `display` | `{ "flip_x": bool, "flip_z": bool, "rotate_deg": number }` | How to draw the world: screen right = +x, screen down = +z, **after** applying these. From the hub's `[map]` config, so the map matches the in-game minimap. The dashboard's `?map=` URL option overrides it, for finding the right config value. |

### LapRecord

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
| `lap_class` | string | *(Added in v1, optional.)* `"pro"` (every assist off for the whole lap, docs/LAP_ASSUMPTIONS.md A16) or `"open"`. Missing means `"open"`. |

### Moment *(added in v1, optional)*

Something the TV shows full screen for a few seconds, then returns to the view it was on. Every moment has
`kind` and `at` (Unix ms); clients ignore kinds they don't know.

| `kind` | Fields |
|---|---|
| `now_driving` | `rig_id`, `rig_name`, `driver`, `track_key`, `track_name`, `today_record` (`{ "driver", "lap_ms" }` \| null), `personal_best_ms` (int \| null). Sent when staff start a session on a rig. |
| `record` | `rig_id`, `driver`, `track_key`, `track_name`, `lap_ms`, `lap_class`, `records`: what the lap beat, most important first, each `{ "period": "all_time" \| "today", "lap_class": "pro" \| "open", "previous_ms", "previous_driver", "gap_ms" }` (`gap_ms` negative). Only sent when an existing record is beaten. |
| `card` | `rig_id`, `driver`, `token`, `url`, `best_ms`, `track_name`. A session ended and its story card is ready: the TV shows a QR code to `url` for 30 s (not full screen). The card itself is `GET /api/cards/<token>`, outside this feed. |
| `race_podium` | `track_key`, `track_name`, `session_type`, `drivers` (`rank`, `position`, `driver`, `rig_id`, `grid_position`, `laps`, `best_lap_ms`, `total_time_s`, `status`, `card_url`, `card_token`), `wifi` (`null` for now). *(Added in v1.)* A race ended with 2 or more cafe drivers; needs `sharing` and `race_podium`. `rank` is the cafe ranking, `position` the real race position. |
| `challenge_winner` | `challenge_id`, `title`, `track_name`, `lap_class`, `prize`, `winner` (entry \| null), `runners_up` (entries). Sent once when a challenge ends. |
| `podium` | `reason` (`"hourly"`, `"scheduled"` or `"staff"`), `track_key`, `track_name`, `entries`: today's top three (LeaderboardEntry). |

Pro laps count on the Open boards too; the Pro boards hold Pro laps only.

### Leaderboard

Best counted lap (valid, not an out lap) per driver (per rig if the driver name is unknown) on one track
within a period. Laps are stored in the hub's database (`<data_dir>/laps.db`), so boards survive hub
restarts.

| Field | Type | Notes |
|---|---|---|
| `track_key`, `track_name` | string, string \| null | |
| `period` | string | `"today"`, `"week"` (from Monday) or `"all_time"`. Clients ignore boards with other values. |
| `lap_class` | string | *(Added in v1, optional.)* `"open"` (every lap, the default when missing) or `"pro"` (Pro laps only). The hub sends both classes for each period. |
| `since` | int \| null | Unix ms where the period starts, in the hub PC's local time; `[leaderboard] day_start_hour` sets when a day starts. `null` for all time. |
| `entries` | array | Fastest first, at most 100. |

```json
{ "track_key": "F1:7", "track_name": "Silverstone", "period": "today", "since": 1791237600000,
  "entries": [
    { "rank": 1, "rig_id": "r1", "rig_name": "Rig 1", "driver": "Akshat", "lap_ms": 88123,
      "sectors_ms": [28011, 33456, 26656], "gap_ms": 0, "tyre": { "compound": "soft", "label": "C3", "age_laps": 2 },
      "lap_number": 4, "set_at": 1791302455000 } ] }
```


Today's board *(added in v1, optional fields)*: `record_minis` (the record lap's 24 mini-sector times in ms, when the hub traced that lap: the TV's record ghost and its delta to today's record) and `mini_owners` (per mini-sector, the rig of the driver fastest through it today, from each driver's best traced lap).
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

- Interpolate `position` (and inputs) between frames so dots and needles move at display rate.
- Until an outline exists for a track, draw the path driven so far (the map auto-fits to it).
- Sector colours: `session_best` purple, `personal_best` green, `normal` yellow.
- `no_data` rigs are left off the TV; staff see them on `/staff` (Health tab).
- `status.warnings` and rig addresses are for staff tools; the TV never displays them.
- The page is `tv.page` unless a key on the TV PC chose another one more recently than `tv.updated_at`.
