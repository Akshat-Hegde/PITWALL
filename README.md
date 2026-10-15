# Pitwall

Live broadcast timing for sim racing cafes: a local LAN telemetry hub and TV dashboard. Milestone 1: F1 25 (UDP formats 2025 and 2026).

Status: milestone 1 is feature-complete and awaiting its end-to-end test on real devices
([docs/TEST_PLAN.md](docs/TEST_PLAN.md)). The hub receives F1 25 telemetry from every rig on the LAN, tracks
laps, sectors and bests, stores laps in SQLite, and serves the TV dashboard (LIVE, MULTIVIEW,
attract mode) with a live WebSocket feed. Lap tracking was built from the UDP spec; what it assumes about the
real game is listed in [docs/LAP_ASSUMPTIONS.md](docs/LAP_ASSUMPTIONS.md), to be confirmed in that test.

## Setup (Windows, Python 3.11+)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy config\hub.example.toml config\hub.toml   # optional: technical settings (ports, recorder, feature switches)
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
with `[dashboard] directory`), and the feed rate with `[dashboard] frame_hz` (10–20, default 15). The steering
wheel graphic turns with `[dashboard] steering_wheel_rotation_deg` (lock-to-lock, default 360). Until a track
has an outline, the map draws the path driven so far.

`?map=flipx,flipz,rotN` (any combination) overrides the map orientation, for matching the in-game minimap
during testing; the active setting is shown on the map.

Mock options, combined in the URL, e.g. `http://localhost:5173/?outline=late&mismatch=1`:

| Option | Effect |
|---|---|
| `speed=N` | Run the simulation N times faster (e.g. `speed=8` to reach a leaderboard quickly). |
| `outline=late` | No track outline until the first valid lap: trail-only map. |
| `mismatch=1` | Rig 2 reports UDP format 2026 (a warning in the feed; the TV never shows warnings). |
| `recorder=recording\|low\|stopped` | Recorder status / low-disk warnings in the feed (not shown on the TV). |
| `offline=0` | Hide the configured-but-offline Rig 3. |
| `board=N` | Add N earlier drivers to the leaderboard (e.g. `board=8` for a full board of 10, `board=12` to see paging). |
| `rigs=N` | Number of driving rigs, 1–12 (default 2). |
| `idle=1` | Every rig stays in the menu: shows attract mode. |

**TV pages.** The TV is drawn on a fixed 1920 x 1080 canvas scaled to the screen (letterboxed if the shape
differs), so nothing overflows on any TV, 1080p or 4K. Names up to 16 characters shrink to fit before they
are ever cut. Rigs the hub has no data from are left off the TV (they show on `/staff`). The look is
specified in [docs/DESIGN.md](docs/DESIGN.md).

- **LIVE** (default, the Pitwall broadcast screen):
  - **Headline ticker** along the top, a new line every 7 s: who is up or down on today's record after which
    sector, what lap they are on for and where it would put them, who is chasing their own best.
  - **Today's board** (Open, best lap per driver, up to 8): drivers on a rig in their rig colour, the record
    row highlighted, sector bars, and a dashed "on this lap" row for the hottest lap at its predicted position.
  - **Map**: a glowing track with each of 24 mini-sectors in the colour of the rig fastest through it (with one
    rig: how this lap compares with their best), sector marks, every car with its name, the hottest lap ringed,
    and a dashed ghost of today's record (and, with one rig, of their personal best).
  - **Focus card** for the hottest lap (the rig on course for the fastest lap, or the one staff picked): lap,
    name, a big live delta to today's record (or their best), the predicted lap and position, sector times,
    speed with a barcode meter, gear and DRS, the steering wheel, throttle / brake and the four tyres.
  - **Session story**: every lap of the last hour per driver against the clock, best laps ringed, invalid
    laps hollow, today's record as a dashed line; and **Moments**: the last five personal bests, records,
    invalid laps and new drivers.
- **MULTIVIEW:** one tile per active rig, up to 12 (1 full screen, 2 side by side, 3-4 in a 2 x 2 grid, 5-6 in
  3 x 2, 7-8 in 4 x 2, 9-12 in 4 x 3):
  name, speed and gear, steering wheel, pedal bars, a small map with only that car, lap time and delta.
- **Welcome and leaderboard (attract mode):** the cafe name, today's top 10 and the track record holder;
  today, this week and all time side by side.
- **Head to head** (staff-triggered): the two drivers closest on best lap, with the map coloured by who is
  faster in each of 24 mini-sectors, corner labels, lap share bars and both speed traces. The hub keeps every
  driver's best traced lap per track and day, so it is there straight after a TV reload or hub restart.

The fuel, ERS, g-force, damage, brake temperature and tyre wear values are still in the feed
(docs/WS_SCHEMA.md) but no longer on the TV.

**Switching.** Staff choose the page on `/staff` (Rigs tab, **TV** panel: LIVE or MULTIVIEW, the rig for
the trace strip, and **Show head to head** / **Show teams** over the page until **Back to the page**). On the
TV PC's keyboard, `1` is LIVE and `2` MULTIVIEW. The newer choice wins, and it is kept across a reload or a
hub restart. Nothing rotates while anyone drives. With nobody driving for 60 s the TV goes to attract mode
(welcome, leaderboard, and the team board during an event), and back to the page as soon as a car drives.
Moments (below) play over the page and never change it. `?view=live|multi|board|attract` fixes the view for
testing.

**Broadcast moments** (full screen for a few seconds, then back to the view):

- **Now driving:** when staff start a session on `/staff`: rig, driver, track, today's record and the
  driver's personal best there.
- **Record broken:** a lap beats today's or the all-time record, Pro or Open: the new time, the gap to the
  old record and who held it.
- **Podium:** today's top three at the end of every hour (`[moments] podium_every_min`, 0 = off) or when staff
  press **Show podium** on `/staff`.
- **Battle pop-ups** (lower third): two best laps within `[moments] battle_margin_ms` (300 ms), or a driver
  on course to beat the fastest lap (past 40 % of the lap and ahead of it).

**Pro and Open:** a lap is Pro when every assist is off for the whole lap (traction control, ABS, steering
and braking assist, automatic gears, dynamic racing line; docs/LAP_ASSUMPTIONS.md A16). Pro laps count on
the Open boards too.

**Portrait screen:** `http://<hub>:8000/portrait` is a 1080×1920 layout for a vertical TV at the entrance:
cafe name, track record holder, today's top 10 and who's on track.

**Sounds:** `[sounds] enabled = true` plays a short tone when a session starts and a fanfare on a record.
Browsers only play sound after someone has clicked the page once; on a kiosk PC start Chrome or Edge with
`--autoplay-policy=no-user-gesture-required` so it works unattended.

**Features:** every optional feature can be switched off in `[features]` in `hub.toml` (all on by default; see
`config/hub.example.toml`):

| Flag | What it switches |
|---|---|
| `moments` | "Now driving" and "record broken" full-screen moments on the TV |
| `battles` | Battle pop-ups on the TV |
| `podium` | Podium screen (hourly and on staff command) |
| `attract` | Attract mode with nobody driving |
| `portrait` | `/portrait` layout for a vertical screen |
| `head_to_head` | Head to head view |
| `onboard` | The MULTIVIEW page (off = LIVE only) |
| `sharing` | Story cards and every QR code (cards, podium, Wi-Fi) |
| `challenges` | Weekly challenges |
| `events` | Corporate events with teams |
| `owner` | The `/owner` page |
| `race_podium` | Race podium and race cards (needs `sharing`) |
| `self_checkin` | Guests put their own name on a rig from a QR sticker |
| `auto_end_sessions` | Sessions end at closing time, and timed sessions once over time and off track for 5 minutes |
| `backup_warning` | Owner page and staff Health warn when the last backup is over 2 days old |

**The TV looks after itself.** If the feed goes quiet for 3 seconds the TV reconnects; after 10 seconds it shows
the waiting or attract screen rather than frozen cars. When the hub is upgraded the TV reloads itself (at most
once a minute), so nobody has to touch the TV PC. It keeps the screen awake where the browser allows it, and
uses the hub's clock, not its own. The TV shows the same screens around the clock, and never shows addresses,
warnings or other technical messages: those are on the staff page's Health tab.

Mock options for demos: `?moment=now_driving|record|podium&momentAfter=5` shows that moment after 5 s;
`?podium=60` adds a podium every 60 s of simulated time.

Branding comes from `[cafe]` in the hub config: `name`, plus CSS variables in `[cafe.branding]` (e.g.
`"--brand-accent" = "#0a7cff"`), applied to the page as-is.

## TV PC: kiosk launcher

On the PC that drives the TV, double-click `tools\windows\Start TV.cmd`. It waits until the hub answers, then
opens the dashboard full screen in Edge or Chrome (kiosk mode) with sound allowed
(`--autoplay-policy=no-user-gesture-required`), in its own browser profile. **Alt+F4** closes it.

Options (run from a terminal in `tools\windows`, or put them in a shortcut):

```
"Start TV.cmd" -Url http://192.168.1.64:8000/            # the hub is another PC
"Start TV.cmd" -Url http://192.168.1.64:8000/portrait    # the entrance screen
"Start TV.cmd" -Browser edge                             # edge, chrome or auto (default: Chrome, else Edge)
"Start TV.cmd" -Url http://192.168.1.64:8000/ -StartOnLogin   # also open it at every Windows login
"Start TV.cmd" -RemoveStartOnLogin
```

The installer sets this up for you (the **Pitwall TV** shortcut, and "This PC only shows the TV" for a second
TV PC); while the hub is starting the TV shows a local "Starting up" page and switches over by itself. For a
TV PC that should come back by itself after a power cut, also set Windows to sign in automatically (`netplwiz`,
see [docs/INSTALL.md](docs/INSTALL.md)) and set the BIOS to power on after AC loss.

## First-run setup

The owner sets the cafe up in a browser at `http://<hub PC>:8000/setup`: name, tagline, logo, accent colour, opening hours, owner PIN and staff PIN. The choices are saved in `data/settings.json` and override `config/hub.toml` (a `--owner-pin` flag still wins).

Before setup is done, `/setup` needs the one-time setup code. The installer makes it and shows it on its last page; a hub started from source makes one on first start. While setup is not done the hub logs it at every start (console and `data/logs/hub.log`, never the TV). On the hub PC, `python -m simtelemetry setup-code` prints it (`--new` makes a fresh one). Ten wrong codes lock the page for a minute. After setup the code is deleted and `/setup` asks for the owner PIN.

## Staff page and driver profiles

Open `http://<hub>:8000/staff` on a phone or tablet. Tabs (a link like `/staff#queue` opens one):

- **Rigs:** start a session for a walk-in name, the next person in the queue, or a driver profile, with a
  session time (10–60 min or no timer). Names are up to 16 characters (what the TV fits). The time left is on
  the staff page only (the TV doesn't show it); from 5 minutes left the staff page shows **Extend?** (+5 / +10).
  **End session** asks first, then frees the rig and makes the driver's card ("No card this time: no clean lap
  was completed." when there was none). Starting a session shows **Now driving** on the TV. Starting a name
  that is already driving or on today's board asks "Same person?", so one person's laps stay on one line.
- **Queue:** names waiting for a rig, in order; the TV's attract screen shows the first few as **Next up**
  (names only).
- **Drivers:** profiles keyed by phone number. Search by name or the last 4 digits, or create one: the phone
  number is only stored after the driver agrees (the consent checkbox is required). Quick profiles made at
  events have a name only. A profile shows visits, best
  lap per track and the improvement since the last visit. **Delete profile** removes the profile, its phone
  number, its sessions and all its laps (they leave the leaderboards too).
- **Health:** technical diagnostics, for staff only: warnings (another program on the telemetry port, a rig
  sending nothing with a checklist of its game settings, a wrong UDP Format, the hub's address changed, an old
  backup, low disk), each rig's address, state (On track, In menu, No data, Wrong game settings) and packet
  rate, the game settings to enter on every rig (see [docs/RIG_SETUP.md](docs/RIG_SETUP.md)), and the **Test
  from your phone** QR. A paused or spectating game counts as In menu, not driving. None of this is
  ever shown on the TV; it is also in the hub log.
- **Show podium** (top right) puts today's top three on the TV.

Laps are saved under the session's driver, else the game's player name, else the rig name; changing the
name later doesn't rename earlier laps. A profile's laps follow the profile (two profiles with the same name
stay separate). The TV shows the name and that driver's best lap on the track ("PB").

The page always asks for the **staff PIN**, chosen on the setup page (it may be the same as the owner PIN; the
setup page can't be saved without one). A hub set up by an older version without a staff PIN accepts the owner
PIN instead and shows a red "Set a staff PIN on the setup page" banner until one is set. A hub with no PIN at all
(setup not finished) shows "Finish setup first" and no staff data. Five wrong PINs in a minute lock that device
out for a minute; the third lock-out within an hour locks it out for 15 minutes, is logged and is shown on the
owner page ("Someone tried wrong PINs 15 times at 21:40").

**Sessions end by themselves** (`[features] auto_end_sessions = true`, the default):

- At **closing time** (the opening hours on the setup page) every open session ends, exactly as if staff had
  pressed **End session**, so the driver's card is still made.
- A **timed** session ends once its time is up **and** the car hasn't been on track for 5 minutes; a driver
  still on track is never cut off. Sessions with no timer and self check-in sessions have no time limit.
- A session left open when the hub PC was switched off ends as soon as the hub starts again on a later day.
- The rig on the staff page then says "Ended automatically at closing time" or "Ended automatically: time was up".

## Competitions

On `/staff`, the **Compete** tab:

- **Weekly challenges:** pick a track, Pro or Open, the first and last day and a prize ("Free hour for the
  fastest Pro lap"). The challenge board is the best lap per driver in that window. The TV shows the
  challenge (time left, prize, leader) on the leaderboard view, the welcome screen and the portrait screen,
  and announces the winner full screen when it ends.
- **Pro and Open boards:** the leaderboard view alternates between Open (all laps) and Pro (every assist
  off) every 15 seconds once there are Pro laps.
- **Corporate events:** event name, company, company colour, optional track and "best N". Add teams, then their
  drivers from driver profiles (search by name or phone); a walk-in gets a **quick profile** (name only, no
  phone, so no consent needed) right from the team. Laps count for a team only when driven under that
  profile, never by matching a typed name, and upload the company logo and team logos (PNG, JPEG or WebP,
  up to 512 KB; stored in `data\logos\`). The team score is the average of each team's best N drivers' best
  laps since the event started. While the event runs the TV uses the company colour, shows the company next to
  the cafe name and adds the **Teams** board to attract mode; **Show teams** on `/staff` puts it on the TV. **End event** goes back to normal.

`[features] challenges` and `[features] events` switch these off.

## Owner analytics

`http://<hub>:8000/owner` (the owner PIN, chosen on the setup page) shows, for the
last 7, 30 or 90 days: driving hours and sessions per day, rig utilisation (session time over the opening
hours from the setup page, per rig per day), a peak-hours heatmap (average rigs in use by
weekday and hour), new vs returning drivers, popular tracks and the busiest days. **Daily / Sessions / Laps
CSV** download the figures. Everything comes from the hub's own database; nothing leaves the PC.
A bookmark like `/owner#pin=1234` unlocks it on the owner's own device (the part after `#` never reaches the
hub). `[features] owner = false` turns the page off.

## Backups and restore

Every night at `[backup] hour` (default 04:00) the hub saves `pitwall-YYYYMMDD-HHMM.zip` with the lap database
(copied safely while the hub runs), the owner's settings, the rig names, the check-in codes, the uploaded logos
and `hub.toml`, and keeps the last `keep` (14). The one-time setup code is never included.

**Where backups go:** the owner chooses the folder on the owner page (Backups card), for example a USB stick such
as `E:\Backups`; the hub checks it can write there and keeps the choice in `settings.json`. Without a choice the
zips go to `[backup] directory`, or a `backups` folder next to the data folder. A backup on a USB stick survives
a dead PC.

The owner page shows the folder, the last backup and a **Back up now** button; `Pitwall.exe backup` does the same
from a command prompt. When a backup fails the owner page says why in plain words ("The USB stick isn't plugged in
(drive E: not found).", "The backup drive is full.", ...). When the last good backup is more than 2 days old, the
owner page and the staff Health tab show "Last backup: 5 days ago. Check the backup folder or USB stick."
(`[features] backup_warning = true`; never on the TV). `[backup] enabled = false` switches the nightly job off.

To restore, stop the hub, then run `Pitwall.exe restore <zip>` (refused while the hub is running) and start the hub
again; [docs/INSTALL.md](docs/INSTALL.md) has the step-by-step version. Network folders and mapped drives can't be
chosen: the hub runs in the background and can't see them.

## Demo mode

`http://<hub or dev server>/?source=mock&demo=1` runs a busy cafe without any rig: six simulated drivers, a
full leaderboard with Pro and Open boards, a weekly challenge, a corporate event with four teams, a podium
every three minutes and a scripted loop of moments (now driving, a story card QR, a record, a challenge
winner). `/card/demo` shows a sample story card.

**The whole product, one command** (no rigs, no game):

```
python -m simtelemetry run --demo
```

This re-seeds `data-demo\` with 60 days of a busy cafe (sessions, laps, driver profiles, a weekly challenge, a
queue) and starts the hub on it with six **simulated rigs** that send real F1 25 packets through the hub's
normal pipeline: live cars on the map, laps, records, head to head, session timers and story cards all work as
they would in the cafe. Open the TV at `http://localhost:8000/`, the staff page at `/staff`, and the owner page
at `/owner` (PIN `0000` for both unless `--owner-pin` is given). It doesn't listen for real rigs, so stop the
normal hub first (or give the demo another `--http-port`).

**Demo director (for filming):** on `/staff` in demo mode, press **Director** (top right) for buttons that put
each moment on the TV now: now driving, record (today or all time, Pro or Open), battle, podium, challenge
winner and a story card QR (from a real session with a clean lap, so give the rigs two or three minutes).

`python -m simtelemetry seed-demo` only fills the folder, without running anything.
`seed-demo` only writes to an empty folder (or one it made before), never to your real `data\`.

## Self check-in

Guests can put their own name on a rig without staff. Each rig has its own QR sticker (print them from
**Staff -> Check-in QR**, see below). The flow on the guest's phone:

1. Scan the sticker on the rig (the phone must be on a Wi-Fi that reaches the hub, see below). The page shows the
   rig and asks for a name.
2. Type a name (up to 16 characters) and tap **Start**. The rig shows **Now driving** on the TV and the leaderboard, exactly as if
   staff had started the session; laps count for that name.
3. The phone shows the laps and best lap so far. **I'm done** ends the session and the **story card** opens on
   the same phone (**Save for Instagram story**). If staff end the session, the phone shows the card link
   too. **Drive again** starts over.

Details:

- **Guest Wi-Fi:** guests' phones must be on a Wi-Fi that can reach the hub PC: the main cafe Wi-Fi, or a guest
  network with "client/guest isolation" turned off. To check, scan **Test from your phone** on `/setup` or the
  staff Health tab with a phone on that Wi-Fi: it opens `/hello`, which says "Your phone can reach Pitwall.
  Check-in and cards will work.", and `/setup` then shows "A phone reached the hub at 14:02".
- **Busy rigs:** if someone is already driving, the page says "Someone is driving"; a second check-in is
  refused, so a guest can't take over a rig by scanning it.
- **Idle takeover (check-in sessions only):** if a session that a guest started from their phone has not been
  driving for 2 minutes (nobody on track), the sticker shows "This rig looks free" and a new check-in replaces it;
  the earlier driver still gets their card. Sessions staff started (paid bookings) are never taken over from a
  phone, however idle: the page says "Someone is driving" and staff end them.
- **Bad names:** names are checked against a built-in list of slurs and swear words (English and common
  Hindi, with look-alike spellings). Add your own words under `[checkin] blocked_words = ["word", ...]` in
  `config\hub.toml`. Staff can still start any name from the Rigs tab.
- **Switch it off:** `[features] self_checkin = false`; the stickers then show "Check-in is switched off".
- **Printing stickers:** **Staff -> Check-in QR** opens an A4 sheet with one sticker per rig (and the guest
  Wi-Fi QR if one is set in `/setup`). Print, cut and stick one on each rig.
- **New code:** the Rigs tab has **New code** per rig. It invalidates that rig's old sticker immediately (use
  it if a sticker was photographed or stolen), so print and stick the new one.

## Sharing: session story cards

When staff end a session (or start the next driver on the rig), the hub makes a **story card** if the driver
set at least one clean lap. It shows the driver, track, best lap, top speed, theoretical best (best sectors
added up), laps, the improvement since the last visit (profiles only) and the best lap's 24 mini-sectors on
the track map, in the cafe's branding.

- The TV shows a QR code to the card for 30 seconds; the staff page shows one too, after **End session**.
- The card page (`http://<hub>:8000/card/<code>`) draws the 1080×1920 image on the phone: **Save image**, or
  **Share on WhatsApp** (opens WhatsApp with a message and the card's link).
- **Phones must be on the cafe's network (Wi-Fi) to open the card**, and so must anyone the link is sent to.
  Saving the image and posting it works from anywhere. On an iPhone, **Save for Instagram story** shows the
  picture full screen: press and hold it, then tap Save to Photos.
- `/card/demo` shows a sample card without a hub. `[features] sharing = false` turns cards off.

**Privacy:** phone numbers, names and lap times stay in `data\laps.db` on the hub PC; nothing is sent
anywhere. The TV and its WebSocket feed only ever carry names, never phone numbers.

## Race podium and story cards

Race sessions (Race, Race 2, Race 3) are handled differently from time trials. Each rig reports its own
driver's Final Classification; results for the same track within 90 seconds form one race, and the hub
publishes it at once when every rig seen racing on that track in the last 90 seconds has reported. Otherwise
it waits 8 seconds after the last report, and at least 90 seconds after the first, so a slower finisher on the
same LAN race is not split into a separate result. Practice,
qualifying and Time Trial never make a race result.

- **Two or more cafe drivers:** the TV shows a 15 second podium with a QR code beside each name, then 25
  seconds of "Grab your card" (up to 10 finishers). Cafe drivers are ranked by their in-game finishing
  position; finishers come before DNF/DSQ.
- **One cafe driver (racing the AI):** no podium, but they still get a race card through the corner card QR.
- **Race card:** position, grid position and places gained, laps, best lap, total time plus penalties,
  result, track and "1st of 4 at <cafe>". It is a story card with `kind: "race"`; the card page has
  **Save for Instagram story** (1080x1920) and a hint to post it from the gallery.
- **Phones must be on the cafe Wi-Fi** to open a card. In `/setup` the owner can add an optional guest
  Wi-Fi (name, password, security). The TV then shows a "Join our Wi-Fi" QR beside the card QR codes, with
  the network name only; the password is never shown as text. Use a network that reaches the hub: the main
  Wi-Fi, or a guest network with client isolation off (check it with **Test from your phone**).
- **Feature flags:** `[features] race_podium = false` turns the podium and race cards off; `sharing = false`
  turns off every QR code (cards, podium and Wi-Fi).
- **Demo:** on `/staff` in demo mode, the Director has a **Race podium** button (`POST /api/staff/demo/race`) that
  ends a simulated 4-rig race, for screenshots and manual checks.

## Lap database

Every recorded lap goes into SQLite at `<data_dir>/laps.db` (default `data\laps.db`), together with each
track's outline. The TV's leaderboards (today, this week, all time) are read from it, so they survive hub
restarts. "Today" is the cafe's business day: it starts at midnight, or at the closing hour when the cafe
closes after midnight (opening hours on the setup page, e.g. "closes at 02:00 (next day)"), so a lap at 01:30
counts for the evening before. `[leaderboard] day_start_hour` in hub.toml overrides this when set to 1-23.
The week starts on Monday. To start the boards from scratch, stop the hub and delete or rename `laps.db`.

`replay` keeps its laps in memory, so replaying a capture never changes the real boards; add `--save-laps`
to store them. `replay --rigs 6 --names "Maya,Kofi,..."` plays six rigs at once from a capture's sources
(reused and staggered round the track): real data for demos and screenshots.

**Track outlines.** The map outline is learned from the first lap whose path covers the whole lap (valid or
not, with no flashback) and refined by averaging in the next four. To ship a good outline with the hub:

    python -m simtelemetry save-outline              # list the learned outlines
    python -m simtelemetry save-outline Silverstone  # write hub/simtelemetry/tracks/F1-7.json

A bundled track file is used straight away on every hub and never replaced by a learned outline.

## Python on the dev machine and building the installer

Day-to-day development uses the **Microsoft Store** build of Python 3.11 in `.venv`. That is fine for running the
hub and the tests, but Store Python is unreliable with PyInstaller and with Windows Firewall *program* rules, so the
packaged build uses a separate **python.org 3.11** in `.venv-build`.

## Building the installer

1. Install python.org Python 3.11 (`winget install -e --id Python.Python.3.11`).
2. Create the build-only venv once: `"%LOCALAPPDATA%\Programs\Python\Python311\python.exe" -m venv .venv-build`
3. Run `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`. It builds the dashboard (`npm ci`,
   `npm run build`), runs PyInstaller (`packaging\pitwall.spec`) into `dist\Pitwall\` (one folder, `Pitwall.exe`
   plus `_internal\`), smoke-tests the exe on HTTP port 8199 (`run --demo`, including a logo upload), then compiles
   the installer with Inno Setup 6 (`winget install -e --id JRSoftware.InnoSetup`) into `dist\Pitwall-Setup-<version>.exe`.
   `build\` and `dist\` are not committed. Never run the installer on the dev PC; see [docs/INSTALL-TEST.md](docs/INSTALL-TEST.md).

Double-clicking `Pitwall.exe` (no arguments) starts the hub, same as `run`.

## Docs

- [docs/INSTALL.md](docs/INSTALL.md): installing at a cafe (the Windows warning, antivirus, router, setup, guest
  Wi-Fi, TV PCs, backups, restore, upgrading).
- [docs/INSTALL-TEST.md](docs/INSTALL-TEST.md): the steps to test the installer on a spare PC or VM.
- [docs/RIG_SETUP.md](docs/RIG_SETUP.md): in-game telemetry settings for each rig, SimHub, and what to do when a rig
  doesn't show up.
- [docs/TEST_PLAN.md](docs/TEST_PLAN.md): firewall setup and the end-to-end test checklist (2 PCs, 2 copies of F1 25).
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
  state/         reducer, store, position trails, lap traces (mini-sectors, speed traces)
  map/           map geometry (display transform, fit)
  components/    header, track map, timing, leaderboards, race / leaderboard / head-to-head / onboard views
  views.ts       view selection and rotation (auto, attract mode)
```
