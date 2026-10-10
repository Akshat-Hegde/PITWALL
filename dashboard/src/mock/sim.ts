// Mock hub: simulates rigs on a synthetic track and emits messages that follow docs/WS_SCHEMA.md.
// Deterministic for a given seed, so tests can run it step by step without timers.

import {
  SCHEMA_VERSION,
  type BestLap,
  type Comparison,
  type HubMessage,
  type HubStatus,
  type LapRecord,
  type Leaderboard,
  type LeaderboardEntry,
  type RigFrame,
  type RigInfo,
  type SectorRating,
  type SectorTime,
  type Sectors,
  type SessionInfo,
  type SnapshotMessage,
  type TrackOutline,
  type Tyre,
} from "../schema";
import { buildTrack, referenceLapMs, sampleTrack, type MockTrack } from "./track";

export interface MockOptions {
  seed: number;
  /** Send the outline only after the first valid lap (as a real hub would generate it). */
  outlineLate: boolean;
  /** Second rig reports a different packet format. */
  formatMismatch: boolean;
  recorder: "off" | "recording" | "low" | "stopped";
  /** Include a configured rig that never sends data. */
  offlineRig: boolean;
  frameHz: number;
  /** Earlier drivers already on the leaderboard (tests the layout with many entries). */
  pastDrivers: number;
  /** Rigs that drive (1-10). */
  rigs: number;
  /** Every rig stays in the menu: nobody drives (attract mode). */
  idle: boolean;
}

export const DEFAULT_MOCK_OPTIONS: MockOptions = {
  seed: 7,
  outlineLate: false,
  formatMismatch: false,
  recorder: "off",
  offlineRig: true,
  pastDrivers: 0,
  rigs: 2,
  idle: false,
  frameHz: 15,
};

const RIG_DRIVERS = ["Apex_Hunter", "LateBraker77", "Sofia_K", "TurboTom", "Mika H", "DRS_Daisy", "Kerb Crusher",
  "Rae", "Big Ben", "Quali Queen"];
const RIG_COLOURS = ["#36C5F0", "#FF8A3D", "#F15BB5", "#5B8CFF", "#2EC4B6", "#FF6B6B", "#C0C9D2", "#FFB3C6",
  "#8D99AE", "#D4A373"];
const RIG_PACES = [0.995, 0.982, 0.99, 0.986, 0.978, 0.992, 0.975, 0.984, 0.98, 0.988];

const TRACK_KEY = "F1:900";
const TRACK_NAME = "Practice circuit";
const MENU_MS = 6000; // second rig waits in the menu this long
const TRACE_STEP_M = 20;
const PAST_DRIVERS = [
  "Maya R", "Kofi_GT", "J. Lindqvist", "SundayDriver", "Priya S", "Tom from Accounts", "NightShift_Nico",
  "Hana K", "Diego M", "BoxBoxBox", "Ollie P", "Rosa V", "Arjun_92", "Leni", "Sam W",
];

interface RigSpec {
  info: RigInfo;
  driver: string | null;
  pace: number; // fraction of the reference speed
  menuUntilMs: number;
  offline: boolean;
}

interface Trace {
  d: number[]; // distance (m)
  t: number[]; // lap time at that distance (ms)
}

interface RigSim {
  spec: RigSpec;
  sessionId: string;
  distance: number; // into the current lap; negative before the line
  lapNumber: number;
  lapMs: number;
  lapPace: number;
  valid: boolean;
  invalidAtM: number | null;
  sectorSplits: number[]; // ms at the end of each completed sector this lap
  sectors: Sectors;
  lastSectors: Sectors | null;
  lastMs: number | null;
  best: BestLap | null;
  bestTrace: Trace | null;
  trace: Trace;
  bestSectors: [number, number, number];
  tyreAge: number;
  speed: number; // m/s, smoothed
  prevSpeed: number;
}

class Rng {
  constructor(private s: number) {}
  next(): number {
    // mulberry32
    this.s = (this.s + 0x6d2b79f5) | 0;
    let t = this.s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
}

const GEAR_TOP_KPH = [80, 125, 160, 195, 230, 265, 295, 345];

function gearFor(kph: number): number {
  const g = GEAR_TOP_KPH.findIndex((top) => kph < top);
  return g < 0 ? 8 : g + 1;
}

function rpmFor(kph: number, gear: number): number {
  const lo = gear <= 1 ? 0 : GEAR_TOP_KPH[gear - 2]!;
  const hi = GEAR_TOP_KPH[gear - 1]!;
  return Math.round(7000 + 5000 * Math.min(1, Math.max(0, (kph - lo) / (hi - lo))));
}

function traceTimeAt(trace: Trace, d: number): number | null {
  const n = trace.d.length;
  if (n < 2 || d < trace.d[0]! || d > trace.d[n - 1]!) return null;
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (trace.d[mid]! <= d) lo = mid;
    else hi = mid;
  }
  const k = (d - trace.d[lo]!) / (trace.d[hi]! - trace.d[lo]! || 1);
  return trace.t[lo]! + (trace.t[hi]! - trace.t[lo]!) * k;
}

export class MockHub {
  readonly track: MockTrack;
  private readonly rng: Rng;
  private readonly rigs: RigSim[];
  private seq = 0;
  private simMs = 0;
  private sinceStatus = 0;
  private outlineSent: boolean;
  private sessionBestSectors: [number, number, number] = [Infinity, Infinity, Infinity];
  private leaderboard: Leaderboard | null = null;
  private readonly recentLaps: LapRecord[] = [];
  private readonly pastEntries: LeaderboardEntry[] = [];

  constructor(readonly options: MockOptions = DEFAULT_MOCK_OPTIONS, private readonly clock: () => number = Date.now) {
    this.track = buildTrack();
    this.rng = new Rng(options.seed);
    this.outlineSent = !options.outlineLate;
    const driving = Math.max(1, Math.min(10, options.rigs));
    const specs: RigSpec[] = [];
    for (let i = 0; i < driving; i++) {
      const n = i + 1;
      specs.push({
        info: rigInfo(`rig-${n}`, `Rig ${n}`, RIG_COLOURS[i]!, `192.168.1.${20 + n}`,
          options.formatMismatch && n === 2 ? "2026" : "2025"),
        driver: RIG_DRIVERS[i]!,
        pace: RIG_PACES[i]!,
        // Rig 2 starts in the menu for a while; the rest join a little apart.
        menuUntilMs: options.idle ? Infinity : n === 1 ? 0 : n === 2 ? MENU_MS : i * 1500,
        offline: false,
      });
    }
    if (options.offlineRig) {
      const n = driving + 1;
      specs.push({
        info: rigInfo(`rig-${n}`, `Rig ${n}`, RIG_COLOURS[driving % RIG_COLOURS.length]!, `192.168.1.${20 + n}`, null),
        driver: null,
        pace: 1,
        menuUntilMs: Infinity,
        offline: true,
      });
    }
    this.rigs = specs.map((spec, i) => this.newRigSim(spec, i));
    const reference = referenceLapMs(this.track);
    for (let i = 0; i < options.pastDrivers; i++) {
      const rig = specs[i % 2]!.info;
      const lapMs = Math.round(reference / 0.99 + 400 + this.rng.next() * 4500);
      const s1 = Math.round(lapMs * (0.32 + this.rng.next() * 0.01));
      const s2 = Math.round(lapMs * 0.37);
      this.pastEntries.push({
        rank: 0, rig_id: rig.rig_id, rig_name: rig.name, driver: PAST_DRIVERS[i % PAST_DRIVERS.length]!,
        lap_ms: lapMs, sectors_ms: [s1, s2, lapMs - s1 - s2], gap_ms: 0,
        tyre: { compound: "soft", label: "C3", age_laps: 1 + (i % 4) }, lap_number: 2 + (i % 5),
        set_at: this.clock() - (i + 1) * 600_000,
      });
    }
    if (this.pastEntries.length > 0) this.leaderboard = this.buildLeaderboard();
  }

  private newRigSim(spec: RigSpec, i: number): RigSim {
    return {
      spec,
      sessionId: `mock-session-${i + 1}`,
      distance: -120 - 60 * i, // start on the grid, before the line
      lapNumber: 1,
      lapMs: 0,
      lapPace: spec.pace,
      valid: true,
      invalidAtM: null,
      sectorSplits: [],
      sectors: [null, null, null],
      lastSectors: null,
      lastMs: null,
      best: null,
      bestTrace: null,
      trace: { d: [], t: [] },
      bestSectors: [Infinity, Infinity, Infinity],
      tyreAge: 0,
      speed: 30,
      prevSpeed: 30,
    };
  }

  private envelope<T extends HubMessage["type"]>(type: T) {
    return { v: SCHEMA_VERSION, type, seq: this.seq++, ts: this.clock() };
  }

  snapshot(): SnapshotMessage {
    this.seq = 0;
    return {
      ...this.envelope("snapshot"),
      hub: { version: "mock", games: ["F1"], frame_hz: this.options.frameHz, udp_port: 20777,
             lan_address: "192.168.1.10" },
      cafe: { name: "Sim Racing Cafe", branding: {} },
      status: this.status(),
      rigs: this.rigs.map((r) => r.spec.info),
      frame: { rigs: this.rigs.map((r) => this.frame(r)), comparison: this.comparison() },
      outlines: this.outlineSent ? [this.outline()] : [],
      leaderboards: this.leaderboard ? this.periodBoards(this.leaderboard) : [],
      recent_laps: [...this.recentLaps],
    };
  }

  /** Advance the simulation by dtMs and return the messages a hub would send for this tick. */
  step(dtMs: number): HubMessage[] {
    const out: HubMessage[] = [];
    this.simMs += dtMs;
    for (const rig of this.rigs) out.push(...this.advance(rig, dtMs));
    out.push({ ...this.envelope("frame"), rigs: this.rigs.map((r) => this.frame(r)), comparison: this.comparison() });
    this.sinceStatus += dtMs;
    if (this.sinceStatus >= 1000) {
      this.sinceStatus = 0;
      out.push({ ...this.envelope("status"), status: this.status() });
    }
    return out;
  }

  private driving(rig: RigSim): boolean {
    return !rig.spec.offline && this.simMs >= rig.spec.menuUntilMs;
  }

  private advance(rig: RigSim, dtMs: number): HubMessage[] {
    if (!this.driving(rig)) return [];
    const msgs: HubMessage[] = [];
    const target = sampleTrack(this.track, rig.distance).speed * rig.lapPace;
    rig.prevSpeed = rig.speed;
    rig.speed += (target - rig.speed) * Math.min(1, dtMs / 250);
    const before = rig.distance;
    rig.distance += (rig.speed * dtMs) / 1000;
    if (before >= 0 || rig.distance >= 0) rig.lapMs += before < 0 ? (rig.distance / rig.speed) * 1000 : dtMs;

    if (rig.distance >= 0) {
      if (rig.trace.d.length === 0 || rig.distance - rig.trace.d[rig.trace.d.length - 1]! >= TRACE_STEP_M) {
        rig.trace.d.push(rig.distance);
        rig.trace.t.push(rig.lapMs);
      }
      if (rig.valid && rig.invalidAtM !== null && rig.distance >= rig.invalidAtM) rig.valid = false;
      // Sector boundaries within the lap.
      const sector = rig.sectorSplits.length;
      const boundary = this.track.sectorDistances[sector + 1];
      if (sector < 2 && boundary !== undefined && rig.distance >= boundary) {
        // Splits are rounded to whole ms so the three sectors always add up to the lap time.
        const prevSplit = sector === 0 ? 0 : rig.sectorSplits[0]!;
        // Time at the exact crossing, not at the end of this tick.
        const split = Math.round(rig.lapMs - ((rig.distance - boundary) / rig.speed) * 1000);
        rig.sectorSplits.push(split);
        rig.sectors[sector] = this.rateSector(rig, sector, split - prevSplit);
      }
    }
    if (rig.distance >= this.track.length) msgs.push(...this.completeLap(rig));
    return msgs;
  }

  private rateSector(rig: RigSim, sector: number, ms: number): SectorTime {
    if (!rig.valid) return { ms, rating: null };
    let rating: SectorRating = "normal";
    if (ms < rig.bestSectors[sector]!) {
      rig.bestSectors[sector] = ms;
      rating = "personal_best";
    }
    if (ms < this.sessionBestSectors[sector]!) {
      this.sessionBestSectors[sector] = ms;
      rating = "session_best";
    }
    return { ms, rating };
  }

  private completeLap(rig: RigSim): HubMessage[] {
    const msgs: HubMessage[] = [];
    const overshoot = rig.distance - this.track.length;
    const lapMs = Math.round(rig.lapMs - (overshoot / rig.speed) * 1000);
    const s1 = rig.sectorSplits[0] ?? Math.round(lapMs / 3);
    const s2 = (rig.sectorSplits[1] ?? Math.round((2 * lapMs) / 3)) - s1;
    const s3 = lapMs - s1 - s2;
    rig.sectors[2] = this.rateSector(rig, 2, s3);
    const sectorsMs: [number, number, number] = [s1, s2, s3];

    const valid = rig.valid;
    const personalBest = valid && (rig.best === null || lapMs < rig.best.lap_ms);
    const others = this.rigs.filter((r) => r.best).map((r) => r.best!.lap_ms);
    const sessionBest = personalBest && (others.length === 0 || lapMs < Math.min(...others));
    if (personalBest) {
      rig.best = { lap_ms: lapMs, sectors_ms: sectorsMs, lap_number: rig.lapNumber, set_at: this.clock() };
      rig.bestTrace = rig.trace;
    }
    const lap: LapRecord = {
      rig_id: rig.spec.info.rig_id,
      driver: rig.spec.driver,
      track_key: TRACK_KEY,
      session_id: rig.sessionId,
      lap_number: rig.lapNumber,
      lap_ms: lapMs,
      sectors_ms: sectorsMs,
      valid,
      out_lap: false,
      tyre: this.tyre(rig),
      personal_best: personalBest,
      session_best: sessionBest,
      completed_at: this.clock(),
    };
    this.recentLaps.unshift(lap);
    this.recentLaps.splice(20);
    msgs.push({ ...this.envelope("lap_completed"), lap });
    if (personalBest) {
      this.leaderboard = this.buildLeaderboard();
      for (const board of this.periodBoards(this.leaderboard)) {
        msgs.push({ ...this.envelope("leaderboard"), leaderboard: board });
      }
    }
    if (valid && !this.outlineSent) {
      this.outlineSent = true;
      msgs.push({ ...this.envelope("track_outline"), outline: this.outline() });
    }

    // Next lap.
    rig.lastMs = lapMs;
    rig.lastSectors = rig.sectors;
    rig.sectors = [null, null, null];
    rig.sectorSplits = [];
    rig.lapNumber += 1;
    rig.tyreAge += 1;
    rig.distance = overshoot;
    rig.lapMs = (overshoot / rig.speed) * 1000;
    rig.trace = { d: [], t: [] };
    rig.lapPace = rig.spec.pace * (1 + (this.rng.next() - 0.5) * 0.012);
    rig.valid = true;
    rig.invalidAtM = this.rng.next() < 0.15 ? this.rng.next() * this.track.length : null;
    return msgs;
  }

  /** The mock has one session, so every period shows the same board. */
  private periodBoards(board: Leaderboard): Leaderboard[] {
    const today = new Date(this.clock());
    today.setHours(0, 0, 0, 0);
    const monday = new Date(today);
    monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
    return [
      { ...board, period: "today", since: today.getTime() },
      { ...board, period: "week", since: monday.getTime() },
      { ...board, period: "all_time", since: null },
    ];
  }

  private buildLeaderboard(): Leaderboard {
    const live: LeaderboardEntry[] = this.rigs
      .filter((r) => r.best)
      .map((r) => ({
        rank: 0,
        rig_id: r.spec.info.rig_id,
        rig_name: r.spec.info.name,
        driver: r.spec.driver,
        lap_ms: r.best!.lap_ms,
        sectors_ms: r.best!.sectors_ms,
        gap_ms: 0,
        tyre: this.tyre(r),
        lap_number: r.best!.lap_number,
        set_at: r.best!.set_at,
      }));
    const sorted = [...live, ...this.pastEntries].sort((a, b) => a.lap_ms - b.lap_ms);
    const leader = sorted[0]?.lap_ms ?? 0;
    return {
      track_key: TRACK_KEY,
      track_name: TRACK_NAME,
      period: "today",
      since: null,
      entries: sorted.map((e, i) => ({ ...e, rank: i + 1, gap_ms: e.lap_ms - leader })),
    };
  }

  private comparison(): Comparison | null {
    const active = this.rigs.filter((r) => this.driving(r));
    if (active.length < 2) return null;
    return {
      track_key: TRACK_KEY,
      rigs: active.map((rig) => {
        const others = active.filter((o) => o !== rig && o.best).sort((a, b) => a.best!.lap_ms - b.best!.lap_ms);
        const ref = others[0];
        let live: number | null = null;
        if (ref?.bestTrace && rig.valid && rig.distance >= 0) {
          const refT = traceTimeAt(ref.bestTrace, rig.distance);
          if (refT !== null) live = Math.round(rig.lapMs - refT);
        }
        return {
          rig_id: rig.spec.info.rig_id,
          reference_rig_id: ref ? ref.spec.info.rig_id : null,
          best_gap_ms: ref && rig.best ? rig.best.lap_ms - ref.best!.lap_ms : null,
          live_delta_ms: live,
        };
      }),
    };
  }

  private tyre(rig: RigSim): Tyre {
    return { compound: "soft", label: "C3", age_laps: rig.tyreAge };
  }

  private session(rig: RigSim): SessionInfo {
    if (rig.spec.offline) {
      return { session_id: null, track_key: null, track_name: null, track_length_m: null, session_type: null };
    }
    return {
      session_id: rig.sessionId,
      track_key: TRACK_KEY,
      track_name: TRACK_NAME,
      track_length_m: Math.round(this.track.length),
      session_type: "Time Trial",
    };
  }

  private frame(rig: RigSim): RigFrame {
    const base = {
      rig_id: rig.spec.info.rig_id,
      driver: rig.spec.offline ? null : rig.spec.driver,
      session: this.session(rig),
      best: rig.best,
    };
    if (rig.spec.offline) {
      return {
        ...base, state: "no_data", last_seen_ms: null, position: null, speed_kph: null, gear: null,
        throttle: null, brake: null, rpm: null, tyre: null, lap: null,
      };
    }
    if (!this.driving(rig)) {
      return {
        ...base, state: "in_menu_paused", last_seen_ms: 20, position: null, speed_kph: null, gear: null,
        throttle: null, brake: null, rpm: null, tyre: this.tyre(rig), lap: null,
      };
    }
    const p = sampleTrack(this.track, rig.distance);
    const kph = rig.speed * 3.6;
    const accel = rig.speed - rig.prevSpeed;
    const braking = accel < -0.05;
    const gear = gearFor(kph);
    const sector = Math.min(2, rig.sectorSplits.length) as 0 | 1 | 2;
    return {
      ...base,
      state: "driving",
      last_seen_ms: 8,
      position: { x: p.x, z: p.z },
      speed_kph: Math.round(kph),
      gear,
      throttle: braking ? 0 : accel > 0.02 ? 1 : 0.55,
      brake: braking ? Math.min(1, -accel / 0.6) : 0,
      rpm: rpmFor(kph, gear),
      max_rpm: 12500,
      tyre: this.tyre(rig),
      lap: {
        number: rig.lapNumber,
        distance_m: Math.round(rig.distance * 10) / 10,
        current_ms: Math.max(0, Math.round(rig.lapMs)),
        last_ms: rig.lastMs,
        valid: rig.valid,
        sector,
        sectors: [...rig.sectors] as Sectors,
        last_sectors: rig.lastSectors,
      },
    };
  }

  private outline(): TrackOutline {
    return {
      track_key: TRACK_KEY,
      track_name: TRACK_NAME,
      points: this.track.points.map(([x, z]) => [Math.round(x * 10) / 10, Math.round(z * 10) / 10]),
      source: "first_valid_lap",
      sector_starts: this.track.sectorStarts,
      display: { flip_x: false, flip_z: false, rotate_deg: 0 },
    };
  }

  private status(): HubStatus {
    const active = this.rigs.filter((r) => !r.spec.offline && r.spec.info.data_format);
    const formats = Object.fromEntries(active.map((r) => [r.spec.info.rig_id, r.spec.info.data_format!]));
    const mismatch = new Set(Object.values(formats)).size > 1;
    const warnings: HubStatus["warnings"] = [];
    if (mismatch) {
      warnings.push({
        code: "format_mismatch",
        message: `Rigs send different UDP formats (${[...new Set(Object.values(formats))].join(" and ")})`,
        rig_id: null,
      });
    }
    let recorder: HubStatus["recorder"] = null;
    if (this.options.recorder === "recording") recorder = { state: "recording", message: null, free_gb: 84.2 };
    if (this.options.recorder === "low") {
      recorder = { state: "low_disk_warning", message: null, free_gb: 3.4 };
      warnings.push({ code: "recorder_low_disk", message: "Low disk space for recordings (3.4 GB free)", rig_id: null });
    }
    if (this.options.recorder === "stopped") {
      recorder = { state: "stopped", message: "recording stopped: low disk", free_gb: 0.6 };
      warnings.push({ code: "recorder_stopped", message: "Recording stopped: low disk (0.6 GB free)", rig_id: null });
    }
    return { format_mismatch: mismatch, formats, recorder, warnings };
  }
}

function rigInfo(rig_id: string, name: string, colour: string, address: string, data_format: string | null): RigInfo {
  return { rig_id, name, colour, address, game: "F1", data_format, format_supported: true };
}

/** Read mock options from the page URL, e.g. ?outline=late&mismatch=1&recorder=stopped&speed=4. */
export function mockOptionsFromQuery(query: URLSearchParams): MockOptions {
  const recorder = query.get("recorder");
  return {
    ...DEFAULT_MOCK_OPTIONS,
    seed: Number(query.get("seed") ?? DEFAULT_MOCK_OPTIONS.seed) || DEFAULT_MOCK_OPTIONS.seed,
    outlineLate: query.get("outline") === "late",
    formatMismatch: query.get("mismatch") === "1",
    recorder: recorder === "recording" || recorder === "low" || recorder === "stopped" ? recorder : "off",
    offlineRig: query.get("offline") !== "0",
    pastDrivers: Math.max(0, Math.min(40, Math.floor(Number(query.get("board") ?? 0) || 0))),
    rigs: Math.max(1, Math.min(10, Math.floor(Number(query.get("rigs") ?? 2) || 2))),
    idle: query.get("idle") === "1",
  };
}
