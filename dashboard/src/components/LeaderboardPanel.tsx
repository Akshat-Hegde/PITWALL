import { useEffect, useState } from "react";
import { formatDelta, formatLapTime } from "../format";
import type { Leaderboard, LeaderboardEntry, RigInfo } from "../schema";

/** Rows on screen at once: ten fit at 1080p and 4K (sizes scale with screen height). */
export const BOARD_PAGE_SIZE = 10;
/** With more entries than that, the board pages through them at this interval. */
export const BOARD_PAGE_MS = 8000;

export function pageCount(total: number, size = BOARD_PAGE_SIZE): number {
  return Math.max(1, Math.ceil(total / size));
}

/** Entries on a page (wraps around), plus the 1-based range shown, e.g. [11, 14]. */
export function pageSlice<T>(entries: T[], page: number, size = BOARD_PAGE_SIZE) {
  const pages = pageCount(entries.length, size);
  const p = ((page % pages) + pages) % pages;
  const items = entries.slice(p * size, p * size + size);
  return { items, page: p, first: entries.length ? p * size + 1 : 0, last: p * size + items.length };
}

function usePage(total: number): number {
  const pages = pageCount(total);
  const [page, setPage] = useState(0);
  useEffect(() => {
    if (pages <= 1) {
      setPage(0);
      return;
    }
    const timer = setInterval(() => setPage((p) => (p + 1) % pages), BOARD_PAGE_MS);
    return () => clearInterval(timer);
  }, [pages]);
  return page % pages;
}

interface Props {
  leaderboard: Leaderboard | null;
  rigs: RigInfo[];
}

export function LeaderboardPanel({ leaderboard, rigs }: Props) {
  const colour = new Map(rigs.map((r) => [r.rig_id, r.colour]));
  const entries = leaderboard?.entries ?? [];
  const { items, first, last } = pageSlice(entries, usePage(entries.length));
  const paged = entries.length > BOARD_PAGE_SIZE;
  return (
    <section className="panel board-lb" aria-label="Best laps">
      <h2 className="panel__title">
        Best laps today
        {leaderboard?.track_name && <span className="panel__sub">{leaderboard.track_name}</span>}
        {paged && (
          <span className="lb__range" aria-live="polite">
            {first}–{last} of {entries.length}
          </span>
        )}
      </h2>
      {entries.length === 0 ? (
        <p className="panel__empty">No valid laps yet. Times appear here after a clean lap.</p>
      ) : (
        <ol className="lb" start={first}>
          {items.map((e) => (
            <BoardRow key={`${e.rig_id}-${e.driver ?? ""}-${e.rank}`} entry={e} colour={colour.get(e.rig_id)} />
          ))}
        </ol>
      )}
    </section>
  );
}

function BoardRow({ entry: e, colour }: { entry: LeaderboardEntry; colour: string | undefined }) {
  return (
    <li
      className={`lb__row${e.rank === 1 ? " lb__row--first" : ""}`}
      style={{ "--rig-colour": colour ?? "#888" } as React.CSSProperties}
    >
      <span className="lb__rank">{e.rank}</span>
      <span className="stripe" aria-hidden="true" />
      <span className="lb__who">
        <span className="lb__driver">{e.driver ?? e.rig_name}</span>
        <span className="lb__rig">{e.rig_name}</span>
      </span>
      <span className="lb__time num">{formatLapTime(e.lap_ms)}</span>
      <span className="lb__gap num">{e.rank === 1 ? "" : formatDelta(e.gap_ms)}</span>
    </li>
  );
}
