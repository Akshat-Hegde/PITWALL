import { useEffect, useState } from "react";
import type { DashboardState } from "../state/reducer";

const LINK_TEXT: Record<DashboardState["link"], string> = {
  connecting: "Connecting to hub",
  live: "Live",
  reconnecting: "Reconnecting to hub",
  version_mismatch: "Version mismatch",
};

interface Props {
  state: DashboardState;
  trackKey: string | null;
}

/**
 * Thin header: cafe left, link and clock right (the track is in the map's corner). Technical warnings (ports, addresses)
 * never show on the TV: they are on the staff page's Health tab and in the hub log.
 */
export function StatusBar({ state }: Props) {
  const event = state.features.events ? state.competition.event : null;
  return (
    <>
      <header className="header">
        <span className="kerb header__kerb" aria-hidden="true" />
        <div className="header__brand">
          <span className="header__mark" aria-hidden="true" />
          {state.cafe.name || "Live timing"}
          {event && (
            <span className="header__event">
              <span className="t3">×</span>
              {event.logo ? <img className="header__logo" src={event.logo} alt={event.company} /> : event.company}
            </span>
          )}
        </div>
        <div className="header__session" />
        <div className="header__right">
          <span className={`header__link link--${state.link}`}>
            {state.source === "mock" && state.link === "live" ? "Mock data" : LINK_TEXT[state.link]}
          </span>
          <Clock />
        </div>
      </header>
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
