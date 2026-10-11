import { useEffect, useState } from "react";
import { formatDelta, formatLapTime } from "../format";
import type { Leaderboard, LeaderboardEntry, RigInfo } from "../schema";
import { Tab } from "./Motifs";

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

function usePage(total: number, size: number): number {
  const pages = pageCount(total, size);
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
  title: string;
  /** Show the track name next to the title. */
  showTrack?: boolean;
  /** Row slots; more entries page through (or, with `top`, are cut off). */
  slots?: number;
  /** Show only the first `slots` entries, never page (e.g. "fastest today" in the race view). */
  top?: boolean;
  /** Show empty positions as open slots, so the board always fills its height (portrait, welcome). */
  fill?: boolean;
  className?: string;
}

export function LeaderboardPanel({ leaderboard, rigs, title, showTrack = true, slots = BOARD_PAGE_SIZE, top = false,
                                   fill = false, className = "" }: Props) {
  const colour = new Map(rigs.map((r) => [r.rig_id, r.colour]));
  const entries = leaderboard?.entries ?? [];
  const page = usePage(top ? 0 : entries.length, slots);
  const { items, first, last } = top
    ? { items: entries.slice(0, slots), first: entries.length ? 1 : 0, last: Math.min(slots, entries.length) }
    : pageSlice(entries, page, slots);
  const paged = !top && entries.length > slots;
  return (
    <section className={`lbcol ${className}`} aria-label={title}>
      <h2 className="lbcol__title">
        <Tab left={title} right={entries.length ? `${entries.length} ${entries.length === 1 ? "driver" : "drivers"}` : null} />
        {showTrack && leaderboard?.track_name && <span className="t2"> {leaderboard.track_name}</span>}
        {paged && (
          <span className="lbcol__range t3" aria-live="polite">
            {first}–{last} of {entries.length}
          </span>
        )}
      </h2>
      <div className="lb__head" aria-hidden="true">
        <span>Pos</span>
        <span />
        <span>Driver</span>
        <span className="r">Time</span>
        <span className="r">Gap</span>
      </div>
      {entries.length === 0 && !fill ? (
        <p className="lbcol__empty t2">No valid laps yet. Times appear here after a clean lap.</p>
      ) : (
        <ol className="lb" start={first || 1} style={{ "--slots": slots } as React.CSSProperties}>
          {items.map((e) => (
            <BoardRow key={`${e.rig_id}-${e.driver ?? ""}-${e.rank}`} entry={e} colour={colour.get(e.rig_id)} />
          ))}
          {fill && Array.from({ length: Math.max(0, slots - items.length) }, (_, i) => (
            <li key={`open-${i}`} className="lb__row lb__row--open">
              <span className="pos">{items.length + i + 1}</span>
              <span className="stripe" aria-hidden="true" />
              <span className="who__text">
                <span className="who__name">{items.length + i === 0 ? "Open: set the first lap" : "Open"}</span>
              </span>
              <span className="lb__time r">–:––.–––</span>
              <span className="lb__gap r" />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function BoardRow({ entry: e, colour }: { entry: LeaderboardEntry; colour: string | undefined }) {
  return (
    <li className={`lb__row${e.rank === 1 ? " lb__row--p1" : ""}`} style={{ "--rig-colour": colour ?? "var(--text-3)" } as React.CSSProperties}>
      <span className="pos">{e.rank}</span>
      <span className="stripe" aria-hidden="true" />
      <span className="who__text">
        <span className="who__name">{e.driver ?? e.rig_name}</span>
        <span className="who__sub">{e.rig_name}</span>
      </span>
      <span className={`lb__time r${e.rank === 1 ? " c-purple" : ""}`}>{formatLapTime(e.lap_ms)}</span>
      <span className="lb__gap r t2">{e.rank === 1 ? "" : formatDelta(e.gap_ms)}</span>
    </li>
  );
}
