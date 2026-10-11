import {
  BOARD_PERIODS,
  KNOWN_TYPES,
  type BoardPeriod,
  SCHEMA_VERSION,
  type Comparison,
  type Features,
  MOMENT_KINDS,
  type CardMoment,
  type Competition,
  type Moment,
  type QueueEntry,
  type HubMessage,
  type HubStatus,
  type LapRecord,
  type Leaderboard,
  type RigFrame,
  type RigInfo,
  type TrackOutline,
} from "../schema";
import { softenColour } from "../colour";

export type LinkState = "connecting" | "live" | "reconnecting" | "version_mismatch";

export interface DashboardState {
  link: LinkState;
  /** "hub" when talking to a real hub, "mock" for the built-in simulation. */
  source: "hub" | "mock";
  receivedVersion: number | null;
  cafe: { name: string; branding: Record<string, string> };
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
  recentLaps: LapRecord[];
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
}

export const ALL_FEATURES: Features = {
  moments: true, battles: true, podium: true, attract: true, portrait: true, head_to_head: true, onboard: true,
  sharing: true, challenges: true, events: true,
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
    recentLaps: [],
    lastFrameAt: null,
    features: ALL_FEATURES,
    battleMarginMs: 300,
    sounds: { enabled: false, volume: 0.6 },
    moments: [],
    queue: [],
    cards: [],
  };
}

function momentAllowed(moment: Moment, features: Features): boolean {
  if (!moment || !MOMENT_KINDS.has(moment.kind)) return false;
  if (moment.kind === "podium") return features.podium;
  if (moment.kind === "challenge_winner") return features.challenges;
  return features.moments;
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
        recentLaps: msg.recent_laps.slice(0, RECENT_LAPS_MAX),
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
    case "lap_completed":
      return { ...state, recentLaps: [msg.lap, ...state.recentLaps].slice(0, RECENT_LAPS_MAX) };
    case "competition":
      return { ...state, competition: msg.competition };
    case "queue":
      return { ...state, queue: msg.queue };
    case "moment":
      if (msg.moment?.kind === "card") {
        if (!state.features.sharing) return state;
        return { ...state, cards: [...state.cards, msg.moment as CardMoment].slice(-CARDS_MAX) };
      }
      if (!momentAllowed(msg.moment as Moment, state.features)) return state;
      return { ...state, moments: [...state.moments, msg.moment as Moment].slice(-MOMENTS_MAX) };
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
