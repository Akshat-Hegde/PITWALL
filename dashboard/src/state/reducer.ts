import {
  BOARD_PERIODS,
  KNOWN_TYPES,
  type BoardPeriod,
  SCHEMA_VERSION,
  type Comparison,
  type HubMessage,
  type HubStatus,
  type LapRecord,
  type Leaderboard,
  type RigFrame,
  type RigInfo,
  type TrackOutline,
} from "../schema";

export type LinkState = "connecting" | "live" | "reconnecting" | "version_mismatch";

export interface DashboardState {
  link: LinkState;
  /** "hub" when talking to a real hub, "mock" for the built-in simulation. */
  source: "hub" | "mock";
  receivedVersion: number | null;
  cafe: { name: string; branding: Record<string, string> };
  frameHz: number;
  status: HubStatus | null;
  rigs: RigInfo[];
  frames: Record<string, RigFrame>;
  comparison: Comparison | null;
  outlines: Record<string, TrackOutline>;
  /** Boards of the shown track by period ("today", "week", "all_time"). */
  leaderboards: Partial<Record<BoardPeriod, Leaderboard>>;
  recentLaps: LapRecord[];
  lastFrameAt: number | null;
}

export const RECENT_LAPS_MAX = 20;

export function initialState(source: DashboardState["source"]): DashboardState {
  return {
    link: "connecting",
    source,
    receivedVersion: null,
    cafe: { name: "", branding: {} },
    frameHz: 15,
    status: null,
    rigs: [],
    frames: {},
    comparison: null,
    outlines: {},
    leaderboards: {},
    recentLaps: [],
    lastFrameAt: null,
  };
}

function isPeriod(period: string): period is BoardPeriod {
  return (BOARD_PERIODS as readonly string[]).includes(period);
}

function boardsByPeriod(boards: Leaderboard[]): Partial<Record<BoardPeriod, Leaderboard>> {
  return Object.fromEntries(boards.filter((b) => isPeriod(b.period)).map((b) => [b.period, b]));
}

function framesById(frames: RigFrame[]): Record<string, RigFrame> {
  return Object.fromEntries(frames.map((f) => [f.rig_id, f]));
}

function upsertRig(rigs: RigInfo[], rig: RigInfo): RigInfo[] {
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
        status: msg.status,
        rigs: msg.rigs,
        frames: framesById(msg.frame.rigs),
        comparison: msg.frame.comparison,
        outlines: Object.fromEntries(msg.outlines.map((o) => [o.track_key, o])),
        leaderboards: boardsByPeriod(msg.leaderboards),
        recentLaps: msg.recent_laps.slice(0, RECENT_LAPS_MAX),
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
    case "leaderboard": {
      const period = msg.leaderboard.period;
      if (!isPeriod(period)) return state;
      // Boards of another track replace all of them (the hub sends all three when the track changes).
      const sameTrack = Object.values(state.leaderboards).every((b) => b?.track_key === msg.leaderboard.track_key);
      const base = sameTrack ? state.leaderboards : {};
      return { ...state, leaderboards: { ...base, [period]: msg.leaderboard } };
    }
  }
}
