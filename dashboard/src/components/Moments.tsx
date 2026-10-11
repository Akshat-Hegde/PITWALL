import { useEffect, useRef, useState } from "react";
import { formatDelta, formatLapTime } from "../format";
import type { Moment, NowDrivingMoment, PodiumMoment, RecordMoment, RigInfo } from "../schema";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { playSound } from "../sounds";
import { findBattle } from "./Battle";
import { ChallengeWinner } from "./Competition";
import { Avatar, KineticType, StripeBundle, Tab } from "./Motifs";

/** How long each moment stays on screen (DESIGN.md §4). */
export const MOMENT_MS: Record<Moment["kind"], number> = {
  now_driving: 4000, record: 6000, podium: 10000, challenge_winner: 10000,
};
export const BATTLE_POPUP_MS = 5000;
/** A pair (or "on course") pop-up isn't repeated within this time. */
export const BATTLE_REPEAT_MS = 120_000;

/** Full-screen moments from the hub, one at a time, over whatever view is showing. */
export function MomentLayer({ store, state }: { store: DashboardStore; state: DashboardState }) {
  const moment = state.moments[0] ?? null;
  useEffect(() => {
    if (!moment) return;
    if (state.sounds.enabled && moment.kind !== "podium") {
      playSound(moment.kind === "record" ? "record" : "session_start", state.sounds.volume);
    }
    const timer = setTimeout(() => store.shiftMoment(moment.at), MOMENT_MS[moment.kind] ?? 5000);
    return () => clearTimeout(timer);
  }, [moment, store, state.sounds.enabled, state.sounds.volume]);
  if (!moment) return null;
  const colour = (rigId: string) => state.rigs.find((r) => r.rig_id === rigId)?.colour ?? "var(--text-3)";
  return (
    <div className={`moment moment--${moment.kind}`} role="status" key={moment.at}>
      <StripeBundle corner="top-left" className="moment__stripes" />
      {moment.kind === "now_driving" && <NowDriving m={moment} colour={colour(moment.rig_id)} />}
      {moment.kind === "record" && <RecordBroken m={moment} colour={colour(moment.rig_id)} />}
      {moment.kind === "podium" && <Podium m={moment} colour={colour} />}
      {moment.kind === "challenge_winner" && <ChallengeWinner m={moment} />}
    </div>
  );
}

function NowDriving({ m, colour }: { m: NowDrivingMoment; colour: string }) {
  return (
    <>
      <KineticType words={["Now", "driving"]} />
      <section className="moment__card cutcard streaks" style={{ "--rig-colour": colour } as React.CSSProperties}>
        <span className="kerb moment__kerb" aria-hidden="true" />
        <div className="moment__who">
          <Avatar name={m.driver} className="avatar--xl" />
          <div>
            <Tab left={m.rig_name} right="Now driving" />
            <h1 className="moment__name">{m.driver}</h1>
            {m.track_name && <span className="moment__sub">{m.track_name}</span>}
          </div>
        </div>
        <div className="moment__stats">
          <div className="field">
            <span className="label">Today's record</span>
            <span className="moment__value c-purple">{formatLapTime(m.today_record?.lap_ms ?? null)}</span>
            <span className="t2">{m.today_record ? m.today_record.driver : "Not set yet: take it"}</span>
          </div>
          <div className="field">
            <span className="label">Personal best here</span>
            <span className="moment__value">{formatLapTime(m.personal_best_ms)}</span>
            <span className="t2">{m.personal_best_ms == null ? "First time on this track" : "Beat it"}</span>
          </div>
        </div>
      </section>
    </>
  );
}

const PERIOD_TEXT: Record<string, string> = { all_time: "Track record", today: "Today's record" };

function RecordBroken({ m, colour }: { m: RecordMoment; colour: string }) {
  const main = m.records[0];
  return (
    <>
      <KineticType words={main?.period === "all_time" ? ["Track", "record"] : ["New", "record"]} />
      <section className="moment__card moment__card--record cutcard streaks"
               style={{ "--rig-colour": colour } as React.CSSProperties}>
        <span className="chequer moment__chequer" aria-hidden="true" />
        <div className="moment__who">
          <Avatar name={m.driver ?? "?"} className="avatar--xl" />
          <div>
            <Tab left={PERIOD_TEXT[main?.period ?? ""] ?? "Record"} right={m.lap_class === "pro" ? "Pro" : "Open"} />
            <h1 className="moment__name">{m.driver ?? "Driver"}</h1>
            {m.track_name && <span className="moment__sub">{m.track_name}</span>}
          </div>
        </div>
        <div className="moment__time c-purple">{formatLapTime(m.lap_ms)}</div>
        {main && (
          <div className="moment__gap">
            <span className="moment__gap-value">{formatDelta(main.gap_ms)}</span>
            <span className="t2">
              faster than {main.previous_driver ?? "the old record"} ({formatLapTime(main.previous_ms)})
            </span>
          </div>
        )}
        <ul className="moment__records">
          {m.records.map((r) => (
            <li key={`${r.period}-${r.lap_class}`}>
              <Tab left={PERIOD_TEXT[r.period] ?? r.period} right={r.lap_class === "pro" ? "Pro" : "Open"}
                   className="tab-badge--muted" />
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function Podium({ m, colour }: { m: PodiumMoment; colour: (rigId: string) => string }) {
  const order = [1, 0, 2].filter((i) => m.entries[i]); // P2, P1, P3 like a podium
  return (
    <>
      <header className="podium__head">
        <Tab left="Podium" right={m.reason === "staff" ? "Today" : "This hour"} />
        <h1 className="podium__title">{m.track_name ?? "Today"}</h1>
      </header>
      <div className="podium">
        {order.map((i) => {
          const e = m.entries[i]!;
          return (
            <section key={e.rank} className={`podium__step podium__step--p${e.rank} cutcard`}
                     style={{ "--rig-colour": colour(e.rig_id) } as React.CSSProperties}>
              {e.rank === 1 && <span className="chequer podium__chequer" aria-hidden="true" />}
              <span className="podium__pos">P{e.rank}</span>
              <Avatar name={e.driver ?? e.rig_name} className="avatar--l" />
              <span className="podium__name">{e.driver ?? e.rig_name}</span>
              <span className={`podium__time${e.rank === 1 ? " c-purple" : ""}`}>{formatLapTime(e.lap_ms)}</span>
              <span className="t2">{e.rank === 1 ? e.rig_name : formatDelta(e.gap_ms)}</span>
            </section>
          );
        })}
      </div>
    </>
  );
}

// ---- Battle pop-ups --------------------------------------------------------------------------------

interface Popup {
  key: string;
  title: string;
  text: string;
  rigs: RigInfo[];
}

/** Lower-third pop-up: two best laps within the margin, or a driver on course to beat the leader. */
export function BattlePopups({ state, trackKey }: { state: DashboardState; trackKey: string | null }) {
  const [popup, setPopup] = useState<Popup | null>(null);
  const shown = useRef(new Map<string, number>());
  const candidate = battleCandidate(state, trackKey);
  useEffect(() => {
    if (!candidate || popup) return;
    const now = performance.now();
    const last = shown.current.get(candidate.key);
    if (last !== undefined && now - last < BATTLE_REPEAT_MS) return;
    shown.current.set(candidate.key, now);
    setPopup(candidate);
  }, [candidate?.key, popup]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!popup) return;
    const timer = setTimeout(() => setPopup(null), BATTLE_POPUP_MS);
    return () => clearTimeout(timer);
  }, [popup]);
  if (!popup || !state.features.battles) return null;
  return (
    <aside className="popup cutcard" role="status">
      <span className="kerb popup__kerb" aria-hidden="true" />
      <Tab left="Battle" right={popup.title} />
      <div className="popup__body">
        {popup.rigs.map((r) => (
          <span key={r.rig_id} className="popup__who" style={{ "--rig-colour": r.colour } as React.CSSProperties}>
            <span className="stripe" aria-hidden="true" />
            {state.frames[r.rig_id]?.driver ?? r.name}
          </span>
        ))}
        <span className="popup__text">{popup.text}</span>
      </div>
    </aside>
  );
}

/** What deserves a pop-up right now, if anything. Exported for tests. */
export function battleCandidate(state: DashboardState, trackKey: string | null): Popup | null {
  if (!state.features.battles || !trackKey) return null;
  const rig = (id: string) => state.rigs.find((r) => r.rig_id === id);
  // On course to beat the leader: live delta to the fastest other rig's best, past 40 % of the lap.
  const bests = state.rigs
    .map((r) => ({ r, ms: state.frames[r.rig_id]?.best?.lap_ms ?? null }))
    .filter((x) => x.ms != null && state.frames[x.r.rig_id]?.session.track_key === trackKey)
    .sort((a, b) => a.ms! - b.ms!);
  const leader = bests[0]?.r;
  const length = state.frames[leader?.rig_id ?? ""]?.session.track_length_m ?? null;
  for (const e of state.comparison?.rigs ?? []) {
    const f = state.frames[e.rig_id];
    if (!leader || e.reference_rig_id !== leader.rig_id || e.live_delta_ms == null || e.live_delta_ms >= 0) continue;
    if (!f?.lap || !length || f.lap.distance_m < length * 0.4) continue;
    const chaser = rig(e.rig_id);
    if (!chaser) continue;
    return {
      key: `course-${e.rig_id}-${f.lap.number}`,
      title: "On course for P1",
      text: `${formatDelta(e.live_delta_ms, 2)} up on the fastest lap`,
      rigs: [chaser, leader],
    };
  }
  const battle = findBattle(state, trackKey);
  if (battle && battle.gapMs <= state.battleMarginMs) {
    const a = rig(battle.leader.rigId);
    const b = rig(battle.chaser.rigId);
    if (a && b) {
      return {
        key: `pair-${a.rig_id}-${b.rig_id}`,
        title: "Close fight",
        text: `${formatDelta(battle.gapMs)} apart on best laps`,
        rigs: [a, b],
      };
    }
  }
  return null;
}
