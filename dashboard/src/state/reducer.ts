import {
  BOARD_PERIODS,
  KNOWN_TYPES,
  type BoardPeriod,
  SCHEMA_VERSION,
  type Comparison,
  type Features,
  MOMENT_KINDS,
  type BattleMoment,
  type CafeInfo,
  type CardMoment,
  type Competition,
  type HeadToHead,
  type Moment,
  type QueueEntry,
  type HubMessage,
  type HubStatus,
  type LapRecord,
  type Leaderboard,
  type RigFrame,
  type RigInfo,
  type TrackOutline,
  type TvSetting,
  type StoryLap,
} from "../schema";
import { softenColour } from "../colour";
import { hubNow } from "./hubclock";

export type LinkState = "connecting" | "live" | "reconnecting" | "version_mismatch";

export interface DashboardState {
  link: LinkState;
  /** "hub" when talking to a real hub, "mock" for the built-in simulation. */
  source: "hub" | "mock";
  receivedVersion: number | null;
  cafe: CafeInfo;
  frameHz: number;
  /** Where games send telemetry, from the hub (for the waiting screen). */
  telemetryTarget: { address: string | null; port: number };
  /** Lock-to-lock rotation of the steering wheel graphic, degrees. */
  steeringRotationDeg: number;
  status: HubStatus | null;
  rigs: RigInfo[];
  frames: Record<string, RigFrame>;
  comparison: Comparison | null;
  outlines: Record<string, TrackOutline>;
  /** Open boards of the shown track by period ("today", "week", "all_time"). */
  leaderboards: Partial<Record<BoardPeriod, Leaderboard>>;
  /** Pro boards (every assist off), same periods. */
  proLeaderboards: Partial<Record<BoardPeriod, Leaderboard>>;
  /** Current challenge and running corporate event. */
  competition: Competition;
  /** Head to head from the hub (survives TV reloads); null until two drivers have a traced lap today. */
  headToHead: HeadToHead | null;
  tv: TvSetting;
  recentLaps: LapRecord[];
  /** Laps on the shown track in the last hour (the LIVE page's session story). */
  storyLaps: StoryLap[];
  /** Newest first: what just happened, for the LIVE page's moments log. */
  pitEvents: PitEvent[];
  lastFrameAt: number | null;
  /** Optional features from the hub config (missing = on). */
  features: Features;
  battleMarginMs: number;
  sounds: { enabled: boolean; volume: number };
  /** Broadcast moments waiting to be shown, oldest first (the store removes each once shown). */
  moments: Moment[];
  /** Who's waiting for a rig (names only). */
  queue: QueueEntry[];
  /** Story cards just made (newest last): the TV shows their QR codes for a while. */
  cards: CardMoment[];
  /** A battle pop-up sent by the hub (demo director), shown before any the TV found itself. */
  battle: BattleMoment | null;
}

export const ALL_FEATURES: Features = {
  moments: true, battles: true, podium: true, attract: true, portrait: true, head_to_head: true, onboard: true,
  sharing: true, challenges: true, events: true, race_podium: true,
};
export const CARDS_MAX = 3;
export const MOMENTS_MAX = 5;

export const RECENT_LAPS_MAX = 20;

export function initialState(source: DashboardState["source"]): DashboardState {
  return {
    link: "connecting",
    source,
    receivedVersion: null,
    cafe: { name: "", branding: {} },
    frameHz: 15,
    telemetryTarget: { address: null, port: 20777 },
    steeringRotationDeg: 360,
    status: null,
    rigs: [],
    frames: {},
    comparison: null,
    outlines: {},
    leaderboards: {},
    proLeaderboards: {},
    competition: { challenge: null, event: null },
    headToHead: null,
    tv: { page: "live", pinned_rig: null, overlay: null, updated_at: 0 },
    recentLaps: [],
    storyLaps: [],
    pitEvents: [],
    lastFrameAt: null,
    features: ALL_FEATURES,
    battleMarginMs: 300,
    sounds: { enabled: false, volume: 0.6 },
    moments: [],
    queue: [],
    cards: [],
    battle: null,
  };
}

function momentAllowed(moment: Moment, features: Features): boolean {
  if (!moment || !MOMENT_KINDS.has(moment.kind)) return false;
  if (moment.kind === "podium") return features.podium;
  if (moment.kind === "challenge_winner") return features.challenges;
  if (moment.kind === "race_podium") return features.sharing && features.race_podium;
  return features.moments;
}

/** Add a moment to the queue. When it's full, the oldest waiting ones go, never the head: it is on screen. */
function queueMoment(queue: Moment[], moment: Moment): Moment[] {
  const next = [...queue, moment];
  return next.length <= MOMENTS_MAX ? next : [next[0]!, ...next.slice(-(MOMENTS_MAX - 1))];
}

function isPeriod(period: string): period is BoardPeriod {
  return (BOARD_PERIODS as readonly string[]).includes(period);
}

function isPro(board: Leaderboard): boolean {
  return board.lap_class === "pro";
}

function boardsByPeriod(boards: Leaderboard[], pro = false): Partial<Record<BoardPeriod, Leaderboard>> {
  return Object.fromEntries(boards.filter((b) => isPeriod(b.period) && isPro(b) === pro).map((b) => [b.period, b]));
}

function framesById(frames: RigFrame[]): Record<string, RigFrame> {
  return Object.fromEntries(frames.map((f) => [f.rig_id, f]));
}

/** Rig colours are shown desaturated everywhere (map, stripes, charts). */
function soften(rig: RigInfo): RigInfo {
  return { ...rig, colour: softenColour(rig.colour) };
}

function upsertRig(rigs: RigInfo[], incoming: RigInfo): RigInfo[] {
  const rig = soften(incoming);
  const i = rigs.findIndex((r) => r.rig_id === rig.rig_id);
  if (i < 0) return [...rigs, rig];
  const next = rigs.slice();
  next[i] = rig;
  return next;
}

/** Apply one hub message. Pure; unknown message types and fields are ignored per the schema. */
export function applyMessage(state: DashboardState, msg: HubMessage, now: number): DashboardState {
  if (msg.v !== SCHEMA_VERSION) {
    return { ...state, link: "version_mismatch", receivedVersion: msg.v };
  }
  if (state.link === "version_mismatch" || !KNOWN_TYPES.has(msg.type)) return state;

  switch (msg.type) {
    case "snapshot":
      // A snapshot replaces all state.
      return {
        ...initialState(state.source),
        link: "live",
        receivedVersion: msg.v,
        cafe: msg.cafe,
        frameHz: msg.hub.frame_hz,
        telemetryTarget: { address: msg.hub.lan_address ?? null, port: msg.hub.udp_port ?? 20777 },
        steeringRotationDeg: msg.hub.steering_rotation_deg ?? 360,
        features: { ...ALL_FEATURES, ...(msg.hub.features ?? {}) },
        battleMarginMs: msg.hub.moments?.battle_margin_ms ?? 300,
        sounds: msg.hub.sounds ?? { enabled: false, volume: 0.6 },
        status: msg.status,
        rigs: msg.rigs.map(soften),
        frames: framesById(msg.frame.rigs),
        comparison: msg.frame.comparison,
        outlines: Object.fromEntries(msg.outlines.map((o) => [o.track_key, o])),
        leaderboards: boardsByPeriod(msg.leaderboards),
        proLeaderboards: boardsByPeriod(msg.leaderboards, true),
        competition: msg.competition ?? { challenge: null, event: null },
        headToHead: msg.head_to_head ?? null,
        tv: msg.tv ?? state.tv,
        recentLaps: msg.recent_laps.slice(0, RECENT_LAPS_MAX),
        storyLaps: (msg.session_story ?? []).slice(-STORY_LAPS_MAX),
        pitEvents: storyEvents(msg.session_story ?? []),
        queue: msg.queue ?? [],
        lastFrameAt: now,
      };
    case "frame":
      return { ...state, frames: framesById(msg.rigs), comparison: msg.comparison, lastFrameAt: now };
    case "rig_info":
      return { ...state, rigs: upsertRig(state.rigs, msg.rig) };
    case "status":
      return { ...state, status: msg.status };
    case "session_changed": {
      const frame = state.frames[msg.rig_id];
      if (!frame) return state;
      return { ...state, frames: { ...state.frames, [msg.rig_id]: { ...frame, session: msg.session } } };
    }
    case "track_outline":
      return { ...state, outlines: { ...state.outlines, [msg.outline.track_key]: msg.outline } };
    case "lap_completed": {
      const lap = msg.lap;
      const story: StoryLap = { rig_id: lap.rig_id, driver: lap.driver, track_key: lap.track_key, lap_ms: lap.lap_ms, valid: lap.valid,
        out_lap: lap.out_lap, lap_class: lap.lap_class, completed_at: lap.completed_at };
      const event = lapEvent(lap);
      return {
        ...state,
        recentLaps: [lap, ...state.recentLaps].slice(0, RECENT_LAPS_MAX),
        storyLaps: [...state.storyLaps, story].filter((l) => l.completed_at >= lap.completed_at - STORY_WINDOW_MS)
          .slice(-STORY_LAPS_MAX),
        pitEvents: event ? [event, ...state.pitEvents].slice(0, PIT_EVENTS_MAX) : state.pitEvents,
      };
    }
    case "head_to_head":
      return { ...state, headToHead: msg.head_to_head };
    case "tv":
      return { ...state, tv: msg.tv };
    case "cafe":
      return { ...state, cafe: msg.cafe };
    case "competition":
      return { ...state, competition: msg.competition };
    case "queue":
      return { ...state, queue: msg.queue };
    case "moment":
      state = momentEvent(state, msg.moment);
      if (msg.moment?.kind === "battle") {
        return state.features.battles ? { ...state, battle: msg.moment as BattleMoment } : state;
      }
      if (msg.moment?.kind === "card") {
        if (!state.features.sharing) return state;
        return { ...state, cards: [...state.cards, msg.moment as CardMoment].slice(-CARDS_MAX) };
      }
      if (!momentAllowed(msg.moment as Moment, state.features)) return state;
      return { ...state, moments: queueMoment(state.moments, msg.moment as Moment) };
    case "leaderboard": {
      const period = msg.leaderboard.period;
      if (!isPeriod(period)) return state;
      // Boards of another track replace all of them (the hub sends all of them when the track changes).
      const key = isPro(msg.leaderboard) ? "proLeaderboards" : "leaderboards";
      const sameTrack = Object.values(state[key]).every((b) => b?.track_key === msg.leaderboard.track_key);
      const base = sameTrack ? state[key] : {};
      return { ...state, [key]: { ...base, [period]: msg.leaderboard } };
    }
  }
}

// ---- LIVE page: session story and moments log ----------------------------------------------------

export const STORY_WINDOW_MS = 60 * 60_000;
export const STORY_LAPS_MAX = 400;
export const PIT_EVENTS_MAX = 8;

/** One line of the moments log. tone: p purple (record / fastest), g green (personal best), r red (invalid),
 *  w white (other). */
export interface PitEvent {
  at: number;
  rig_id: string;
  driver: string | null;
  label: string;
  value: string;
  tone: "p" | "g" | "r" | "w";
  strike?: boolean;
}

function fmtLap(ms: number): string {
  const m = Math.floor(ms / 60000);
  const s = ((ms % 60000) / 1000).toFixed(3).padStart(6, "0");
  return m ? `${m}:${s}` : s;
}

export function lapEvent(lap: LapRecord): PitEvent | null {
  const base = { at: lap.completed_at, rig_id: lap.rig_id, driver: lap.driver, value: fmtLap(lap.lap_ms) };
  if (lap.out_lap) return null;
  if (!lap.valid) return { ...base, label: "LAP INVALID", tone: "r", strike: true };
  if (lap.session_best) return { ...base, label: "FASTEST LAP TODAY", tone: "p" };
  if (lap.personal_best) return { ...base, label: "PERSONAL BEST", tone: "g" };
  return null;
}

/** Events from the snapshot's story laps (no PB flags there: personal bests are worked out in order). */
function storyEvents(laps: StoryLap[]): PitEvent[] {
  const best = new Map<string, number>();
  const out: PitEvent[] = [];
  for (const l of laps) {
    if (l.out_lap) continue;
    const key = (l.driver ?? l.rig_id).toLowerCase();
    const base = { at: l.completed_at, rig_id: l.rig_id, driver: l.driver, value: fmtLap(l.lap_ms) };
    if (!l.valid) {
      out.push({ ...base, label: "LAP INVALID", tone: "r", strike: true });
      continue;
    }
    const prev = best.get(key);
    if (prev === undefined || l.lap_ms < prev) {
      best.set(key, l.lap_ms);
      if (prev !== undefined) out.push({ ...base, label: "PERSONAL BEST", tone: "g" });
    }
  }
  return out.reverse().slice(0, PIT_EVENTS_MAX);
}

function momentEvent(state: DashboardState, moment: unknown): DashboardState {
  const m = moment as { kind?: string; at?: number; rig_id?: string; rig_name?: string; driver?: string | null;
    lap_ms?: number } | null;
  if (!m || (m.kind !== "record" && m.kind !== "now_driving") || !m.rig_id) return state;
  const event: PitEvent = m.kind === "record"
    ? { at: m.at ?? hubNow(), rig_id: m.rig_id, driver: m.driver ?? null, label: "NEW RECORD",
        value: m.lap_ms != null ? fmtLap(m.lap_ms) : "", tone: "p" }
    : { at: m.at ?? hubNow(), rig_id: m.rig_id, driver: m.driver ?? null,
        label: `NOW DRIVING · ${(m.rig_name ?? "").toUpperCase()}`, value: "", tone: "w" };
  // A record lap also logged "fastest lap today" when it completed: the record line replaces it.
  const rest = state.pitEvents.filter((e) => !(m.kind === "record" && e.rig_id === m.rig_id && e.tone === "p"
    && Math.abs(e.at - event.at) < 10_000));
  return { ...state, pitEvents: [event, ...rest].slice(0, PIT_EVENTS_MAX) };
}
