import { useSyncExternalStore } from "react";
import type { HubMessage } from "../schema";
import { applyMessage, initialState, type DashboardState, type LinkState } from "./reducer";
import { LapShareTracker } from "./lapshare";
import { LapTraceTracker } from "./laptrace";
import { LiveTelemetry } from "./live";
import { PathTrace } from "./paths";
import { TrailBuffer } from "./trails";

/** Friction-circle trail length: about 2 s at 15 frames per second. */
export const G_TRAIL_SAMPLES = 30;

/** Holds dashboard state for React and the position trails for the map canvas. */
export class DashboardStore {
  private state: DashboardState;
  private readonly listeners = new Set<() => void>();
  readonly trails = new TrailBuffer();
  readonly paths = new PathTrace();
  readonly lapShare = new LapShareTracker();
  /** Mini-sectors and speed traces per lap (race map colours, head to head). */
  readonly laps = new LapTraceTracker();
  /** Input history, delta to own best and speed traces per rig (LIVE and MULTIVIEW pages). */
  readonly live = new LiveTelemetry();
  /** Recent (lateral, longitudinal) g per rig, newest last: the friction-circle trail. */
  readonly gTrail = new Map<string, [number, number][]>();

  constructor(source: DashboardState["source"]) {
    this.state = initialState(source);
  }

  getState = (): DashboardState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  dispatch(msg: HubMessage, now = performance.now()): void {
    if (msg.type === "snapshot") {
      this.trails.clear();
      this.paths.clear();
      this.lapShare.clear();
      this.gTrail.clear();
      this.laps.clear();
      this.live.clear();
    }
    if (msg.type === "session_changed") {
      this.trails.clear(msg.rig_id);
      this.laps.clear(msg.rig_id);
    }
    this.state = applyMessage(this.state, msg, now);
    if (this.state.link === "version_mismatch") {
      this.emit();
      return;
    }
    if (msg.type === "snapshot" || msg.type === "frame") {
      const frames = msg.type === "snapshot" ? msg.frame.rigs : msg.rigs;
      for (const frame of frames) {
        this.lapShare.add(frame);
        this.laps.add(frame);
        this.live.add(frame, now);
        this.addG(frame.rig_id, frame.state === "driving" ? frame.car ?? null : null);
        if (!frame.position) continue;
        this.trails.add(frame.rig_id, now, frame.position.x, frame.position.z);
        if (frame.session.track_key) {
          this.paths.add(frame.session.track_key, frame.rig_id, frame.position.x, frame.position.z);
        }
      }
    }
    this.emit();
  }

  private addG(rigId: string, car: { g_lat: number | null; g_long: number | null } | null): void {
    const trail = this.gTrail.get(rigId) ?? [];
    if (car?.g_lat == null || car.g_long == null) {
      if (trail.length) this.gTrail.set(rigId, []);
      return;
    }
    trail.push([car.g_lat, car.g_long]);
    if (trail.length > G_TRAIL_SAMPLES) trail.splice(0, trail.length - G_TRAIL_SAMPLES);
    this.gTrail.set(rigId, trail);
  }

  /** The moment at the head of the queue has been shown. */
  shiftMoment(at: number): void {
    if (this.state.moments[0]?.at !== at) return;
    this.state = { ...this.state, moments: this.state.moments.slice(1) };
    this.emit();
  }

  setLink(link: LinkState): void {
    if (this.state.link === link || this.state.link === "version_mismatch") return;
    this.state = { ...this.state, link };
    this.emit();
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }
}

export function useDashboard(store: DashboardStore): DashboardState {
  return useSyncExternalStore(store.subscribe, store.getState);
}
