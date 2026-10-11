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
  /** Added in v1 (optional): conditions. */
  weather?: "clear" | "light_cloud" | "overcast" | "light_rain" | "heavy_rain" | "storm" | string | null;
  air_temp_c?: number | null;
  track_temp_c?: number | null;
}

/** Four values per wheel, ordered front-left, front-right, rear-left, rear-right. */
export type PerWheel = [number, number, number, number];

/** Added in v1 (optional): car detail beyond speed / gear / pedals. */
export interface CarDetail {
  drs_open: boolean | null;
  drs_allowed: boolean | null;
  rev_lights_pct: number | null;
  ers_pct: number | null;
  ers_mode: "none" | "medium" | "hotlap" | "overtake" | string | null;
  fuel_kg: number | null;
  fuel_laps: number | null;
  pit_limiter: boolean | null;
  steer: number | null;
  g_lat: number | null;
  g_long: number | null;
  tyre_surface_c: PerWheel | null;
  tyre_inner_c: PerWheel | null;
  tyre_pressure_psi: PerWheel | null;
  tyre_wear_pct: PerWheel | null;
  brake_c: PerWheel | null;
  damage: Record<string, number> | null;
  top_speed_lap_kph: number | null;
  top_speed_kph: number | null;
  /** Degrees the car points away from its direction of travel (how sideways it is). */
  slide_deg?: number | null;
  /** Slides caught this session, and the latest one ("SAVE!"). */
  saves?: number;
  last_save_at?: number | null;
  last_save_peak_deg?: number | null;
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
  /** The car's rev limit (added in v1; older hubs don't send it). */
  max_rpm?: number | null;
  tyre: Tyre | null;
  lap: LiveLap | null;
  best: BestLap | null;
  /** The driver's fastest valid lap on this track ever (added in v1; older hubs don't send it). */
  personal_best?: BestLap | null;
  car?: CarDetail | null;
  /** Added in v1 (optional): the staff session on this rig (who, and the booking end). */
  booking?: Booking | null;
}

export interface Booking {
  driver: string;
  started_at: number;
  /** Unix ms when the booked time runs out; null = no timer. */
  ends_at: number | null;
}

/** Added in v1 (optional): someone waiting for a rig. Names only. */
export interface QueueEntry {
  id: number;
  name: string;
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
  /** Added in v1 (optional): "pro" = every assist off for the whole lap; missing = "open". */
  lap_class?: LapClass | string;
}

export type LapClass = "pro" | "open";

/** Added in v1 (optional): switches from [features] in the hub config. Missing = on. */
export interface Features {
  moments: boolean;
  battles: boolean;
  podium: boolean;
  attract: boolean;
  portrait: boolean;
  head_to_head: boolean;
  onboard: boolean;
}

export interface RecordBroken {
  period: "all_time" | "today" | string;
  lap_class: LapClass | string;
  previous_ms: number;
  previous_driver: string | null;
  gap_ms: number;
}

export interface NowDrivingMoment {
  kind: "now_driving";
  at: number;
  rig_id: string;
  rig_name: string;
  driver: string;
  track_key: string | null;
  track_name: string | null;
  today_record: { driver: string | null; lap_ms: number } | null;
  personal_best_ms: number | null;
}

export interface RecordMoment {
  kind: "record";
  at: number;
  rig_id: string;
  driver: string | null;
  track_key: string;
  track_name: string | null;
  lap_ms: number;
  lap_class: LapClass | string;
  records: RecordBroken[];
}

export interface PodiumMoment {
  kind: "podium";
  at: number;
  reason: "hourly" | "scheduled" | "staff" | string;
  track_key: string;
  track_name: string | null;
  entries: LeaderboardEntry[];
}

/** Added in v1 (optional): a full-screen broadcast moment. Unknown kinds are ignored. */
export type Moment = NowDrivingMoment | RecordMoment | PodiumMoment;
export const MOMENT_KINDS: ReadonlySet<string> = new Set(["now_driving", "record", "podium"]);

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
  hub: {
    version: string;
    games: string[];
    frame_hz: number;
    /** Added in v1 (optional): where games should send telemetry. */
    udp_port?: number;
    lan_address?: string | null;
    /** Lock-to-lock rotation of the steering wheel graphic. */
    steering_rotation_deg?: number;
    features?: Partial<Features>;
    moments?: { battle_margin_ms: number };
    sounds?: { enabled: boolean; volume: number };
  };
  cafe: { name: string; branding: Record<string, string> };
  status: HubStatus;
  rigs: RigInfo[];
  frame: { rigs: RigFrame[]; comparison: Comparison | null };
  outlines: TrackOutline[];
  /** One board per period for the shown track; empty while no track is known. */
  leaderboards: Leaderboard[];
  recent_laps: LapRecord[];
  /** Added in v1 (optional): the waiting queue, first first. */
  queue?: QueueEntry[];
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

export interface MomentMessage extends Envelope<"moment"> {
  moment: Moment;
}

export interface QueueMessage extends Envelope<"queue"> {
  queue: QueueEntry[];
}

export type HubMessage =
  | SnapshotMessage
  | FrameMessage
  | RigInfoMessage
  | StatusMessage
  | SessionChangedMessage
  | TrackOutlineMessage
  | LapCompletedMessage
  | LeaderboardMessage
  | MomentMessage
  | QueueMessage;

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
  "moment",
  "queue",
]);
