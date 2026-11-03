import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { MockHub } from "../mock/sim";
import type { HubMessage } from "../schema";
import { DashboardStore } from "../state/store";
import { NO_DATA_MS, SILENT_RECONNECT_MS, webSocketSource } from "./sources";

/** A stand-in WebSocket: tests push messages into the newest one. */
class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }
  close() {
    this.closed = true;
  }
  send(msg: object) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

const latest = () => FakeSocket.all[FakeSocket.all.length - 1]!;

function snapshot(version = "0.5.0"): HubMessage {
  const snap = new MockHub().snapshot() as HubMessage & { hub: { version: string } };
  return { ...snap, seq: 0, hub: { ...snap.hub, version } } as HubMessage;
}

describe("hub link watchdog", () => {
  let clock = 0;
  let stop: (() => void) | null = null;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
    FakeSocket.all = [];
    clock = 0;
  });

  afterEach(() => {
    stop?.();
    stop = null;
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  const advance = (ms: number) => {
    for (let t = 0; t < ms; t += 100) {
      clock += 100;
      vi.advanceTimersByTime(100);
    }
  };

  function start(onHubChanged = vi.fn()) {
    const store = new DashboardStore("hub");
    stop = webSocketSource("ws://hub/ws", { clock: () => clock, onHubChanged })(store);
    return { store, onHubChanged };
  }

  test("a silent hub is dropped after 3 s and the TV reconnects", () => {
    start();
    latest().send(snapshot());
    expect(FakeSocket.all).toHaveLength(1);
    advance(SILENT_RECONNECT_MS - 500);
    expect(FakeSocket.all[0]!.closed).toBe(false);
    advance(2000); // past 3 s, plus the 0.5 s reconnect delay
    expect(FakeSocket.all[0]!.closed).toBe(true);
    expect(FakeSocket.all.length).toBeGreaterThanOrEqual(2);
  });

  test("messages keep the link up", () => {
    const { store } = start();
    const first = snapshot();
    latest().send(first);
    for (let seq = 1; seq <= 10; seq++) {
      advance(1000);
      latest().send({ v: 1, type: "status", seq, ts: Date.now(), status: store.getState().status });
    }
    expect(FakeSocket.all).toHaveLength(1);
  });

  test("after 10 s without frames every rig shows as no-data; a new snapshot brings them back", () => {
    const { store } = start();
    latest().send(snapshot());
    expect(Object.keys(store.getState().frames).length).toBeGreaterThan(0);
    advance(NO_DATA_MS - 1000);
    expect(Object.keys(store.getState().frames).length).toBeGreaterThan(0);
    advance(1500);
    expect(store.getState().frames).toEqual({});
    // The watchdog keeps reconnecting meanwhile: answer on the socket it is currently using.
    while (!latest().onmessage) advance(100);
    latest().send(snapshot());
    expect(Object.keys(store.getState().frames).length).toBeGreaterThan(0);
  });

  test("a second snapshot on the same connection (a new licence) replaces all state, with no reconnect", () => {
    const { store } = start();
    latest().send(snapshot());
    latest().send({ v: 1, type: "status", seq: 1, ts: Date.now(), status: store.getState().status });
    const again = snapshot() as HubMessage & { cafe: { name: string } };
    latest().send({ ...again, seq: 2, cafe: { ...again.cafe, name: "Apex Lounge" } });
    expect(store.getState().cafe?.name).toBe("Apex Lounge");
    latest().send({ v: 1, type: "status", seq: 3, ts: Date.now(), status: store.getState().status });
    expect(FakeSocket.all).toHaveLength(1);
    expect(FakeSocket.all[0]!.closed).toBe(false);
    expect(store.getState().link).toBe("live");
  });

  test("a changed hub version or schema asks for a reload", () => {
    const { onHubChanged } = start();
    latest().send(snapshot("0.5.0"));
    expect(onHubChanged).not.toHaveBeenCalled();
    latest().close();
    latest().onclose?.();
    advance(600);
    latest().send(snapshot("0.5.0"));
    expect(onHubChanged).not.toHaveBeenCalled();
    latest().onclose?.();
    advance(1200);
    latest().send(snapshot("0.6.0"));
    expect(onHubChanged).toHaveBeenCalledTimes(1);
    latest().send({ v: 2, type: "status", seq: 1, ts: Date.now() });
    expect(onHubChanged).toHaveBeenCalledTimes(2);
  });
});
