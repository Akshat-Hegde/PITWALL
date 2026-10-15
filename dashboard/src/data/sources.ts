import { MockHub, mockOptionsFromQuery } from "../mock/sim";
import { SCHEMA_VERSION, type HubMessage } from "../schema";
import type { DashboardStore } from "../state/store";
import { requestReload } from "./reload";

/** Starts feeding the store; returns a function that stops it. */
export type DataSource = (store: DashboardStore) => () => void;

/** Built-in simulation: no hub needed. ?speed=N runs the simulation N times faster. */
export function mockSource(query: URLSearchParams): DataSource {
  return (store) => {
    const options = mockOptionsFromQuery(query);
    const speed = Math.max(0.1, Number(query.get("speed") ?? 1) || 1);
    const hub = new MockHub(options);
    store.dispatch(hub.snapshot());
    const forced = query.get("moment");
    const tickMs = 1000 / options.frameHz;
    let forceAfterMs = forced ? Number(query.get("momentAfter") ?? 0) * 1000 : -1;
    // Demo mode (?demo=1): a scripted loop of moments on top of the simulation, in real seconds.
    const demo = query.get("demo") === "1";
    const DEMO_LOOP_S = 240;
    const timeline: [number, string][] = [[20, "now_driving"], [70, "card"], [130, "record"], [200, "challenge_winner"]];
    let demoClockS = 0;
    const timer = setInterval(() => {
      for (const msg of hub.step(tickMs * speed)) store.dispatch(msg);
      if (demo) {
        const before = demoClockS % DEMO_LOOP_S;
        demoClockS += tickMs / 1000;
        const after = demoClockS % DEMO_LOOP_S;
        for (const [at, kind] of timeline) {
          if (before < at && after >= at) {
            const msg = hub.forceMoment(kind);
            if (msg) store.dispatch(msg);
          }
        }
      }
      if (forced && forceAfterMs >= 0) {
        forceAfterMs -= tickMs;
        if (forceAfterMs < 0) {
          const msg = hub.forceMoment(forced);
          if (msg) store.dispatch(msg);
        }
      }
    }, tickMs);
    return () => clearInterval(timer);
  };
}

/** No message from the hub for this long (it sends a status at least every second): drop the link, reconnect. */
export const SILENT_RECONNECT_MS = 3_000;
/** No frames for this long: show every rig as no-data (the waiting or attract screen), never frozen cars. */
export const NO_DATA_MS = 10_000;
/** How often the watchdog looks. */
export const WATCHDOG_TICK_MS = 500;

export interface WebSocketSourceOptions {
  /** Monotonic clock, ms (tests pass a fake one). */
  clock?: () => number;
  /** The hub was updated (its version changed) or speaks another schema version. Default: reload the page. */
  onHubChanged?: () => void;
}

/**
 * Live hub over WebSocket, with reconnect (0.5 s doubling to 5 s) and a fresh snapshot each time. A watchdog
 * reconnects when the hub goes quiet and hides the cars when no frames arrive. Nothing about the connection
 * is shown on the TV.
 */
export function webSocketSource(url: string, options: WebSocketSourceOptions = {}): DataSource {
  const clock = options.clock ?? (() => performance.now());
  const onHubChanged = options.onHubChanged ?? (() => void requestReload());
  return (store) => {
    let socket: WebSocket | null = null;
    let retryMs = 500;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let expectedSeq = 0;
    let stopped = false;
    let connectedBefore = false;
    let hubVersion: string | null = null;
    let lastMessageAt = clock();
    let lastDataAt = clock();

    const scheduleReconnect = () => {
      if (stopped || timer) return;
      store.setLink("reconnecting");
      timer = setTimeout(() => {
        timer = null;
        connect();
      }, retryMs);
      retryMs = Math.min(5000, retryMs * 2);
    };

    /** Forget a socket: its late events are ignored, so a hung connection can't hold up the reconnect. */
    const drop = (s: WebSocket) => {
      s.onopen = null;
      s.onmessage = null;
      s.onclose = null;
      try {
        s.close();
      } catch {
        // already closed
      }
      if (socket === s) socket = null;
    };

    const connect = () => {
      store.setLink(connectedBefore ? "reconnecting" : "connecting");
      connectedBefore = true;
      expectedSeq = 0;
      lastMessageAt = clock(); // the new socket gets its own SILENT_RECONNECT_MS to say something
      const s = new WebSocket(url);
      socket = s;
      s.onopen = () => {
        retryMs = 500;
      };
      s.onmessage = (event) => {
        if (socket !== s) return;
        let msg: HubMessage;
        try {
          msg = JSON.parse(String(event.data)) as HubMessage;
        } catch {
          return; // not JSON: ignore
        }
        if (typeof msg !== "object" || msg === null || typeof msg.type !== "string") return;
        lastMessageAt = clock();
        if (msg.v !== SCHEMA_VERSION) {
          onHubChanged(); // the hub now speaks a schema this page can't read: a reload fetches the new page
          store.dispatch(msg);
          return;
        }
        if (msg.seq !== expectedSeq) {
          drop(s); // gap: lost messages, resync with a fresh snapshot
          scheduleReconnect();
          return;
        }
        expectedSeq += 1;
        if (msg.type === "snapshot") {
          const version = typeof msg.hub?.version === "string" ? msg.hub.version : null;
          if (version && hubVersion && version !== hubVersion) onHubChanged();
          hubVersion = version ?? hubVersion;
        }
        if (msg.type === "snapshot" || msg.type === "frame") lastDataAt = clock();
        store.dispatch(msg);
      };
      s.onclose = () => {
        if (socket !== s) return;
        socket = null;
        scheduleReconnect();
      };
    };

    const watchdog = setInterval(() => {
      if (stopped) return;
      const now = clock();
      if (socket && now - lastMessageAt >= SILENT_RECONNECT_MS) {
        drop(socket);
        scheduleReconnect();
      }
      if (now - lastDataAt >= NO_DATA_MS) store.dropFrames();
    }, WATCHDOG_TICK_MS);

    connect();
    return () => {
      stopped = true;
      clearInterval(watchdog);
      if (timer) clearTimeout(timer);
      if (socket) drop(socket);
    };
  };
}

/** ?source=mock|ws; defaults to the mock in `vite dev` and to the hub when served by the hub. */
export function chooseSource(query: URLSearchParams, isDev: boolean): { kind: "mock" | "hub"; source: DataSource } {
  const requested = query.get("source");
  const kind = requested === "mock" || requested === "ws" ? requested : isDev ? "mock" : "ws";
  if (kind === "mock") return { kind: "mock", source: mockSource(query) };
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return { kind: "hub", source: webSocketSource(`${proto}//${location.host}/ws`) };
}
