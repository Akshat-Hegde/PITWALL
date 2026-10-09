// TypeScript twin of docs/WS_SCHEMA.md (v1, frozen: additive changes only). Keep the two in sync.

export const SCHEMA_VERSION = 1;

export type RigState = "driving" | "in_menu_paused" | "no_data";
export type CompoundClass = "soft" | "medium" | "hard" | "inter" | "wet" | "other" | "unknown";
export type SectorRating = "session_best" | "personal_best" | "normal";
export type RecorderState = "recording" | "low_disk_warning" | "stopped";
export type WarningCode =
  | "format_mismatch"
  | "format_unsupported"
  | "size_mismatch"
  | "recorder_low_disk"
  | "recorder_stopped";

export interface RigInfo {
  rig_id: string;
  name: string;
  colour: string;
  address: string;
  game: string;
  data_format: string | null;
  format_supported: boolean;
}

export interface HubWarning {
  code: WarningCode | string;
  message: string;
  rig_id: string | null;
}

export interface HubStatus {
  format_mismatch: boolean;
  formats: Record<string, string>;
  recorder: { state: RecorderState; message: string | null; free_gb: number | null } | null;
  warnings: HubWarning[];
}

export interface SessionInfo {
  session_id: string | null;
  track_key: string | null;
  track_name: string | null;
  track_length_m: number | null;
  session_type: string | null;
}

export interface Tyre {
  compound: CompoundClass | string;
  label: string;
  age_laps: number | null;
}

export interface SectorTime {
  ms: number;
  rating: SectorRating | null;
}

export type Sectors = [SectorTime | null, SectorTime | null, SectorTime | null];

export interface LiveLap {
  number: number;
  distance_m: number;
  current_ms: number;
  last_ms: number | null;
  valid: boolean;
  sector: 0 | 1 | 2;
  sectors: Sectors;
  last_sectors: Sectors | null;
}

export interface BestLap {
  lap_ms: number;
  sectors_ms: [number, number, number];
  lap_number: number;
  set_at: number;
}

export interface RigFrame {
  rig_id: string;
  state: RigState;
  last_seen_ms: number | null;
  driver: string | null;
  session: SessionInfo;
  position: { x: number; z: number } | null;
  speed_kph: number | null;
  gear: number | null;
  throttle: number | null;
  brake: number | null;
  rpm: number | null;
  tyre: Tyre | null;
  lap: LiveLap | null;
  best: BestLap | null;
  /** The driver's fastest valid lap on this track ever (added in v1; older hubs don't send it). */
  personal_best?: BestLap | null;
}

export interface ComparisonEntry {
  rig_id: string;
  reference_rig_id: string | null;
  best_gap_ms: number | null;
  live_delta_ms: number | null;
}

export interface Comparison {
  track_key: string;
  rigs: ComparisonEntry[];
}

export interface TrackOutline {
  track_key: string;
  track_name: string | null;
  points: [number, number][];
  source: "first_valid_lap" | "bundled" | string;
  sector_starts: [number, number, number] | null;
  display: { flip_x: boolean; flip_z: boolean; rotate_deg: number };
}

export interface LapRecord {
  rig_id: string;
  driver: string | null;
  track_key: string;
  session_id: string | null;
  lap_number: number;
  lap_ms: number;
  sectors_ms: [number, number, number] | null;
  valid: boolean;
  /** Started from the pit/garage: never counts for bests, whatever `valid` says. */
  out_lap: boolean;
  tyre: Tyre | null;
  personal_best: boolean;
  session_best: boolean;
  completed_at: number;
}

export interface LeaderboardEntry {
  rank: number;
  rig_id: string;
  rig_name: string;
  driver: string | null;
  lap_ms: number;
  sectors_ms: [number, number, number] | null;
  gap_ms: number;
  tyre: Tyre | null;
  lap_number: number;
  set_at: number;
}

export type BoardPeriod = "today" | "week" | "all_time";
export const BOARD_PERIODS: readonly BoardPeriod[] = ["today", "week", "all_time"];

export interface Leaderboard {
  track_key: string;
  track_name: string | null;
  /** Which board this is; unknown values must be ignored. */
  period: BoardPeriod | string;
  /** Unix ms where the period starts (hub's local time); null for all time. */
  since: number | null;
  entries: LeaderboardEntry[];
}

export interface Envelope<T extends string> {
  v: number;
  type: T;
  seq: number;
  ts: number;
}

export interface SnapshotMessage extends Envelope<"snapshot"> {
  hub: { version: string; games: string[]; frame_hz: number };
  cafe: { name: string; branding: Record<string, string> };
  status: HubStatus;
  rigs: RigInfo[];
  frame: { rigs: RigFrame[]; comparison: Comparison | null };
  outlines: TrackOutline[];
  /** One board per period for the shown track; empty while no track is known. */
  leaderboards: Leaderboard[];
  recent_laps: LapRecord[];
}

export interface FrameMessage extends Envelope<"frame"> {
  rigs: RigFrame[];
  comparison: Comparison | null;
}

export interface RigInfoMessage extends Envelope<"rig_info"> {
  rig: RigInfo;
}

export interface StatusMessage extends Envelope<"status"> {
  status: HubStatus;
}

export interface SessionChangedMessage extends Envelope<"session_changed"> {
  rig_id: string;
  session: SessionInfo;
}

export interface TrackOutlineMessage extends Envelope<"track_outline"> {
  outline: TrackOutline;
}

export interface LapCompletedMessage extends Envelope<"lap_completed"> {
  lap: LapRecord;
}

export interface LeaderboardMessage extends Envelope<"leaderboard"> {
  leaderboard: Leaderboard;
}

export type HubMessage =
  | SnapshotMessage
  | FrameMessage
  | RigInfoMessage
  | StatusMessage
  | SessionChangedMessage
  | TrackOutlineMessage
  | LapCompletedMessage
  | LeaderboardMessage;

/** Message types this client knows; others must be ignored (schema rule). */
export const KNOWN_TYPES: ReadonlySet<string> = new Set<HubMessage["type"]>([
  "snapshot",
  "frame",
  "rig_info",
  "status",
  "session_changed",
  "track_outline",
  "lap_completed",
  "leaderboard",
]);
