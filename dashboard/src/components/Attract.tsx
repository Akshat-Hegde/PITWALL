import { formatLapTime } from "../format";
import type { LeaderboardEntry } from "../schema";
import type { DashboardState } from "../state/reducer";
import { LeaderboardPanel } from "./LeaderboardPanel";
import { Avatar, KineticType, StripeBundle, Tab } from "./Motifs";

/** The all-time record holder on the shown board's track (layout model 7: driver card). */
export function RecordHolder({ state }: { state: DashboardState }) {
  const board = state.leaderboards.all_time ?? state.leaderboards.today ?? null;
  const top: LeaderboardEntry | undefined = board?.entries[0];
  const colour = state.rigs.find((r) => r.rig_id === top?.rig_id)?.colour ?? "var(--text-3)";
  return (
    <section className="holder cutcard streaks" style={{ "--rig-colour": colour } as React.CSSProperties}
             aria-label="Track record">
      <span className="chequer holder__chequer" aria-hidden="true" />
      <Tab left="Track record" right={board?.track_name ?? null} />
      {top ? (
        <div className="holder__body">
          <Avatar name={top.driver ?? top.rig_name} className="avatar--l" />
          <div className="holder__who">
            <span className="label">Held by</span>
            <span className="holder__name">{top.driver ?? top.rig_name}</span>
          </div>
          <span className="holder__time c-purple">{formatLapTime(top.lap_ms)}</span>
        </div>
      ) : (
        <p className="holder__empty t2">No record yet. The first clean lap sets it.</p>
      )}
    </section>
  );
}

/** Attract mode: cafe branding, today's top 10, the record holder (and the challenge, when there is one). */
export function AttractView({ state }: { state: DashboardState }) {
  const name = state.cafe.name || "Live timing";
  return (
    <main className="attract">
      <StripeBundle corner="top-right" />
      <section className="attract__hero">
        <KineticType words={name.split(/\s+/).slice(0, 3)} rows={4} className="attract__kinetic" />
        <div className="attract__brand">
          <span className="kerb attract__kerb" aria-hidden="true" />
          <h1 className="attract__name">{name}</h1>
          <p className="attract__tag">Grab a seat. Set a lap. Beat the board.</p>
        </div>
        <RecordHolder state={state} />
      </section>
      <LeaderboardPanel title="Today" leaderboard={state.leaderboards.today ?? null} rigs={state.rigs}
                        className="attract__board" top />
    </main>
  );
}

/** /portrait: for a vertical screen at the entrance (1080 x 1920). */
export function PortraitView({ state }: { state: DashboardState }) {
  const name = state.cafe.name || "Live timing";
  const anyDriving = Object.values(state.frames).filter((f) => f.state === "driving");
  return (
    <main className="portrait">
      <StripeBundle corner="top-right" />
      <header className="portrait__brand">
        <span className="kerb" aria-hidden="true" />
        <h1 className="attract__name">{name}</h1>
        <p className="attract__tag">Grab a seat. Set a lap. Beat the board.</p>
      </header>
      <RecordHolder state={state} />
      <LeaderboardPanel title="Today" leaderboard={state.leaderboards.today ?? null} rigs={state.rigs}
                        className="portrait__board" top />
      <footer className="portrait__foot">
        <Tab left="On track now" right={String(anyDriving.length)} />
        <span className="t2">
          {anyDriving.length ? anyDriving.map((f) => f.driver ?? f.rig_id).join(" · ") : "Rigs are free: ask at the desk"}
        </span>
      </footer>
    </main>
  );
}
