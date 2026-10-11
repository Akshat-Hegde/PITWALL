# TV dashboard design (v2)

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
| `--bg` | `#0C0D11` | Page background. Flat; only the stripe-bundle motif may sit on it, never behind data. |
| `--panel` | `#14151B` | Cards (cut-corner). One level only: no card inside a card. |
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

Rules:
- Purple / green / yellow mean timing and are only ever a text colour or a thin line. Never a fill.
- Rig colours (desaturated ~25 % by the dashboard) mark driver identity only: the 3 px name stripe, the map
  dot and its leader line, chart lines. Never a panel tint or a value colour.
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
- `1rem` = 1.85 % of the screen height (20 px at 1080p, 40 px at 4K); in portrait, 1.05 % (20 px at 1920 px).

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
| 1 | **Stripe bundle**: 5 parallel thin lines that run in from a screen edge, bend 45° with a rounded corner and fade out at one end | Group_58 (corner bundles on every page, behind the posters) | One inline SVG (`<StripeBundle corner>`): 5 paths, 6 px apart at 1080p, `--brand-accent` at 22 % opacity, a linear-gradient mask for the fade | One per view, in a corner or edge that holds no data (the empty corner of the map, the attract / moment screens, the story card). View wipes. | Behind any number, name, table or map line; more than one per view; in other colours than the accent. |
| 2 | **Double slanted bar**: two parallel bars, the lower one darker, both ending in a 60° cut, a separate slanted cap after a small gap | User screenshot "slanted bars" | `<SlantBar value>`: two 3 px divs (accent / accent-2, or white / grey for throttle) with `clip-path` cut ends + a cap parallelogram | Throttle / brake, lap progress, sector progress, ERS / fuel, section dividers under titles | As decoration with no value; thicker than 4 px per bar. |
| 3 | **Diagonal light streaks**: 3–5 soft wide diagonal bands, a few % white | User screenshot "streak header", Group_58 posters | CSS `repeating-linear-gradient(115deg, …)` on a pseudo-element, masked to fade out | The header bar, the top-left corner of moment cards and the attract/portrait hero | Over tables, timing or maps. |
| 4 | **Barcode meter**: a row of thin vertical ticks, lit ticks white, the rest `--line-strong`; ticks get taller toward the top end | User screenshot "broadcast card" (speed meter) | `<Barcode value max ticks>`: SVG rects; lit count rounded, no animation between ticks | Speed (instead of a round dial), revs, session timer, record "gap" meter | Any round dial or arc gauge. |
| 5 | **Wide display numerals + angled tabs + cut-corner cards + avatar slot** | Broadcast card ("308 KM/H", "LAP 15/27 \| ATTACK"), Group_58 driver card ("112 POINTS") | Display type token; `<Tab>` parallelogram with a white half and an accent half; cut-corner `.card`; `<Avatar>` shows the staff photo or the driver's initials on `--panel-2` | Speed, lap time and gaps on cards; "LAP 4 \| PUSH", "P1 \| RECORD" tabs; driver cards | Real photos of anyone who didn't consent; team or sponsor wording on tabs. |
| 6 | **Kinetic wide type**: huge wide uppercase words in rows, alternating filled and outlined, sliding sideways | Group_58 ("HAMMER TIME" rows) | `<KineticType words>`: Saira 125 % / 900, rows alternate `fill` and `-webkit-text-stroke`, CSS translate animation | View wipes (one word: the next view's name), record-broken and now-driving moments, attract mode | Anywhere data is shown at the same time; longer than the moment. |
| 7 | **Layout models**: timing tower, driver card, track card | Group_58 (race tower "LAP 36/52", "LEWIS HAMILTON 112 POINTS" card, circuit cards with length and lap record) | Leaderboard = tower (tab head with lap / title, rows: pos · stripe · name · time · gap · compound letter). Driver card = avatar left, small label, name over two lines, wide number right. Track card = map well, length in wide numerals bottom-right, name, 3-stat row, record sub-card | Leaderboards, onboard / moments driver cards, the race view's track header and the attract screen | Team logos in tower rows (we use the rig stripe), "points" from a championship we don't run. |
| 8 | **Kerb strip**: short alternating accent / white blocks | Ours (racing accent asked for in the brief) | 6 px tall `repeating-linear-gradient` strip | Top edge of the header, under view titles, moment cards | Behind data; taller than 8 px. |
| 9 | **Chequered edge**: 2 rows of small squares on one edge | Ours | `repeating-conic-gradient` 2 rows × 6 px | The P1 / record card only | Anywhere else. |

## 3. Layout

- Strict grid: page margin `--s6`, gutter `--s5`. Sections are separated by space and hairlines; cards are
  used for things that are objects (a driver, a track, a moment), not for every group.
- **Header** (2.6rem): kerb strip on top edge, cafe name and mark left, session · track centre, views ·
  link · clock right, faint streaks (motif 3).
- 1920×1080 and 3840×2160 with the same layout (rem scales); 1–10 rigs. Portrait 1080×1920 at `/portrait`.

## 4. Components

**Driver name**: 3 px rig stripe, name in Saira 112 % / 700 uppercase, rig name below in `--text-2`.

**Timing values**: lap time, S1–S3, last, best, gap. Label above. White unless rated: purple (fastest today),
green (own best), yellow (slower, on gaps and mini-sectors). Placeholders `--text-3`. Invalid lap: struck
through in `--text-3`.

**Mini-sectors**: 24 per lap (8 per sector), worked out in the dashboard from distance and time. Short 3 px
lines under the sector times; done ones purple / green / yellow, the rest `--line-strong`.

**Speed**: barcode meter (motif 4) with the speed in display numerals, `KM/H` unit, gear beside it.

**Throttle / brake**: double slanted bars (motif 2), throttle white / grey, brake accent / accent-2.

**Tyre**: compound letter (S M H I W) in the compound colour + age; on onboard: four tyre blocks with
temperature as coloured text, wear, pressure, brake temperature.

**Track map**: neutral 0.2rem line, no glow or casing, coloured only by meaning; small dots with name labels
off the track on thin leader lines; start/finish a short white tick.

**Leaderboard (tower)**: tab head with the period and track; rows: pos · stripe · name · lap time · gap ·
class (PRO / OPEN); hairlines; P1's time purple and the P1 row gets the chequered edge.

**Moments** (full screen, over the current view, then back): kinetic type in, card, out. Now driving 4 s;
record broken 6 s; podium 10 s; battle pop-up 5 s as a lower-third card (not full screen).

## 5. Views

| View | Shows | Key |
|---|---|---|
| **Race** | Track header card, map (lead car's mini-sectors), battle line, timing (cards ≤4 rigs, tower 5–10), bottom strip (today's top 3, speed trap, conditions), session timers and "Next up". | `1` |
| **Leaderboard** | Pro and Open × today / week / all time towers for the track, 10 rows, paging. | `2` |
| **Head to head** | Two drivers left / right, map coloured by who's faster per mini-sector, LOW / MEDIUM / HIGH SPEED labels, mirrored lap-share bars, speed traces. | `3` |
| **Onboard** | Per driving rig (two per page): barcode speed, revs, pedals, steering, g-circle, tyres, fuel, ERS, DRS, damage, slides / saves. | `4` |
| **Attract** | Cafe branding, today's top 10, record holder, current challenge. Auto when nobody drives. | `5` |

`?view=race|board|analysis|onboard|attract` fixes the view; `0` returns to auto rotation.
