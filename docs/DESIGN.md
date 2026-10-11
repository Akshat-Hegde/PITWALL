# TV dashboard design (v3: two pages)

The TV dashboard should look like a motorsport broadcast: flat near-black, a clean grid, sharp racing accents
used sparingly, big white numbers, small grey labels. The style is ours.

**Never** in the UI, the mock or demo data, the screenshots or the docs: the F1 / F2 / F3 logos or any
"F"-mark lookalike, the words "Formula 1" / "Formula One" / "FIA", the official F1 fonts (or any font taken
from a reference file), team names or logos, sponsor marks, real driver names or photos. The reference files
in `docs/design-refs/` are not committed and nothing is extracted from them; every motif below is redrawn
by us in SVG/CSS.

Tokens live in `dashboard/src/styles.css` (`:root`). Components use tokens only, never raw values. The cafe
can override `--brand-accent` (and any other token) from `[cafe.branding]` in the hub config.

## 1. Tokens

### Colour

| Token | Value | Use |
|---|---|---|
| `--bg` | `#050506` (TV) | Page background. Flat; only the stripe-bundle motif may sit on it, never behind data. |
| `--panel` | `#101014` (TV) | Cards: sharp corners, 1 px `--edge` hairline, 3 px rig-colour left edge. One level only. |
| `--panel-2` | `#1B1C24` | Inset areas inside a card: bar tracks, the map well of the track card. |
| `--edge` | `#262731` | Card outline (1 px), so cards read without shadows. |
| `--line` | `rgba(255,255,255,0.08)` | Hairline dividers between rows and sections. |
| `--line-strong` | `rgba(255,255,255,0.16)` | Axis lines, neutral track line, empty barcode ticks. |
| `--text` | `#FFFFFF` | Values, names. |
| `--text-2` | `rgba(255,255,255,0.56)` | Labels, secondary values. |
| `--text-3` | `rgba(255,255,255,0.34)` | Placeholders (`–:––.–––`), units, disabled. |
| `--brand-accent` | `#E10600` (config) | The one brand colour: logo, motifs (stripes, slanted bars, kerb strips), active tab, "SAVE!", brake bar, record moments. |
| `--brand-accent-2` | `color-mix(--brand-accent 55%, black)` | The darker second bar of a double bar; derived, not configured. |
| `--timing-purple` | `#B46CFF` | Fastest today (lap, sector, mini-sector). **Text and thin lines only.** |
| `--timing-green` | `#38D97A` | Driver's own best / ahead on a gap. **Text and thin lines only.** |
| `--timing-yellow` | `#F2C230` | Slower than own best / behind on a gap. **Text and thin lines only.** |
| `--temp-cold` / `--temp-warm` / `--temp-hot` | `#5AA9FF` / `#FFA43D` / `#FF5A4F` | Tyre and brake temperatures, as text colour; in range is `--text`. |
| `--compound-*` | soft `#FF4A4A`, medium `#FFD43B`, hard `#ECECEC`, inter `#45C46B`, wet `#4C8DFF` | The compound letter / dot only. |
| `--delta-ahead` / `--delta-behind` | `#38D97A` / `#FF5A4F` | Live delta (ahead / behind own best), speed-trace gap shading. |
| `--throttle` / `--brake` | `#38D97A` / `#FF4A4A` | Pedal bars and the pedal trace. |
| `--tyre-ok` | `#2F9E5A` | Tyre block in the working window (cold / warm / hot use the `--temp-*` tokens). |

Rules (TV pages):
- **Colour is only for meaning**: rig identity, the delta (green / red), sector timing (purple / green /
  yellow), throttle / brake, and tyre temperature. Everything else is white or grey; the brand accent is
  left to the kerb strip and the attract / moment screens.
- Purple / green / yellow timing colours are a text colour or a thin line, never a fill. Tyre blocks are the
  one temperature fill.
- Rig colours (desaturated ~25 % by the dashboard) mark driver identity only: the 3 px card edge, the map
  dot and its leader line, the mini-sectors that rig owns, trace lines. Never a panel tint or a value colour.
- No gradients or patterns behind data, no glows, no drop shadows, no tinted panels.

### Type

**Saira** (variable: weight 100–900, width 50–125 %) and **Saira Condensed**, self-hosted from
`@fontsource-variable/saira` and `@fontsource/saira-condensed` (SIL OFL). No CDN.

| Role | Family / setting | Use |
|---|---|---|
| Display | Saira, `font-stretch: 125%`, weight 800 | Big numbers (speed, lap time on cards, gaps on moments), kinetic type, view titles. |
| Name | Saira, `font-stretch: 112%`, weight 700, uppercase | Driver names. |
| Value | Saira, weight 600 | Times and numbers in rows. |
| Body | Saira, weight 500 | Running text. |
| Label | Saira Condensed 600, uppercase, `+0.14em` tracking, `--text-2` | Field and column labels. |

- Tabular numerals everywhere (`font-variant-numeric: tabular-nums`, set on `body`).
- **No italics**, except the cafe logo if the cafe's own logo is italic.
- The TV is a fixed **1920 x 1080 design canvas** (portrait: 1080 x 1920) scaled to the screen and
  letterboxed if the shape differs; `1rem` = 20 px on the canvas. A 4K TV shows the same layout at 2x
  (canvases draw at screen resolution). Nothing may overflow the canvas.
- **At most three text sizes per panel**: label, value, hero. Hero is only for speed, gear, delta and lap
  time (wide display numerals). Names are value size.
- Names up to 16 characters fit: text shrinks to fit (`FitText`, down to 60 %) before it is ever cut.

| Token | Size | Token | Size |
|---|---|---|---|
| `--fs-label` | 0.6rem | `--fs-value-l` | 1.7rem |
| `--fs-small` | 0.75rem | `--fs-name` | 1.3rem |
| `--fs-body` | 0.9rem | `--fs-display` | 3rem |
| `--fs-value` | 1.2rem | `--fs-title` | 2.2rem |

### Spacing, lines, shape

- Spacing (rem): `--s1 0.2`, `--s2 0.4`, `--s3 0.6`, `--s4 0.8`, `--s5 1.2`, `--s6 1.6`, `--s7 2.4`.
  Page margin `--s6`, grid gutter `--s5`.
- Hairline `1px solid var(--line)`. Card edge `1px solid var(--edge)`. Rig stripe 3 px. Bars: two 3 px bars
  with a 2 px gap (`--bar`). Map line 0.2rem.
- **Cut corners** instead of radii: cards clip the top-right corner (`--cut: 0.9rem`) with
  `clip-path: polygon(...)`. Tabs and badges are parallelograms (`--slant: 0.55rem`). Dots stay round.

### Motion

- Data: 150–250 ms ease-out, opacity only; bars may ease width over 120 ms. Timing colours switch instantly.
- Transitions between views: one ~400 ms wipe (§3, motif 1 + speed lines). Moments: up to 4 s, see §4.
- `prefers-reduced-motion`: no transitions, moments fade only.

## 2. Motifs

Each motif is drawn by us; references are for style only.

| # | Motif | From | How we build it | Allowed | Banned |
|---|---|---|---|---|---|
| 1 | **Slanted blocks over halftone**: three bold parallelograms (thick, thin, short) running in from a corner at ~50°, over a field of small dots that fades away from the corner | Racing promo posters (style only) | One inline SVG (`<StripeBundle corner>`): filled paths in `--brand-accent`, a rotated dot `<pattern>` masked by a radial fade; on LIVE / MULTIVIEW a compact version (`<SlashMark>`) closes the header on the right | One per view, in a corner or edge that holds no data (the empty corner of the map, the attract / moment screens, the story card). View wipes. | Behind any number, name, table or map line; more than one per view; in other colours than the accent. |
| 2 | **Double slanted bar**: two parallel bars, the lower one darker, both ending in a 60° cut, a separate slanted cap after a small gap | User screenshot "slanted bars" | `<SlantBar value>`: two 3 px divs (accent / accent-2, or white / grey for throttle) with `clip-path` cut ends + a cap parallelogram | Throttle / brake, lap progress, sector progress, ERS / fuel, section dividers under titles | As decoration with no value; thicker than 4 px per bar. |
| 3 | **Diagonal light streaks**: 3–5 soft wide diagonal bands, a few % white | User screenshot "streak header", Group_58 posters | CSS `repeating-linear-gradient(115deg, …)` on a pseudo-element, masked to fade out | The top-left corner of moment cards and the attract/portrait hero | Over tables, timing or maps. |
| 4 | **Barcode meter**: a row of thin vertical ticks, lit ticks white, the rest `--line-strong`; ticks get taller toward the top end | User screenshot "broadcast card" (speed meter) | `<Barcode value max ticks>`: SVG rects; lit count rounded, no animation between ticks | Speed (instead of a round dial), revs, session timer, record "gap" meter | Any round dial or arc gauge. |
| 5 | **Wide display numerals + angled tabs + cut-corner cards + avatar slot** | Broadcast card ("308 KM/H", "LAP 15/27 \| ATTACK"), Group_58 driver card ("112 POINTS") | Display type token; `<Tab>` parallelogram with a white half and an accent half; cut-corner `.card`; `<Avatar>` shows the staff photo or the driver's initials on `--panel-2` | Speed, lap time and gaps on cards; "LAP 4 \| PUSH", "P1 \| RECORD" tabs; driver cards | Real photos of anyone who didn't consent; team or sponsor wording on tabs. |
| 6 | **Kinetic wide type**: huge wide uppercase words in rows, alternating filled and outlined, sliding sideways | Group_58 ("HAMMER TIME" rows) | `<KineticType words>`: Saira 125 % / 900, rows alternate `fill` and `-webkit-text-stroke`, CSS translate animation | View wipes (one word: the next view's name), record-broken and now-driving moments, attract mode | Anywhere data is shown at the same time; longer than the moment. |
| 7 | **Layout models**: timing tower, driver card, track card | Group_58 (race tower "LAP 36/52", "LEWIS HAMILTON 112 POINTS" card, circuit cards with length and lap record) | Leaderboard = tower (tab head with lap / title, rows: pos · stripe · name · time · gap · compound letter). Driver card = avatar left, small label, name over two lines, wide number right. Track card = map well, length in wide numerals bottom-right, name, 3-stat row, record sub-card | Leaderboards, onboard / moments driver cards, the race view's track header and the attract screen | Team logos in tower rows (we use the rig stripe), "points" from a championship we don't run. |
| 8 | **Kerb strip**: short alternating accent / white blocks | Ours (racing accent asked for in the brief) | 6 px tall `repeating-linear-gradient` strip | Top edge of the header, under view titles, moment cards | Behind data; taller than 8 px. |
| 9 | **Chequered edge**: 2 rows of small squares on one edge | Ours | `repeating-conic-gradient` 2 rows × 6 px | The P1 / record card only | Anywhere else. |

## 3. Layout

- **12-column grid, 24 px gutters and margins** (`--gutter`); every panel edge sits on a column line.
- **Fewer boxes**: sections are separated by space and hairlines. Only rig cards (and MULTIVIEW tiles, which
  are rig cards) are boxed.
- **One stripe motif per page**, never under data, nothing decorative in the map area. On LIVE and
  MULTIVIEW that motif is the slash mark closing the header on the right.
- **Header** (2.6rem, black): cafe name left, link state and clock right, slash mark at the right edge. No view tabs (pages are
  switched from `/staff` or keys 1 / 2), no track (it is in the map corner), no warnings (staff only).
- Motion: car dots, the steering wheel and pedal bars are interpolated at display rate (60 fps) between the
  15 Hz frames; numerals are tabular with fixed widths so nothing beside them moves.

## 4. Components

**Driver name**: 3 px rig stripe, name in Saira 112 % / 700 uppercase, rig name below in `--text-2`.

**Timing values**: lap time, S1–S3, last, best, gap. Label above. White unless rated: purple (fastest today),
green (own best), yellow (slower). Placeholders `--text-3`. Invalid lap: the time dims to `--text-2` and a
small grey "Invalid" tag sits by the lap number (the numerals stay readable).

**Delta**: the current lap against the driver's own best at the same lap distance, hero numerals, two
decimals, green ahead / red behind, a dash until the driver has a full lap the page saw.

**Steering wheel**: our own formula-style wheel (wide body, two grips, centre screen, three buttons, LED
slots each side), light grey with the cut-outs showing the page. It turns with the input (steer x
`steering_rotation_deg` / 2) about its centre; the screen shows the gear, the LEDs light green / yellow / red
/ purple with the car's rev lights, a rig-colour mark sits on top, the angle in degrees under it.

**Pedal bars**: two thin (8 px) vertical bars, throttle green and brake red, filling from the bottom.

**Tyre blocks**: 2 x 2 blocks (FL FR / RL RR), the fill is the surface-temperature band, the number the
pressure (psi).

**Mini-sectors**: 24 per lap (8 per sector), worked out in the dashboard from distance and time. Short 3 px
lines under the sector times; done ones purple / green / yellow, the rest `--line-strong`.

**Speed and gear**: display numerals, `KM/H` unit label between them.

**Track map** (broadcast style): a thick band (0.55rem) on a black casing, neutral grey; each of 24
mini-sectors painted in the colour of the rig with the fastest time through it (clean laps, valid or not);
LOW / MEDIUM / HIGH SPEED labels off the track at the corners (from a traced lap's speed); sector ticks with
S2 / S3; start/finish a white tick; car dots with name labels on thin leader lines, placed clear of the corner
labels. Mini maps (MULTIVIEW) show a thinner band, one car, no labels.

**Numerals**: speed, gear, delta and lap time use the `--font-num` token (Saira 125 % / 800 by default), so a
font the cafe licenses can be dropped in. Only fonts we may bundle (SIL OFL or bought for the venue) go in.

**Leaderboard (tower)**: tab head with the period and track; rows: pos · stripe · name · lap time · gap ·
class (PRO / OPEN); hairlines; P1's time purple and the P1 row gets the chequered edge.

**Moments** (full screen, over the current view, then back): kinetic type in, card, out. Now driving 4 s;
record broken 6 s; podium 10 s; battle pop-up 5 s as a lower-third card (not full screen).

## 5. TV pages

Two pages. Staff switch them on `/staff` (or keys `1` / `2` on the TV PC); nothing rotates while anyone
drives. Rigs without data are left off the TV.

| Page | Layout (12 columns) |
|---|---|
| **LIVE** (default) | Map, columns 1-8 (track name, length and today's record in the top-left corner only). Rig cards, columns 9-12, one per active rig: name, lap, lap time, delta, speed + gear, wheel, pedal bars, tyre blocks; large (1-2 rigs), tall (3), compact (4-6). Bottom strip (216 px, all 12 columns): the selected rig's name (cols 1-2), pedal trace over 10 s (cols 3-6), speed this lap vs best by distance with the gap shaded (cols 7-12). The selected rig is the one on the fastest lap (best + live delta) unless staff pinned one; it changes at most every 8 s. |
| **MULTIVIEW** | One tile per active rig: 1 full, 2 side by side, 3-4 in 2 x 2, 5-6 in 3 x 2. Tile: name, lap time, delta; speed + gear, wheel and pedals; a mini map with only that car. |

Also on the TV: **attract mode** (welcome and leaderboard, after 60 s with nobody driving, back to the page
when a car drives), **head to head** and the **team board** (put over the page from `/staff`), and the
**moments** (now driving, record, podium, battle), which play over the page and never change it.

Not on the TV (still in the feed): fuel, ERS, g-force, damage, brake temperatures, tyre wear and inner
temperatures, slides / saves, lap-share statistics, IP addresses and technical warnings.
