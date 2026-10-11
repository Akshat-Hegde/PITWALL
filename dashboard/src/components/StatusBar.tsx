import { useEffect, useState } from "react";
import type { DashboardState } from "../state/reducer";
import type { View } from "../views";

const LINK_TEXT: Record<DashboardState["link"], string> = {
  connecting: "Connecting to hub",
  live: "Live",
  reconnecting: "Reconnecting to hub",
  version_mismatch: "Version mismatch",
};

const VIEW_TEXT: [View, string][] = [
  ["race", "Race"],
  ["board", "Leaderboard"],
  ["analysis", "Head to head"],
  ["onboard", "Onboard"],
  ["attract", "Welcome"],
];

interface Props {
  state: DashboardState;
  trackKey: string | null;
  view: View;
  /** "Auto", "Attract" or "Fixed". */
  modeNote: string;
}

/** Thin header: cafe left, session and track centre, views, link and clock right. Warnings in a line below. */
export function StatusBar({ state, trackKey, view, modeNote }: Props) {
  const warnings = state.status?.warnings ?? [];
  const session = Object.values(state.frames).find((f) => f.session.track_key === trackKey)?.session;
  const track = session?.track_name ?? state.leaderboards.today?.track_name ?? null;
  const length = session?.track_length_m ? `${(session.track_length_m / 1000).toFixed(3)} km` : null;
  return (
    <>
      <header className="header">
        <span className="kerb header__kerb" aria-hidden="true" />
        <div className="header__brand">
          <span className="header__mark" aria-hidden="true" />
          {state.cafe.name || "Live timing"}
        </div>
        <div className="header__session">
          {session?.session_type && <span className="t2">{session.session_type}</span>}
          {track && <span className="header__track">{track}</span>}
          {length && <span className="t2">{length}</span>}
        </div>
        <div className="header__right">
          <nav className="tabs" aria-label="Views">
            {VIEW_TEXT.map(([v, text]) => (
              <span key={v} className={`tab${v === view ? " is-active" : ""}`}>{text}</span>
            ))}
            <span className="tab tab--mode">{modeNote}</span>
          </nav>
          <span className={`header__link link--${state.link}`}>
            {state.source === "mock" && state.link === "live" ? "Mock data" : LINK_TEXT[state.link]}
          </span>
          <Clock />
        </div>
      </header>
      {warnings.length > 0 && (
        <ul className="warnings" role="status">
          {warnings.map((w) => (
            <li key={`${w.code}-${w.rig_id ?? ""}`}>{w.message}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 10_000);
    return () => clearInterval(timer);
  }, []);
  return (
    <time className="header__clock" dateTime={now.toISOString()}>
      {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
    </time>
  );
}
