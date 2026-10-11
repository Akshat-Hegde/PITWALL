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
  type Competition,
  type Moment,
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
  /** Podium moment every this many ms of simulated time; 0 = never (demo mode turns it on). */
  podiumEveryMs: number;
  /** A corporate event with teams is running. */
  event: boolean;
  /** A weekly challenge is running (?challenge=0 turns it off). */
  challenge: boolean;
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
  podiumEveryMs: 0,
  event: false,
  challenge: true,
};

const MOCK_QUEUE = [{ id: 1, name: "Jordan P" }, { id: 2, name: "Office party (4)" }, { id: 3, name: "Sam W" }];
const BOOKED_MIN = [20, 7, 15, 20, 45, 30, 20, 15, 30, 20]; // rig 2 is nearly out of time

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
  /** Driving style: where on the lap this driver is a little quicker or slower (head-to-head variety). */
  stylePhase: number;
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
  /** Smoothed longitudinal g for the friction circle. */
  gLong: number;
  saves: number;
  savedLap: number;
  lastSaveAt: number | null;
  announced: boolean;
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
  private sincePodium = 0;
  private readonly startedAt: number;
  private outlineSent: boolean;
  private sessionBestSectors: [number, number, number] = [Infinity, Infinity, Infinity];
  private leaderboard: Leaderboard | null = null;
  private readonly recentLaps: LapRecord[] = [];
  private readonly pastEntries: LeaderboardEntry[] = [];

  constructor(readonly options: MockOptions = DEFAULT_MOCK_OPTIONS, private readonly clock: () => number = Date.now) {
    this.track = buildTrack();
    this.startedAt = clock();
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
      stylePhase: i * 1.9,
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
      gLong: 0,
      saves: 0,
      savedLap: 0,
      lastSaveAt: null,
      announced: false,
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
             lan_address: "192.168.1.10", steering_rotation_deg: 360,
             features: { moments: true, battles: true, podium: true, attract: true, portrait: true,
                         head_to_head: true, onboard: true, sharing: true, challenges: true, events: true },
             moments: { battle_margin_ms: 300 }, sounds: { enabled: false, volume: 0.6 } },
      cafe: { name: "Sim Racing Cafe", branding: {} },
      status: this.status(),
      rigs: this.rigs.map((r) => r.spec.info),
      frame: { rigs: this.rigs.map((r) => this.frame(r)), comparison: this.comparison() },
      outlines: this.outlineSent ? [this.outline()] : [],
      leaderboards: this.leaderboard ? this.periodBoards(this.leaderboard) : [],
      recent_laps: [...this.recentLaps],
      queue: MOCK_QUEUE.slice(0, this.options.rigs >= 4 ? 3 : 2),
      competition: this.competition(),
    };
  }

  /** Advance the simulation by dtMs and return the messages a hub would send for this tick. */
  step(dtMs: number): HubMessage[] {
    const out: HubMessage[] = [];
    this.simMs += dtMs;
    for (const rig of this.rigs) out.push(...this.advance(rig, dtMs));
    out.push(...this.podiumDue(dtMs));
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
    if (!rig.announced && rig.spec.driver && rig.spec.menuUntilMs > 0) {
      rig.announced = true; // rigs that start later get a "now driving" moment, like a staff-started session
      msgs.push(this.moment(this.nowDriving(rig)));
    }
    const lapAngle = (Math.max(0, rig.distance) / this.track.length) * Math.PI * 2;
    const style = 1 + 0.014 * Math.sin(lapAngle * 3 + rig.stylePhase);
    const target = sampleTrack(this.track, rig.distance).speed * rig.lapPace * style;
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
    const recordBefore = this.leaderboard?.entries[0] ?? null;
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
    if (valid && recordBefore && lapMs < recordBefore.lap_ms) {
      msgs.push(this.moment(this.recordMoment(rig, lapMs, recordBefore)));
    }
    if (personalBest) {
      this.leaderboard = this.buildLeaderboard();
      for (const board of this.periodBoards(this.leaderboard)) {
        msgs.push({ ...this.envelope("leaderboard"), leaderboard: board });
      }
      msgs.push({ ...this.envelope("competition"), competition: this.competition() });
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

  private moment(moment: Moment): HubMessage {
    return { ...this.envelope("moment"), moment };
  }

  private nowDriving(rig: RigSim): Moment {
    const record = this.leaderboard?.entries[0] ?? null;
    return {
      kind: "now_driving", at: this.clock(), rig_id: rig.spec.info.rig_id, rig_name: rig.spec.info.name,
      driver: rig.spec.driver ?? rig.spec.info.name, track_key: TRACK_KEY, track_name: TRACK_NAME,
      today_record: record ? { driver: record.driver, lap_ms: record.lap_ms } : null,
      personal_best_ms: rig.best?.lap_ms ?? null,
    };
  }

  private recordMoment(rig: RigSim, lapMs: number, before: LeaderboardEntry): Moment {
    const gap = lapMs - before.lap_ms;
    const prev = { previous_ms: before.lap_ms, previous_driver: before.driver ?? before.rig_name, gap_ms: gap };
    return {
      kind: "record", at: this.clock(), rig_id: rig.spec.info.rig_id, driver: rig.spec.driver, track_key: TRACK_KEY,
      track_name: TRACK_NAME, lap_ms: lapMs, lap_class: "pro",
      records: [{ period: "all_time", lap_class: "pro", ...prev }, { period: "all_time", lap_class: "open", ...prev },
                { period: "today", lap_class: "open", ...prev }],
    };
  }

  private podiumMoment(): Moment | null {
    const entries = this.leaderboard?.entries.slice(0, 3) ?? [];
    if (!entries.length) return null;
    return { kind: "podium", at: this.clock(), reason: "hourly", track_key: TRACK_KEY, track_name: TRACK_NAME, entries };
  }

  /** A moment right now, for demos and screenshots (?moment=now_driving|record|podium). */
  forceMoment(kind: string): HubMessage | null {
    const rig = this.rigs.find((r) => !r.spec.offline) ?? null;
    if (!rig) return null;
    if (kind === "now_driving") return this.moment(this.nowDriving(rig));
    if (kind === "podium") {
      const m = this.podiumMoment();
      return m ? this.moment(m) : null;
    }
    if (kind === "challenge_winner") {
      const c = this.competition().challenge!;
      return this.moment({ kind: "challenge_winner", at: this.clock(), challenge_id: c.id, title: c.title,
        track_name: c.track_name, lap_class: c.lap_class, prize: c.prize,
        winner: c.entries[0] ?? { rank: 1, driver: "Maya R", lap_ms: 87_671, gap_ms: 0 },
        runners_up: c.entries.slice(1, 3) });
    }
    if (kind === "card") {
      return { ...this.envelope("moment"), moment: {
        kind: "card", at: this.clock(), rig_id: rig.spec.info.rig_id, driver: rig.spec.driver ?? "Driver",
        token: "demo", url: `${globalThis.location?.origin ?? ""}/card/demo`, best_ms: rig.best?.lap_ms ?? 87_259,
        track_name: TRACK_NAME } };
    }
    if (kind === "record") {
      const top = this.leaderboard?.entries[0];
      const base: LeaderboardEntry = top ?? { rank: 1, rig_id: "rig-2", rig_name: "Rig 2", driver: "Maya R",
        lap_ms: 87_671, sectors_ms: null, gap_ms: 0, tyre: null, lap_number: 3, set_at: this.clock() };
      return this.moment(this.recordMoment(rig, base.lap_ms - 412, base));
    }
    return null;
  }

  /** Podium every podiumEveryMs of simulated time (demo mode). */
  private podiumDue(dtMs: number): HubMessage[] {
    if (!this.options.podiumEveryMs) return [];
    this.sincePodium += dtMs;
    if (this.sincePodium < this.options.podiumEveryMs) return [];
    this.sincePodium = 0;
    const m = this.podiumMoment();
    return m ? [this.moment(m)] : [];
  }

  /** A weekly challenge (always) and a corporate event (?event=1 or demo mode). */
  competition(): Competition {
    const day = 24 * 3600_000;
    const board = this.leaderboard?.entries ?? [];
    const leader = board[0]?.lap_ms ?? 0;
    const challenge = {
      id: 1, title: "Practice circuit Pro week", track_key: TRACK_KEY, track_name: TRACK_NAME, lap_class: "pro",
      starts_at: this.startedAt - 2 * day, ends_at: this.startedAt + 3 * day + 4 * 3600_000,
      prize: "Free hour for the fastest Pro lap", state: "running",
      entries: board.slice(0, 5).map((e, i) => ({ rank: i + 1, driver: e.driver ?? e.rig_name, lap_ms: e.lap_ms,
                                                   gap_ms: e.lap_ms - leader })),
    };
    if (!this.options.event) return { challenge: this.options.challenge ? challenge : null, event: null };
    const names = board.map((e) => e.driver ?? e.rig_name);
    const team = (id: number, name: string, members: string[]) => {
      const bests = members.map((m) => ({ id: id * 10 + members.indexOf(m), name: m,
        best_ms: board.find((e) => (e.driver ?? e.rig_name) === m)?.lap_ms ?? null }));
      const counted = bests.filter((b) => b.best_ms != null).map((b) => b.best_ms!).sort((a, b) => a - b).slice(0, 2);
      return { id, rank: 0, name, logo: null, members: bests, counted: counted.length,
               average_ms: counted.length ? Math.round(counted.reduce((a, b) => a + b, 0) / counted.length) : null };
    };
    const teams = [team(1, "Sales sharks", names.slice(0, 3)), team(2, "Dev ops", names.slice(3, 6)),
                   team(3, "Finance flyers", names.slice(6, 9)), team(4, "People team", names.slice(9, 11))]
      .sort((a, b) => (a.average_ms ?? Infinity) - (b.average_ms ?? Infinity)).map((t, i) => ({ ...t, rank: i + 1 }));
    return { challenge: this.options.challenge ? challenge : null, event: { id: 1, name: "Q4 kick-off", company: "Northwind", accent: "#0a84ff", logo: null,
      track_key: TRACK_KEY, track_name: TRACK_NAME, best_n: 2, starts_at: this.startedAt, teams } };
  }

  /** The mock has one session, so every period shows the same board. */
  private periodBoards(board: Leaderboard): Leaderboard[] {
    const today = new Date(this.clock());
    today.setHours(0, 0, 0, 0);
    const monday = new Date(today);
    monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
    // Pro boards: the drivers who run without assists (every third one, plus rig 1's driver), re-ranked.
    const proEntries = board.entries.filter((e, i) => i % 3 === 0 || e.rig_id === "rig-1");
    const proLeader = proEntries[0]?.lap_ms ?? 0;
    const pro: Leaderboard = { ...board, lap_class: "pro",
      entries: proEntries.map((e, i) => ({ ...e, rank: i + 1, gap_ms: e.lap_ms - proLeader })) };
    const open: Leaderboard = { ...board, lap_class: "open" };
    return [open, pro].flatMap((b) => [
      { ...b, period: "today", since: today.getTime() },
      { ...b, period: "week", since: monday.getTime() },
      { ...b, period: "all_time", since: null },
    ]);
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
      weather: "light_cloud",
      air_temp_c: 23,
      track_temp_c: 31,
    };
  }

  private frame(rig: RigSim): RigFrame {
    const base = {
      rig_id: rig.spec.info.rig_id,
      driver: rig.spec.offline ? null : rig.spec.driver,
      session: this.session(rig),
      best: rig.best,
      booking: rig.spec.offline || !rig.spec.driver ? null : {
        driver: rig.spec.driver, started_at: this.startedAt,
        ends_at: this.startedAt + BOOKED_MIN[(Number(rig.spec.info.rig_id.split("-")[1]) - 1) % 10]! * 60_000,
      },
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
      car: this.carDetail(rig, kph, gear, braking, accel),
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

  private carDetail(rig: RigSim, kph: number, gear: number, braking: boolean, accel: number) {
    const wear = Math.min(60, rig.tyreAge * 2.4 + (rig.distance / this.track.length) * 2.4);
    const heat = braking ? 8 : 0;
    const surface: [number, number, number, number] = [96 + heat, 99 + heat, 92, 94];
    const lapFraction = Math.max(0, rig.distance) / this.track.length;
    const g = Math.max(-1, Math.min(1, (rig.speed - rig.prevSpeed) / 1.2));
    const stintLap = (rig.lapNumber - 1) % 10;
    const gTarget = braking ? -4 * Math.min(1, -accel / 0.6) : g * 1.2;
    rig.gLong += (gTarget - rig.gLong) * 0.3; // smoothed, like a real car's
    return {
      drs_open: kph > 285,
      drs_allowed: true,
      rev_lights_pct: Math.round(Math.max(0, Math.min(100, ((rpmFor(kph, gear) - 7000) / 5000) * 100))),
      ers_pct: Math.round((60 + 35 * Math.sin(lapFraction * Math.PI * 2 + rig.lapNumber)) * 10) / 10,
      ers_mode: "hotlap",
      // Fuel runs down over a 10-lap stint, then the car is refuelled.
      fuel_kg: Math.round((18 - stintLap * 1.6 - lapFraction * 1.6) * 100) / 100,
      fuel_laps: Math.round((4.5 - stintLap * 0.4) * 100) / 100,
      pit_limiter: false,
      steer: Math.round(Math.sin(rig.distance / 140) * 0.6 * 1000) / 1000,
      g_lat: Math.round(Math.sin(rig.distance / 140) * 3.2 * 100) / 100,
      g_long: Math.round(rig.gLong * 100) / 100,
      tyre_surface_c: surface,
      tyre_inner_c: [101, 103, 98, 99] as [number, number, number, number],
      tyre_pressure_psi: [23.1, 23.2, 21.4, 21.5] as [number, number, number, number],
      tyre_wear_pct: [wear * 1.1, wear * 1.15, wear * 0.9, wear * 0.95].map((w) => Math.round(w * 10) / 10) as [
        number, number, number, number],
      brake_c: [braking ? 780 : 420, braking ? 790 : 430, braking ? 610 : 360, braking ? 620 : 370] as [
        number, number, number, number],
      damage: { front_wing_left: rig.lapNumber >= 3 ? 18 : 0, front_wing_right: 0, rear_wing: 0,
        floor: rig.lapNumber >= 3 ? 6 : 0, diffuser: 0, sidepod: 0, gearbox: 0, engine: 0 },
      ...this.slide(rig, lapFraction),
      top_speed_lap_kph: Math.round(Math.max(kph, 300 * rig.lapPace)),
      top_speed_kph: Math.round(318 * rig.spec.pace),
    };
  }

  /** A slide through 30-36% of every lap: peak ~24 degrees, caught (a "save"). */
  private slide(rig: RigSim, lapFraction: number) {
    const from = 0.3;
    const to = 0.36;
    let slide = Math.sin(rig.distance / 90) * 2;
    if (lapFraction > from && lapFraction < to) {
      slide = Math.sin(((lapFraction - from) / (to - from)) * Math.PI) * 24;
    }
    if (lapFraction >= to && rig.savedLap !== rig.lapNumber) {
      rig.savedLap = rig.lapNumber;
      rig.saves += 1;
      rig.lastSaveAt = this.clock();
    }
    return {
      slide_deg: Math.round(slide * 10) / 10,
      saves: rig.saves,
      last_save_at: rig.lastSaveAt,
      last_save_peak_deg: rig.saves > 0 ? 24 : null,
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
  if (query.get("demo") === "1") {
    // Demo mode: a busy cafe. Six rigs, a full board, a podium every 3 minutes, a corporate event.
    return { ...DEFAULT_MOCK_OPTIONS, rigs: Number(query.get("rigs") ?? 6) || 6, pastDrivers: 14,
             offlineRig: false, podiumEveryMs: 180_000, event: true };
  }
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
    podiumEveryMs: Math.max(0, Number(query.get("podium") ?? 0) || 0) * 1000,
    event: query.get("event") === "1",
    challenge: query.get("challenge") !== "0",
  };
}
