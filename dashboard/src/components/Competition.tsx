import { formatDelta, formatLapTime } from "../format";
import type { Challenge, ChallengeWinnerMoment } from "../schema";
import { hubNow } from "../state/hubclock";
import type { DashboardState } from "../state/reducer";
import { Avatar, KineticType, StripeBundle, Tab } from "./Motifs";

/** "3 days left", "Ends today", "Starts in 2 days". `now` is hub time, like the challenge's dates. */
export function challengeWhen(c: Challenge, now = hubNow()): string {
  const day = 24 * 3600_000;
  if (c.state === "upcoming") {
    const d = Math.ceil((c.starts_at - now) / day);
    return d <= 1 ? "Starts tomorrow" : `Starts in ${d} days`;
  }
  if (c.state === "ended") return "Finished";
  const left = c.ends_at - now;
  if (left < day) return `Ends in ${Math.max(1, Math.ceil(left / 3600_000))} h`;
  return `${Math.ceil(left / day)} days left`;
}

/** The current weekly challenge: track, class, prize, time left and the leader (attract, portrait, boards). */
export function ChallengeCard({ state, compact = false }: { state: DashboardState; compact?: boolean }) {
  const c = state.features.challenges ? state.competition.challenge : null;
  if (!c) return null;
  const leader = c.entries[0];
  return (
    <section className={`challenge cutcard streaks${compact ? " challenge--compact" : ""}`} aria-label="Challenge">
      <span className="kerb challenge__kerb" aria-hidden="true" />
      <div className="challenge__head">
        <Tab left="Weekly challenge" right={c.lap_class === "pro" ? "Pro" : "Open"} />
        <span className="challenge__when">{challengeWhen(c)}</span>
      </div>
      <h2 className="challenge__title">{c.title}</h2>
      <div className="challenge__body">
        {c.prize && (
          <div className="field">
            <span className="label">Prize</span>
            <span className="challenge__prize">{c.prize}</span>
          </div>
        )}
        <div className="field">
          <span className="label">{c.state === "upcoming" ? "Track" : "Leader"}</span>
          {c.state === "upcoming" || !leader ? (
            <span className="challenge__prize">{c.state === "upcoming" ? c.track_name : "Nobody yet: be first"}</span>
          ) : (
            <span className="challenge__leader">
              {leader.driver} <span className="c-purple">{formatLapTime(leader.lap_ms)}</span>
            </span>
          )}
        </div>
      </div>
      {!compact && c.entries.length > 1 && (
        <ol className="challenge__list">
          {c.entries.slice(1, 5).map((e) => (
            <li key={e.rank}>
              <span className="t3">{e.rank}</span> {e.driver} <span className="t2">{formatDelta(e.gap_ms)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function ChallengeWinner({ m }: { m: ChallengeWinnerMoment }) {
  return (
    <>
      <KineticType words={["Challenge", "winner"]} />
      <section className="moment__card moment__card--record cutcard streaks">
        <span className="chequer moment__chequer" aria-hidden="true" />
        <div className="moment__who">
          <Avatar name={m.winner?.driver ?? "?"} className="avatar--xl" />
          <div>
            <Tab left={m.title} right={m.lap_class === "pro" ? "Pro" : "Open"} />
            <h1 className="moment__name">{m.winner?.driver ?? "No entries"}</h1>
            {m.track_name && <span className="moment__sub">{m.track_name}</span>}
          </div>
        </div>
        {m.winner && <div className="moment__time c-purple">{formatLapTime(m.winner.lap_ms)}</div>}
        {m.prize && <div className="moment__gap"><span className="label">Prize</span><span>{m.prize}</span></div>}
        {m.runners_up.length > 0 && (
          <ul className="moment__records">
            {m.runners_up.map((e) => (
              <li key={e.rank}><Tab left={`P${e.rank} ${e.driver}`} right={formatDelta(e.gap_ms)} className="tab-badge--muted" /></li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

/** Corporate event: team leaderboard (average of each team's best N drivers). */
export function TeamsView({ state }: { state: DashboardState }) {
  const ev = state.competition.event;
  if (!ev) {
    return (
      <main className="teams">
        <p className="analysis__empty">No corporate event is running. Start one on the staff page.</p>
      </main>
    );
  }
  const leader = ev.teams.find((t) => t.average_ms != null)?.average_ms ?? null;
  return (
    <main className="teams">
      <StripeBundle corner="top-right" />
      <header className="viewhead teams__head">
        {ev.logo && <img className="teams__logo" src={ev.logo} alt={ev.company} />}
        <h1 className="viewhead__title">{ev.name}</h1>
        <span className="viewhead__sub t2">
          {ev.company} · Team score: average of the best {ev.best_n} {ev.best_n === 1 ? "lap" : "laps"}
          {ev.track_name ? ` · ${ev.track_name}` : ""}
        </span>
      </header>
      <ol className="teams__list">
        {ev.teams.map((t) => (
          <li key={t.id} className={`team cutcard${t.rank === 1 && t.average_ms != null ? " team--p1" : ""}`}>
            {t.rank === 1 && t.average_ms != null && <span className="chequer team__chequer" aria-hidden="true" />}
            <span className="team__pos">{t.rank}</span>
            {t.logo ? <img className="team__logo" src={t.logo} alt="" /> : <Avatar name={t.name} className="avatar--l" />}
            <div className="team__who">
              <span className="team__name">{t.name}</span>
              <span className="team__members t2">
                {t.members.map((m) => `${m.name}${m.best_ms ? ` ${formatLapTime(m.best_ms)}` : ""}`).join(" · ") || "No drivers yet"}
              </span>
            </div>
            <span className="team__count t2">{t.counted}/{ev.best_n}</span>
            <span className={`team__time${t.rank === 1 && t.average_ms != null ? " c-purple" : ""}`}>
              {formatLapTime(t.average_ms)}
            </span>
            <span className="team__gap t2">
              {t.average_ms != null && leader != null && t.average_ms !== leader ? formatDelta(t.average_ms - leader) : ""}
            </span>
          </li>
        ))}
      </ol>
    </main>
  );
}
