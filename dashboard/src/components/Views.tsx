import { useEffect, useState } from "react";
import type { DashboardState } from "../state/reducer";
import { LeaderboardPanel } from "./LeaderboardPanel";
import { ChallengeCard } from "./Competition";
import { StripeBundle, Tab } from "./Motifs";

/** Open and Pro boards alternate on the leaderboard view (when there are Pro laps). */
export const BOARD_CLASS_MS = 15_000;

function useBoardClass(hasPro: boolean): "open" | "pro" {
  const [pro, setPro] = useState(false);
  useEffect(() => {
    if (!hasPro) {
      setPro(false);
      return;
    }
    const timer = setInterval(() => setPro((p) => !p), BOARD_CLASS_MS);
    return () => clearInterval(timer);
  }, [hasPro]);
  return pro && hasPro ? "pro" : "open";
}

/** Full-screen boards: today, this week, all time; Open and Pro alternate. */
export function BoardView({ state }: { state: DashboardState }) {
  const hasPro = Object.values(state.proLeaderboards).some((b) => b && b.entries.length > 0);
  const lapClass = useBoardClass(hasPro);
  const boards = lapClass === "pro" ? state.proLeaderboards : state.leaderboards;
  const track = state.leaderboards.today?.track_name ?? state.leaderboards.all_time?.track_name ?? null;
  return (
    <main className="boards">
      <StripeBundle corner="top-right" className="boards__stripes" />
      <header className="viewhead">
        <h1 className="viewhead__title">{track ?? "Best laps"}</h1>
        <Tab left={lapClass === "pro" ? "Pro" : "Open"}
             right={lapClass === "pro" ? "All assists off" : hasPro ? "All laps" : null} />
        <span className="viewhead__sub t2">Best lap per driver</span>
        <ChallengeCard state={state} compact />
      </header>
      <div className="boards__grid" key={lapClass}>
        <LeaderboardPanel title="Today" leaderboard={boards.today ?? null} rigs={state.rigs} showTrack={false} />
        <LeaderboardPanel title="This week" leaderboard={boards.week ?? null} rigs={state.rigs} showTrack={false} />
        <LeaderboardPanel title="All time" leaderboard={boards.all_time ?? null} rigs={state.rigs} showTrack={false} />
      </div>
    </main>
  );
}
