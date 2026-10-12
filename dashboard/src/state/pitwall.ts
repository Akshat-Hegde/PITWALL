import type { LeaderboardEntry, LiveLap, StoryLap } from "../schema";
import type { DistTrace } from "./live";

// Model for the Pitwall LIVE page (design: "Pitwall TV", Turn 2): the reference laps the focus driver is
// measured against, the predicted lap and position, the tower rows with the "on this lap" ghost row, the
// rotating headlines and the session-story chart. Pure functions, so the page stays a thin renderer.

export const MAX_TOWER_ROWS = 8;

// ---- reference laps ---------------------------------------------------------------------------------

/** A lap to race against: lap time at any distance, and distance at any lap time (the ghost on the map). */
export interface RefLap {
  kind: "record" | "pb";
  lapMs: number;
  length: number;
  sectorsMs: [number, number, number] | null;
  timeAt(d: number): number;
  distAt(t: number): number;
}

function interp(xs: readonly number[], ys: readonly number[], x: number): number {
  const n = xs.length;
  if (x <= xs[0]!) return ys[0]!;
  if (x >= xs[n - 1]!) return ys[n - 1]!;
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid]! <= x) lo = mid;
    else hi = mid;
  }
  const k = xs[hi]! > xs[lo]! ? (x - xs[lo]!) / (xs[hi]! - xs[lo]!) : 0;
  return ys[lo]! + (ys[hi]! - ys[lo]!) * k;
}

/** A reference lap from its 24 mini-sector times (the hub's record_minis). */
export function refFromMinis(kind: RefLap["kind"], minis: readonly number[], length: number,
                             sectorsMs: [number, number, number] | null = null): RefLap | null {
  if (!minis.length || length <= 0 || minis.some((m) => !(m > 0))) return null;
  const d = [0];
  const t = [0];
  minis.forEach((ms, i) => {
    d.push(((i + 1) / minis.length) * length);
    t.push(t[i]! + ms);
  });
  return { kind, lapMs: t[t.length - 1]!, length, sectorsMs, timeAt: (x) => interp(d, t, x), distAt: (x) => interp(t, d, x) };
}

/** A reference lap from a full (distance, time) trace this page saw (the driver's own best). */
export function refFromTrace(kind: RefLap["kind"], trace: DistTrace, length: number, lapMs: number,
                             sectorsMs: [number, number, number] | null = null): RefLap | null {
  if (trace.d.length < 2) return null;
  return { kind, lapMs, length, sectorsMs, timeAt: (x) => interp(trace.d, trace.t, x), distAt: (x) => interp(trace.t, trace.d, x) };
}

/** Current lap time minus the reference at the same distance; null before the line or when they disagree. */
export function deltaTo(ref: RefLap | null, lap: LiveLap | null | undefined): number | null {
  if (!ref || !lap || lap.distance_m < 0) return null;
  const delta = lap.current_ms - ref.timeAt(Math.min(lap.distance_m, ref.length));
  return Math.abs(delta) > Math.min(60_000, ref.lapMs * 0.25) ? null : Math.round(delta);
}

// ---- tower ------------------------------------------------------------------------------------------

export type Rating = "p" | "g" | "y" | "n";

export interface TowerRow {
  key: string;
  pos: string;
  ghost: boolean;
  leader: boolean;
  name: string;
  colour: string | null;
  lapMs: number;
  gapMs: number;
  sectors: Rating[];
  sub?: string;
}

/** Sector colours on the board: purple fastest on the board, green quicker than the median, else yellow. */
function boardSectorRatings(entries: readonly LeaderboardEntry[]): (e: LeaderboardEntry) => Rating[] {
  const per = [0, 1, 2].map((i) => entries.map((e) => e.sectors_ms?.[i]).filter((v): v is number => v != null).sort((a, b) => a - b));
  return (e) => [0, 1, 2].map((i) => {
    const v = e.sectors_ms?.[i];
    const list = per[i]!;
    if (v == null || !list.length) return "n";
    if (v <= list[0]!) return "p";
    return v <= list[Math.floor((list.length - 1) / 2)]! ? "g" : "y";
  });
}

export function driverKey(name: string | null | undefined, rigId: string): string {
  return name ? `d:${name.toLowerCase()}` : `r:${rigId}`;
}

/**
 * Today's board as tower rows, with the focus driver's "on this lap" ghost row slotted in where the predicted
 * lap would place it. colourOf: the rig colour for drivers on an active rig, else null (shown grey).
 */
export function towerRows(entries: readonly LeaderboardEntry[], colourOf: (e: LeaderboardEntry) => string | null,
                          ghost: { name: string; colour: string; predMs: number; sectors: Rating[] } | null,
                          max = MAX_TOWER_ROWS): TowerRow[] {
  const shown = entries.slice(0, ghost ? max : max + 1);
  const rate = boardSectorRatings(entries);
  const leader = shown[0]?.lap_ms ?? 0;
  const rows: TowerRow[] = shown.map((e, i) => ({
    key: driverKey(e.driver, e.rig_id), pos: String(i + 1), ghost: false, leader: i === 0, name: (e.driver ?? e.rig_name).toUpperCase(),
    colour: colourOf(e), lapMs: e.lap_ms, gapMs: e.lap_ms - leader, sectors: rate(e),
  }));
  if (ghost) {
    const at = shown.filter((e) => e.lap_ms < ghost.predMs).length;
    rows.splice(at, 0, {
      key: "ghost", pos: `P${at + 1}`, ghost: true, leader: false, name: ghost.name.toUpperCase(), colour: ghost.colour,
      lapMs: ghost.predMs, gapMs: ghost.predMs - (leader || ghost.predMs), sectors: ghost.sectors, sub: `P${at + 1} ON THIS LAP`,
    });
  }
  return rows;
}

/** Position the predicted lap would take on today's board (1-based). */
export function predictedPosition(entries: readonly LeaderboardEntry[], predMs: number): number {
  return entries.filter((e) => e.lap_ms < predMs).length + 1;
}

// ---- headlines --------------------------------------------------------------------------------------

export type Tone = "w" | "g" | "r" | "p";
export type Headline = [string, Tone][];

export function fmtLap(ms: number): string {
  const m = Math.floor(ms / 60000);
  const s = ((ms % 60000) / 1000).toFixed(3).padStart(6, "0");
  return m ? `${m}:${s}` : (ms / 1000).toFixed(3);
}

/** Predicted lap to hundredths ("1:27.09"). */
export function fmtPred(ms: number): string {
  return fmtLap(ms).slice(0, -1);
}

const secs = (ms: number) => `${(Math.abs(ms) / 1000).toFixed(2)} s`;

export interface HeadlineInput {
  focus: { name: string; delta: number | null; sectorsDone: number; vsRecord: boolean; predMs: number | null; predPos: number | null } | null;
  chaser: { name: string; delta: number } | null;
  record: { holder: string; lapMs: number } | null;
  focusBestMs: number | null;
}

export function headlines(h: HeadlineInput): Headline[] {
  const out: Headline[] = [];
  const f = h.focus;
  if (f && f.delta != null && f.sectorsDone > 0) {
    const vs = f.vsRecord ? "TODAY'S RECORD" : "THEIR BEST";
    out.push([[`${f.name} IS `, "w"], [`${secs(f.delta)} ${f.delta <= 0 ? "UP" : "DOWN"}`, f.delta <= 0 ? "g" : "r"],
      [` ON ${vs} AFTER SECTOR ${f.sectorsDone}`, "w"]]);
  }
  if (f && f.predMs != null) {
    const newRecord = h.record != null && f.predMs < h.record.lapMs;
    out.push(newRecord
      ? [[`${f.name} IS ON FOR `, "w"], [fmtPred(f.predMs), "p"], [" — THAT WOULD BE A NEW RECORD", "w"]]
      : [[`${f.name} IS ON FOR `, "w"], [fmtPred(f.predMs), "g"], [` — THAT'S P${f.predPos ?? "?"} ON TODAY'S BOARD`, "w"]]);
  }
  if (h.chaser) {
    const c = h.chaser;
    out.push(c.delta > 0
      ? [[`${c.name} CHASING THEIR BEST — `, "w"], [secs(c.delta), "r"], [" TO FIND", "w"]]
      : [[`${c.name} IS `, "w"], [`${secs(c.delta)} UP`, "g"], [" ON THEIR BEST", "w"]]);
  }
  if (h.record) {
    const gap = h.focusBestMs != null && h.focusBestMs > h.record.lapMs ? h.focusBestMs - h.record.lapMs : null;
    out.push(gap != null
      ? [[`TODAY'S RECORD: ${h.record.holder} `, "w"], [fmtLap(h.record.lapMs), "p"], [` — ${secs(gap)} STILL TO FIND`, "w"]]
      : [[`TODAY'S RECORD: ${h.record.holder} `, "w"], [fmtLap(h.record.lapMs), "p"]]);
  }
  if (!out.length) out.push([["GRAB A SEAT. SET A LAP. BEAT THE BOARD.", "w"]]);
  return out;
}

/** Headline font size: as big as fits the space (design: min(62, 1140 / (chars x 0.46))). */
export function headlineSize(h: Headline): number {
  const len = h.reduce((a, [t]) => a + t.length, 0);
  return Math.max(28, Math.min(62, Math.floor(1140 / (len * 0.46))));
}

// ---- session story chart ----------------------------------------------------------------------------

export const CHART = { W: 1208, H: 196, L: 60, R: 1098, T: 10, B: 166 } as const;

export interface ChartRef {
  ms: number;
  label: string;
  colour: string;
}

export interface StoryChart {
  lines: { d: string; colour: string }[];
  dots: { x: number; y: number; r: number; fill: string; stroke: string }[];
  /** right: the label ends at x (lines that reach NOW are labelled on their left, clear of the ref labels). */
  names: { x: number; y: number; text: string; colour: string; right: boolean }[];
  yTicks: { y: number; label: string }[];
  xTicks: { x: number; label: string }[];
  refs: { y: number; label: string; colour: string }[];
  nowX: number;
}

const BG = "#0B0C0F";

/**
 * Lap times over clock time for each driver in the window: a line per driver, a bigger white-ringed dot on
 * their best valid lap, hollow dots on invalid laps; dashed reference lines (record, PB); NOW at the right.
 */
export function storyChart(laps: readonly StoryLap[], now: number, colourOf: (l: StoryLap) => string,
                           refs: readonly ChartRef[], onlyKey: string | null = null, maxDrivers = 8): StoryChart {
  const { L, R, T, B } = CHART;
  // Only laps inside the window: older ones would sit (and be labelled) left of the chart.
  const shown = laps.filter((l) => !l.out_lap && l.completed_at >= now - 47 * 60_000
                                && (onlyKey == null || driverKey(l.driver, l.rig_id) === onlyKey));
  const x1 = now + 20_000;
  const first = shown.length ? shown[0]!.completed_at - 60_000 : now - 10 * 60_000;
  const x0 = Math.min(Math.max(now - 47 * 60_000, first), x1 - 10 * 60_000);
  const valid = shown.filter((l) => l.valid).map((l) => l.lap_ms);
  if (!valid.length) valid.push(...shown.map((l) => l.lap_ms));
  const fastest = Math.min(...valid, ...refs.map((r) => r.ms), Infinity);
  const yT = Number.isFinite(fastest) ? Math.floor(fastest / 1000) : 60;
  const yB = yT + 8;
  const X = (t: number) => L + ((t - x0) / (x1 - x0)) * (R - L);
  const Y = (ms: number) => T + ((Math.max(yT, Math.min(ms / 1000, yB)) - yT) / (yB - yT)) * (B - T);

  const groups = new Map<string, StoryLap[]>();
  for (const l of shown) {
    const k = driverKey(l.driver, l.rig_id);
    groups.set(k, [...(groups.get(k) ?? []), l]);
  }
  const recent = [...groups.entries()].sort((a, b) => b[1].at(-1)!.completed_at - a[1].at(-1)!.completed_at).slice(0, maxDrivers);
  const lines: StoryChart["lines"] = [];
  const dots: StoryChart["dots"] = [];
  const names: StoryChart["names"] = [];
  for (const [, group] of recent) {
    const colour = colourOf(group.at(-1)!);
    const best = Math.min(...group.filter((l) => l.valid).map((l) => l.lap_ms));
    const pts = group.map((l) => ({ x: X(l.completed_at), y: Y(l.lap_ms), l }));
    lines.push({ d: "M" + pts.map((p) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" L"), colour });
    for (const p of pts) {
      if (p.l.valid && p.l.lap_ms === best) dots.push({ x: p.x, y: p.y, r: 7, fill: colour, stroke: "#fff" });
      else dots.push({ x: p.x, y: p.y, r: 4, fill: p.l.valid ? colour : BG, stroke: colour });
    }
    const last = pts.at(-1)!;
    const nearNow = last.x > R - 90;
    names.push({ x: nearNow ? last.x - 12 : last.x + 10, y: last.y, text: (last.l.driver ?? last.l.rig_id).toUpperCase(), colour, right: nearNow });
  }
  // Name labels at the line ends: nudge apart so they never sit on top of each other.
  names.sort((a, b) => a.y - b.y);
  for (let i = 1; i < names.length; i++) names[i]!.y = Math.max(names[i]!.y, names[i - 1]!.y + 15);
  const yTicks = [];
  for (let s = yT; s <= yB; s += 2) yTicks.push({ y: Y(s * 1000), label: `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` });
  const xTicks = [];
  const step = 10 * 60_000;
  for (let t = Math.ceil(x0 / step) * step; t <= x1 - 3 * 60_000; t += step) {
    const d = new Date(t);
    xTicks.push({ x: X(t), label: `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` });
  }
  return {
    lines, dots, names, yTicks, xTicks, nowX: X(now),
    refs: refs.map((r) => ({ y: Y(r.ms), label: r.label, colour: r.colour })),
  };
}
