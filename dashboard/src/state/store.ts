import { useSyncExternalStore } from "react";
import type { HubMessage } from "../schema";
import { applyMessage, initialState, type DashboardState, type LinkState } from "./reducer";
import { PathTrace } from "./paths";
import { TrailBuffer } from "./trails";

/** Holds dashboard state for React and the position trails for the map canvas. */
export class DashboardStore {
  private state: DashboardState;
  private readonly listeners = new Set<() => void>();
  readonly trails = new TrailBuffer();
  readonly paths = new PathTrace();

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
    }
    if (msg.type === "session_changed") this.trails.clear(msg.rig_id);
    this.state = applyMessage(this.state, msg, now);
    if (this.state.link === "version_mismatch") {
      this.emit();
      return;
    }
    if (msg.type === "snapshot" || msg.type === "frame") {
      const frames = msg.type === "snapshot" ? msg.frame.rigs : msg.rigs;
      for (const frame of frames) {
        if (!frame.position) continue;
        this.trails.add(frame.rig_id, now, frame.position.x, frame.position.z);
        if (frame.session.track_key) {
          this.paths.add(frame.session.track_key, frame.rig_id, frame.position.x, frame.position.z);
        }
      }
    }
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
