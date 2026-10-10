# TV dashboard design

The TV dashboard should read like a broadcast timing graphic: flat near-black, thin lines, one typeface, big
white numbers, small grey labels. The style is ours. **No F1 logos, F1 fonts, team names or logos, or sponsor
marks** anywhere in the UI, the mock data or the screenshots.

Tokens live in `dashboard/src/styles.css` (`:root`). Components use the tokens only, never raw values. The cafe
can override `--brand-accent` (and any other token) from `[cafe.branding]` in the hub config.

## 1. Tokens

### Colour

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0B0C0F` | Page background. Flat, no gradients, no patterns. |
| `--panel` | `#111318` | The few real panels (one step lighter than `--bg`). |
| `--panel-2` | `#171A20` | Inset areas inside a panel (bar tracks, the g-circle). |
| `--line` | `rgba(255,255,255,0.08)` | Hairline dividers between rows and sections. |
| `--line-strong` | `rgba(255,255,255,0.16)` | Axis lines, the active-row divider, the map's neutral track. |
| `--text` | `#FFFFFF` | Values, names. |
| `--text-2` | `rgba(255,255,255,0.55)` | Labels, secondary values (rig name under the driver). |
| `--text-3` | `rgba(255,255,255,0.35)` | Placeholders (`–:––.–––`), units, disabled. |
| `--brand-accent` | `#E4202C` (config) | The one brand colour: logo mark, the active-view tick, "SAVE!", brake bar. |
| `--timing-purple` | `#B46CFF` | Fastest today (lap, sector, mini-sector). **Text and lines only.** |
| `--timing-green` | `#38D97A` | Driver's own best / ahead on a gap. **Text and lines only.** |
| `--timing-yellow` | `#F2C230` | Slower than own best / behind on a gap. **Text and lines only.** |
| `--temp-cold` / `--temp-hot` / `--temp-warm` | `#5AA9FF` / `#FF5A4F` / `#FFA43D` | Tyre and brake temperatures as text colour; in range is `--text`. |
| `--compound-*` | soft `#FF4A4A`, medium `#FFD43B`, hard `#ECECEC`, inter `#45C46B`, wet `#4C8DFF` | The small compound dot only. |

Rules:
- Purple, green and yellow mean timing (fastest / own best / slower). They are only ever a text colour or a
  thin line (map mini-sectors, mini-sector ticks). Never a filled box or a background.
- Rig colours come from the hub and are shown **desaturated** (`softenColour`, ~25% less saturation). A rig colour is
  used only for: the 3 px name stripe, its map dot and trail, its lines in charts and analysis bars. Never as a
  panel tint or text colour for values.
- No gradients, tinted panels, diagonal hatching, chequered patterns, glows or drop shadows.

### Type

One family: **Barlow** (UI, numbers) and **Barlow Condensed** (names, labels, headings), self-hosted from
`@fontsource/*` (no CDN). Weights: 400, 500, 600, 700. **No italics.**

All numbers use tabular figures (`font-variant-numeric: tabular-nums`, set on `body`) so times don't jitter.

`1rem` = 1.85 % of the screen height (20 px at 1080p, 40 px at 4K), so every size below scales with the TV.

| Token | Size | Family / weight | Use |
|---|---|---|---|
| `--fs-label` | 0.6rem | Condensed 600, uppercase, `+0.12em` tracking, `--text-2` | Column and field labels. |
| `--fs-small` | 0.75rem | Barlow 500 | Secondary values (rig name, units, tyre age). |
| `--fs-body` | 0.9rem | Barlow 500 | Running text, small timing cells. |
| `--fs-value` | 1.2rem | Barlow 600 | Timing values in rows. |
| `--fs-value-l` | 1.7rem | Barlow 600 | Lap clock, key times on cards. |
| `--fs-name` | 1.3rem | Condensed 700 uppercase | Driver names. |
| `--fs-display` | 2.8rem | Barlow 600 | Speed and gear. |
| `--fs-title` | 2.2rem | Condensed 700 uppercase | View titles (track name, "Head to head"). |

Values are large and white; labels are small, grey and uppercase. Units sit in `--text-3` at `--fs-small`
next to the value.

### Spacing, lines, radii

- Spacing scale (rem): `--s1 0.2`, `--s2 0.4`, `--s3 0.6`, `--s4 0.8`, `--s5 1.2`, `--s6 1.6`, `--s7 2.4`.
- Page margin `--s6`; grid gutter `--s5`; row padding `--s3` vertical.
- Hairline: `1px solid var(--line)`. Rig stripe: 3 px (`--stripe`). Track line on the map: 3–4 px at 1080p
  (`0.18rem`), scaled with the screen. Throttle/brake bars: 4 px (`--bar`). No thick borders.
- Radii: `0`. Everything is square, except dots (round) and bar ends (square).

### Motion

- 150–250 ms, `ease-out`, opacity and colour only. View changes fade 250 ms. A new best lap fades its colour in.
- Bars may transition width over 120 ms (smooths the 15 Hz feed). Nothing bounces, scales or slides.
- Respect `prefers-reduced-motion`: no transitions.

## 2. Layout

- Strict grid: page margin `--s6`, gutter `--s5`. Sections are separated by space and hairlines, not boxes.
  At most one level of panel.
- **Header** (thin, 2.6rem): cafe name left (with a small accent square), session and track centre, link state and
  clock right. Hub warnings show as one line under the header, accent-coloured text.
- Works at 1920×1080 and 3840×2160 (same layout, `rem` scales), with 1 to 10 rigs.

## 3. Components

**Driver name**: 3 px stripe in the rig colour, name in Condensed 700 uppercase, rig name below in `--text-2`.

**Timing values**: current lap, S1–S3, last, best, gap. Label above in `--fs-label`. Lap and sector times are
white unless rated: purple (fastest today), green (own best), yellow (slower, only on gaps and mini-sectors).
Placeholders are `--text-3`. An invalid lap's clock is struck through in `--text-3`.

**Mini-sectors**: 24 per lap (8 per sector), worked out in the dashboard from lap distance and time.
A row of short 3 px lines under the sector times; each completed one is purple / green / yellow, the rest
`--line-strong`.

**Speed**: big number + `KM/H` unit + gear beside it, and a thin 4 px bar under it (0–360 km/h). No dial.

**Throttle / brake**: two thin horizontal bars, throttle `--text`, brake `--brand-accent`.

**Tyre**: compound dot (0.5rem) + label (`C3`) + age in laps. On the onboard view: four small blocks
(FL FR / RL RR), temperature as coloured text, wear % below in `--text-2`.

**Track map**: neutral 3–4 px line in `--line-strong`; no glow, no casing. Coloured only by meaning: race view
colours mini-sectors of the lead car's current lap (purple / green / yellow); analysis view colours each
mini-sector in the faster driver's rig colour. Car dots are small (0.5rem) in the rig colour; the name label sits
off the track, joined to the dot by a thin leader line. Start/finish is a short white tick.

**Leaderboard rows**: position, stripe, name, rig, time, gap; hairline between rows; P1's time purple.

## 4. Views

| View | Shows | Key |
|---|---|---|
| **Race** | Map, timing (cards for up to 4 rigs, a tower for 5–10), and a bottom strip with today's top 3, speed trap and conditions. Per rig only: position, name, tyre, current lap, sectors + mini-sectors, last, best, gap, speed, gear, throttle/brake. | `1` |
| **Leaderboard** | Today / this week / all time for the track, 10 rows, paging beyond that. | `2` |
| **Head to head** | Two drivers (the closest pair by best lap) left and right, map centre coloured by who's faster per mini-sector, LOW/MEDIUM/HIGH SPEED zone labels on the corners with leader lines, mirrored bars for full throttle / heavy braking / cornering %, lap time and gap per side, speed traces underneath. Compares each driver's best lap seen by this TV. | `3` |
| **Onboard** | Per driving rig (two at a time, paging): speed, gear, revs, throttle/brake, steering, g-force circle with trail, four tyres (temperature, wear, pressure, brake temperature), fuel, ERS, DRS, damage, slide angle, saves and the SAVE! flash, lap share bars. | `4` |

Auto rotation (`0`): while someone drives, Race 40 s → Head to head 15 s (when two drivers have a full lap) →
Onboard 15 s. Idle (nobody driving for 10 s): Leaderboard 20 s → Race 10 s → Head to head 10 s (if available).
`?view=race|board|analysis|onboard` fixes the view.
