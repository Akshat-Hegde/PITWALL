import { useEffect, useState } from "react";
import { hubNow } from "../state/hubclock";
import type { DashboardState } from "../state/reducer";
import { SlashMark } from "./Motifs";

interface Props {
  state: DashboardState;
  trackKey: string | null;
}

/**
 * Thin header: cafe left, link and clock right (the track is in the map's corner). Technical warnings (ports, addresses)
 * never show on the TV: they are on the staff page's Health tab and in the hub log. Neither does the connection:
 * the dashboard reconnects by itself and shows the waiting or attract screen while the hub is quiet.
 */
export function StatusBar({ state }: Props) {
  const event = state.features.events ? state.competition.event : null;
  return (
    <>
      <header className="header">
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
          <span className="header__link link--live">{state.source === "mock" ? "Mock data" : "Live"}</span>
          <Clock />
        </div>
        <SlashMark className="header__slash" />
      </header>
    </>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date(hubNow()));
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date(hubNow())), 10_000);
    return () => clearInterval(timer);
  }, []);
  return (
    <time className="header__clock" dateTime={now.toISOString()}>
      {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
    </time>
  );
}
