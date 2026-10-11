import { describe, expect, test } from "vitest";
import { chooseDuel, distinctColours } from "./components/Analysis";
import { challengeWhen } from "./components/Competition";
import { LapTraceTracker } from "./state/laptrace";
import { battleCandidate } from "./components/Moments";
import { DEFAULT_MOCK_OPTIONS, MockHub } from "./mock/sim";
import type { HubMessage, Moment } from "./schema";
import { ALL_FEATURES, applyMessage, initialState, type DashboardState } from "./state/reducer";
import { DashboardStore } from "./state/store";
import { validateMessage } from "./testing/validate";
import { ATTRACT_HERO_MS, IDLE_AFTER_MS, chooseView } from "./views";

function run(seconds: number, options = DEFAULT_MOCK_OPTIONS): HubMessage[] {
  let clock = 1_791_300_000_000;
  const hub = new MockHub(options, () => clock);
  const out: HubMessage[] = [hub.snapshot()];
  for (let t = 0; t < seconds * 15; t++) {
    clock += 67;
    out.push(...hub.step(1000 / 15));
  }
  return out;
}

const moment = (kind: string, at: number) =>
  ({ v: 1, type: "moment", seq: 1, ts: at, moment: { kind, at } }) as unknown as HubMessage;

describe("moments", () => {
  test("the mock sends valid now-driving, record and podium moments", () => {
    const msgs = run(400, { ...DEFAULT_MOCK_OPTIONS, rigs: 4, pastDrivers: 6, podiumEveryMs: 60_000 });
    const kinds = new Set(msgs.filter((m) => m.type === "moment").map((m) => (m as { moment: Moment }).moment.kind));
    expect(kinds).toEqual(new Set(["now_driving", "record", "podium"]));
    for (const m of msgs.filter((x) => x.type === "moment")) expect(validateMessage(m)).toEqual([]);
  });

  test("moments queue up, unknown kinds and switched-off features are dropped", () => {
    let s: DashboardState = { ...initialState("hub"), link: "live", receivedVersion: 1 };
    s = applyMessage(s, moment("now_driving", 1), 0);
    s = applyMessage(s, moment("fireworks", 2), 0);
    s = applyMessage(s, moment("podium", 3), 0);
    expect(s.moments.map((m) => m.at)).toEqual([1, 3]);
    s = { ...s, features: { ...ALL_FEATURES, moments: false } };
    s = applyMessage(s, moment("record", 4), 0);
    expect(s.moments).toHaveLength(2);
  });

  test("the store removes a moment once it has been shown", () => {
    const store = new DashboardStore("mock");
    store.dispatch(run(0)[0]!);
    store.dispatch(moment("now_driving", 10));
    store.shiftMoment(99); // not the head: ignored
    expect(store.getState().moments).toHaveLength(1);
    store.shiftMoment(10);
    expect(store.getState().moments).toHaveLength(0);
  });

  test("snapshot settings: features, battle margin, sounds", () => {
    const store = new DashboardStore("mock");
    store.dispatch(run(0)[0]!);
    const s = store.getState();
    expect(s.features.attract).toBe(true);
    expect(s.battleMarginMs).toBe(300);
    expect(s.sounds.enabled).toBe(false);
  });
});

describe("battle pop-ups", () => {
  test("a close pair of best laps makes a pop-up; a wide gap doesn't", () => {
    const store = new DashboardStore("mock");
    for (const m of run(300, { ...DEFAULT_MOCK_OPTIONS, rigs: 2 })) store.dispatch(m);
    const s = store.getState();
    const track = Object.values(s.frames)[0]!.session.track_key;
    const wide = battleCandidate({ ...s, battleMarginMs: 0, comparison: null }, track);
    expect(wide).toBeNull();
    const close = battleCandidate({ ...s, battleMarginMs: 60_000, comparison: null }, track);
    expect(close?.title).toBe("Close fight");
    expect(battleCandidate({ ...s, battleMarginMs: 60_000, features: { ...ALL_FEATURES, battles: false } }, track))
      .toBeNull();
  });
});

describe("attract rotation", () => {
  test("idle: the branded attract screen comes first when switched on", () => {
    const idle = IDLE_AFTER_MS + 1;
    expect(chooseView("auto", idle, 0, { analysis: false, onboard: false, attract: true }).view).toBe("attract");
    expect(chooseView("auto", idle + ATTRACT_HERO_MS, 0, { analysis: false, onboard: false, attract: true }).view)
      .toBe("board");
    expect(chooseView("auto", idle, 0, { analysis: false, onboard: false, attract: false }).view).toBe("board");
  });
});

describe("story cards", () => {
  test("a card moment goes to the QR list, not the full-screen queue; off when sharing is off", () => {
    const card = { v: 1, type: "moment", seq: 1, ts: 5, moment: { kind: "card", at: 5, rig_id: "r", driver: "Maya",
      token: "t", url: "http://hub/card/t", best_ms: 88000, track_name: null } } as unknown as HubMessage;
    let s: DashboardState = { ...initialState("hub"), link: "live", receivedVersion: 1 };
    s = applyMessage(s, card, 0);
    expect(s.cards.map((c) => c.token)).toEqual(["t"]);
    expect(s.moments).toEqual([]);
    s = applyMessage({ ...s, cards: [], features: { ...ALL_FEATURES, sharing: false } }, card, 0);
    expect(s.cards).toEqual([]);
  });
});

describe("Pro boards and challenges", () => {
  test("Pro boards are kept apart from Open boards", () => {
    const store = new DashboardStore("mock");
    for (const m of run(200, { ...DEFAULT_MOCK_OPTIONS, rigs: 3, pastDrivers: 6 })) store.dispatch(m);
    const s = store.getState();
    expect(s.leaderboards.today?.lap_class).toBe("open");
    expect(s.proLeaderboards.today?.lap_class).toBe("pro");
    expect(s.proLeaderboards.today!.entries.length).toBeLessThan(s.leaderboards.today!.entries.length);
    expect(s.competition.challenge?.lap_class).toBe("pro");
  });

  test("challenge time text", () => {
    const day = 24 * 3600_000;
    const base = { id: 1, title: "", track_key: "", track_name: null, lap_class: "open", prize: "", entries: [] };
    expect(challengeWhen({ ...base, state: "running", starts_at: 0, ends_at: 3 * day }, 0.5 * day)).toBe("3 days left");
    expect(challengeWhen({ ...base, state: "running", starts_at: 0, ends_at: day }, day - 2 * 3600_000)).toBe("Ends in 2 h");
    expect(challengeWhen({ ...base, state: "upcoming", starts_at: 2 * day, ends_at: 9 * day }, 0)).toBe("Starts in 2 days");
  });
});

describe("head to head from the hub", () => {
  test("a fresh page shows the hub's pair at once, without having seen any lap", () => {
    const side = (rig: string, driver: string, ms: number, mini: number) => ({
      rig_id: rig, driver, lap_ms: ms, lap_number: 3, lap_class: "open", minis: Array(24).fill(mini),
      speed: Array.from({ length: 200 }, (_, i) => 200 + 80 * Math.sin(i / 10)),
      share: { full_throttle: 61, heavy_braking: 12, cornering: 30 } });
    let s: DashboardState = { ...initialState("hub"), link: "live", receivedVersion: 1 };
    s = applyMessage(s, { v: 1, type: "head_to_head", seq: 1, ts: 0, head_to_head: { track_key: "F1:7",
      track_name: "Silverstone", day: "2026-10-12", a: side("r1", "Maya", 88000, 3600), b: side("r2", "Kofi", 88200, 3610) },
    } as unknown as HubMessage, 0);
    const duel = chooseDuel(s, new LapTraceTracker(), "F1:7")!;
    expect([duel.a.name, duel.b.name]).toEqual(["Maya", "Kofi"]);
    expect(new Set(duel.who)).toEqual(new Set(["a"]));
    expect(duel.a.trace.share.fullThrottle).toBe(61);
    expect(chooseDuel(s, new LapTraceTracker(), "F1:10")).toBeNull();
  });
});

describe("head to head colours", () => {
  test("alike rig colours: the second driver gets a contrasting one", () => {
    expect(distinctColours("#36c5f0", "#ff8a3d")).toEqual(["#36c5f0", "#ff8a3d"]);   // already distinct
    const [a, b] = distinctColours("#e85fae", "#f06a6a");                            // pink vs salmon
    expect(a).toBe("#e85fae");
    expect(b).toBe("#3987e5");
  });
});
