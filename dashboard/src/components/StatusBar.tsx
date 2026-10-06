import { useEffect, useState } from "react";
import type { DashboardState } from "../state/reducer";

const STATE_TEXT = { driving: "On track", in_menu_paused: "In menu", no_data: "No data" } as const;

const LINK_TEXT: Record<DashboardState["link"], string> = {
  connecting: "Connecting to hub",
  live: "Live",
  reconnecting: "Reconnecting to hub",
  version_mismatch: "Version mismatch",
};

export function StatusBar({ state }: { state: DashboardState }) {
  const warnings = state.status?.warnings ?? [];
  const mismatch = state.status?.format_mismatch ?? false;
  return (
    <header className="statusbar">
      <div className="statusbar__brand">{state.cafe.name || "Live timing"}</div>
      <ul className="statusbar__rigs" aria-label="Rigs">
        {state.rigs.map((rig) => {
          const frame = state.frames[rig.rig_id];
          const rigState = frame?.state ?? "no_data";
          const format = rig.data_format ? `${rig.game} ${rig.data_format}` : rig.game;
          const formatProblem = !rig.format_supported || (mismatch && rigState !== "no_data");
          return (
            <li
              key={rig.rig_id}
              className={`chip chip--${rigState.replace(/_/g, "-")}`}
              style={{ "--rig-colour": rig.colour } as React.CSSProperties}
            >
              <span className="stripe" aria-hidden="true" />
              <span className="chip__name">{rig.name}</span>
              <span className="chip__state">{STATE_TEXT[rigState]}</span>
              {rigState !== "no_data" && (
                <span className={`chip__format${formatProblem ? " is-problem" : ""}`}>{format}</span>
              )}
              {frame?.session.track_name && rigState !== "no_data" && (
                <span className="chip__track">{frame.session.track_name}</span>
              )}
            </li>
          );
        })}
      </ul>
      {warnings.length > 0 && (
        <ul className="statusbar__warnings" role="status">
          {warnings.map((w) => (
            <li key={`${w.code}-${w.rig_id ?? ""}`}>{w.message}</li>
          ))}
        </ul>
      )}
      <div className={`statusbar__link link--${state.link}`}>
        {state.source === "mock" && state.link === "live" ? "Mock data" : LINK_TEXT[state.link]}
      </div>
      <Clock />
    </header>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 10_000);
    return () => clearInterval(timer);
  }, []);
  return (
    <time className="statusbar__clock" dateTime={now.toISOString()}>
      {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
    </time>
  );
}
