// @vitest-environment jsdom
// The licence on the TV (factory spec 2.3): the vendor mark follows hub.vendor_mark, and the TV never shows a rig
// the hub didn't describe in rig_info (rigs beyond the licence are left out of the feed; this is the TV's guard).
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { App, WIPE_MS } from "./App";
import { DEFAULT_MOCK_OPTIONS, MockHub } from "./mock/sim";
import type { FrameMessage, HubMessage, RigFrame, SnapshotMessage } from "./schema";
import { applyMessage, initialState } from "./state/reducer";
import { DashboardStore } from "./state/store";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

class NoResize {
  observe() {}
  unobserve() {}
  disconnect() {}
}

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("ResizeObserver", NoResize);
  HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const GHOST = "rig-ghost";
const GHOST_DRIVER = "GHOSTLY DRIVER";

function ghostOf(frame: RigFrame): RigFrame {
  return { ...frame, rig_id: GHOST, driver: GHOST_DRIVER };
}

/** A store fed by the mock hub; `edit` changes each snapshot, `ghost` adds a rig to every frame that is not in rig_info. */
function fedStore({ edit, ghost = false }: { edit?: (s: SnapshotMessage) => SnapshotMessage; ghost?: boolean } = {}) {
  let clock = 1_791_300_000_000;
  const hub = new MockHub({ ...DEFAULT_MOCK_OPTIONS, rigs: 2 }, () => clock);
  const store = new DashboardStore("mock");
  const withGhost = (msg: HubMessage): HubMessage => {
    if (!ghost) return msg;
    if (msg.type === "frame" && msg.rigs[0]) {
      const comparison = msg.comparison && {
        ...msg.comparison,
        rigs: [...msg.comparison.rigs, { rig_id: GHOST, reference_rig_id: null, best_gap_ms: -500, live_delta_ms: -100 }],
      };
      return { ...msg, rigs: [...msg.rigs, ghostOf(msg.rigs[0])], comparison } as FrameMessage;
    }
    return msg;
  };
  let snapshot = hub.snapshot() as SnapshotMessage;
  if (edit) snapshot = edit(snapshot);
  if (ghost) snapshot = { ...snapshot, frame: { ...snapshot.frame, rigs: [...snapshot.frame.rigs, ghostOf(snapshot.frame.rigs[0]!)] } };
  store.dispatch(snapshot);
  const tick = () => {
    clock += 67;
    for (const msg of hub.step(1000 / 15)) store.dispatch(withGhost(msg as HubMessage));
  };
  for (let i = 0; i < 4 * 15; i++) tick();
  return { store, tick };
}

function withVendorMark(value: boolean | undefined) {
  return (s: SnapshotMessage): SnapshotMessage => {
    const hub = { ...s.hub };
    if (value === undefined) delete hub.vendor_mark;
    else hub.vendor_mark = value;
    return { ...s, hub };
  };
}

describe("vendor mark", () => {
  test.each([
    [true, true],
    [false, false],
    [undefined, true], // an older hub that doesn't send it: keep the mark
  ])("hub.vendor_mark %s: POWERED BY shown is %s", (value, shown) => {
    const { store } = fedStore({ edit: withVendorMark(value) });
    expect(store.getState().vendorMark).toBe(shown);
    act(() => root.render(<App store={store} />));
    expect(host.querySelector(".app__view > main")?.className).toContain("live");
    expect(host.querySelector(".pw-powered") !== null).toBe(shown);
    expect(host.querySelector(".pwlogo") !== null).toBe(shown);
    expect(host.textContent?.includes("POWERED BY")).toBe(shown);
    // The rest of the header stays: the cafe's name and the clock.
    expect(host.querySelector(".pw-cafe__name")?.textContent).toBe("SIM RACING CAFE");
    expect(host.querySelector(".pw-clock")).not.toBeNull();
  });

  test("no view shows the mark when vendor_mark is false", () => {
    const { store } = fedStore({ edit: withVendorMark(false) });
    act(() => root.render(<App store={store} />));
    for (const key of ["2", "1"]) {
      act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key })); });
      act(() => { vi.advanceTimersByTime(WIPE_MS + 50); });
      expect(host.textContent).not.toContain("POWERED BY");
      expect(host.querySelector(".pwlogo, .pwmark")).toBeNull();
    }
  });

  test("a fresh snapshot (new licence code) switches the mark on the same connection", () => {
    const { store } = fedStore({ edit: withVendorMark(true) });
    act(() => root.render(<App store={store} />));
    expect(host.querySelector(".pw-powered")).not.toBeNull();
    const hub = new MockHub({ ...DEFAULT_MOCK_OPTIONS, rigs: 2 }, () => 1_791_300_100_000);
    act(() => store.dispatch(withVendorMark(false)(hub.snapshot() as SnapshotMessage)));
    expect(host.querySelector(".pw-powered")).toBeNull();
  });
});

describe("rigs missing from rig_info", () => {
  test("a frame for a rig the hub didn't describe is not kept", () => {
    const hub = new MockHub({ ...DEFAULT_MOCK_OPTIONS, rigs: 2 }, () => 1_791_300_000_000);
    const snapshot = hub.snapshot() as SnapshotMessage;
    let s = applyMessage(initialState("hub"), {
      ...snapshot,
      frame: { ...snapshot.frame, rigs: [...snapshot.frame.rigs, ghostOf(snapshot.frame.rigs[0]!)] },
    }, 0);
    const ids = snapshot.rigs.map((r) => r.rig_id).sort();
    expect(ids).not.toContain(GHOST);
    expect(Object.keys(s.frames).sort()).toEqual(ids);
    const frame: FrameMessage = { v: snapshot.v, type: "frame", seq: snapshot.seq + 1, ts: snapshot.ts,
      rigs: [...snapshot.frame.rigs, ghostOf(snapshot.frame.rigs[0]!)],
      comparison: { track_key: "t", rigs: [
        { rig_id: "rig-1", reference_rig_id: GHOST, best_gap_ms: 100, live_delta_ms: 50 },
        { rig_id: GHOST, reference_rig_id: null, best_gap_ms: null, live_delta_ms: null }] } };
    s = applyMessage(s, frame, 1);
    expect(Object.keys(s.frames).sort()).toEqual(ids);
    expect(s.comparison?.rigs).toEqual([{ rig_id: "rig-1", reference_rig_id: null, best_gap_ms: 100, live_delta_ms: 50 }]);
    // Once the hub describes the rig (rig_info comes before its frames), it is shown.
    const info = { ...snapshot.rigs[0]!, rig_id: GHOST, name: "Rig 9" };
    s = applyMessage(s, { v: snapshot.v, type: "rig_info", seq: snapshot.seq + 2, ts: snapshot.ts, rig: info }, 2);
    s = applyMessage(s, { ...frame, seq: snapshot.seq + 3 }, 3);
    expect(Object.keys(s.frames).sort()).toEqual([...ids, GHOST].sort());
  });

  test("the TV never renders a rig missing from rig_info", () => {
    const { store, tick } = fedStore({ ghost: true });
    const ids = store.getState().rigs.map((r) => r.rig_id);
    expect(ids).not.toContain(GHOST);
    expect(Object.keys(store.getState().frames).sort()).toEqual([...ids].sort());
    expect(store.live.history(GHOST)).toHaveLength(0);
    expect(store.trails.get(GHOST)).toHaveLength(0);
    act(() => root.render(<App store={store} />));
    for (const key of ["1", "2", "1"]) {
      act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key })); });
      act(() => { vi.advanceTimersByTime(WIPE_MS + 50); });
      act(() => { for (let i = 0; i < 15; i++) tick(); });
      expect(host.textContent?.toUpperCase()).not.toContain(GHOST_DRIVER);
    }
    act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "1" })); });
    act(() => { vi.advanceTimersByTime(WIPE_MS + 50); });
    // The LIVE header counts only the described rigs that are sending.
    const live = Number(/(\d+) RIGS? LIVE/.exec(host.textContent ?? "")?.[1]);
    expect(live).toBeLessThanOrEqual(ids.length);
  });
});
