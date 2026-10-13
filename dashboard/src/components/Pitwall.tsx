import { useEffect, useRef, useState } from "react";
import type { Display } from "../map/geometry";
import type { LeaderboardEntry, RigFrame, RigInfo, SectorTime } from "../schema";
import {
  CHART, deltaTo, driverKey, fmtLap, fmtPred, headlineSize, headlines, predictedPosition, refFromMinis,
  refFromTrace, storyChart, towerRows, type Headline, type Rating, type RefLap, type TowerRow,
} from "../state/pitwall";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { PitwallLogo } from "./Brand";
import { EdgeLines, Flash } from "./Motifs";
import { STRIP_HOLD_MS, SteeringWheel, activeRigs, chooseStripRig, useHeld } from "./Live";
import { PitwallMap, type Ghost } from "./PitwallMap";

// The LIVE page (design "Pitwall TV", Turn 2 "premium racing treatment"): headline ticker; today's board with
// the hottest lap's "on this lap" ghost row; the map; one focus-driver card; the session story and moments.

const COL = { p: "#B15CFF", g: "#2EE06E", y: "#F7C948", r: "#FF3B30", w: "#FFFFFF", n: "#3A3E48", grey: "#8A8F9C" };
const RATING_COL: Record<Rating, string> = { p: COL.p, g: COL.g, y: COL.y, n: "#2A2D35" };
const SECTOR_RATING: Record<string, Rating> = { session_best: "p", personal_best: "g", normal: "y" };
const HEADLINE_MS = 7000;
const TREND_SHOW_MS = 60_000;

const minus = (ms: number) => (ms < 0 ? "−" : "+");
const fmtDelta = (ms: number, digits = 2) => `${minus(ms)}${(Math.abs(ms) / 1000).toFixed(digits)}`;

function tyreColour(t: number): string {
  return t < 80 ? "#4DA3FF" : t <= 100 ? COL.g : t <= 110 ? "#FFB020" : COL.r;
}

function useClock(): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return [now.getHours(), now.getMinutes(), now.getSeconds()].map((v) => String(v).padStart(2, "0")).join(":");
}

/** Rotates the headlines: the old line slides out left and fades (280 ms), the next slides in. */
function useHeadline(list: Headline[]): { line: Headline; out: boolean } {
  const [i, setI] = useState(0);
  const [out, setOut] = useState(false);
  useEffect(() => {
    let to: ReturnType<typeof setTimeout> | undefined;
    const id = setInterval(() => {
      setOut(true);
      to = setTimeout(() => {
        setI((x) => x + 1);
        setOut(false);
      }, 280);
    }, HEADLINE_MS);
    return () => {
      clearInterval(id);
      if (to) clearTimeout(to);
    };
  }, []);
  return { line: list[i % list.length] ?? list[0]!, out };
}

/** ▲ / ▼ for a minute after a driver moves up or down today's board. */
function useTrends(entries: readonly LeaderboardEntry[]): Map<string, 1 | -1> {
  const last = useRef(new Map<string, number>());
  const moved = useRef(new Map<string, { dir: 1 | -1; at: number }>());
  const now = Date.now();
  entries.forEach((e, i) => {
    const key = driverKey(e.driver, e.rig_id);
    const prev = last.current.get(key);
    if (prev !== undefined && prev !== i) moved.current.set(key, { dir: i < prev ? 1 : -1, at: now });
    last.current.set(key, i);
  });
  const out = new Map<string, 1 | -1>();
  for (const [key, m] of moved.current) if (now - m.at < TREND_SHOW_MS) out.set(key, m.dir);
  return out;
}

interface PageProps {
  store: DashboardStore;
  state: DashboardState;
  trackKey: string | null;
  mapDisplay?: Display | null;
  pinnedRigId?: string | null;
}

/** The cafe's badge: its logo, or its first letter when there is none or the image fails to load. */
export function CafeBadge({ logo, initial }: { logo: string | null; initial: string }) {
  const [failed, setFailed] = useState<string | null>(null);   // the logo URL that failed; a new URL gets a fresh try
  return (
    <span className="pw-cafe__badge">
      {logo && failed !== logo
        ? <img className="pw-cafe__logo" src={logo} alt="" onError={() => setFailed(logo)} />
        : initial}
    </span>
  );
}

export function PitwallPage({ store, state, trackKey, mapDisplay = null, pinnedRigId = null }: PageProps) {
  const rigs = activeRigs(state);
  const solo = rigs.length <= 1;
  const now = performance.now();
  const focusId = useHeld(chooseStripRig(state, store, pinnedRigId), pinnedRigId ? 0 : STRIP_HOLD_MS, now);
  const focusRig = rigs.find((r) => r.rig_id === focusId) ?? null;
  const frame = focusRig ? state.frames[focusRig.rig_id] : undefined;
  const lap = frame?.state === "driving" ? frame.lap : null;
  const colour = focusRig?.colour ?? "#fff";
  const session = Object.values(state.frames).find((f) => f.session.track_key === trackKey)?.session;
  const length = session?.track_length_m ?? 0;
  const board = state.leaderboards.today && state.leaderboards.today.track_key === trackKey ? state.leaderboards.today : null;
  const entries = board?.entries ?? [];
  const record = entries[0] ?? null;

  // Reference laps: today's record (traced by this page if it saw it, else the hub's mini-sector times) and the
  // focus driver's own best (traced by this page).
  let recordRef: RefLap | null = null;
  if (record && length) {
    for (const r of rigs) {
      const t = store.live.speedTraces(r.rig_id);
      if (t?.best && t.bestMs === record.lap_ms) recordRef = refFromTrace("record", t.best, t.length, t.bestMs, record.sectors_ms);
    }
    recordRef ??= board?.record_minis ? refFromMinis("record", board.record_minis, length, record.sectors_ms) : null;
  }
  const own = focusRig ? store.live.speedTraces(focusRig.rig_id) : null;
  const ownBestSectors = frame?.best?.sectors_ms ?? frame?.personal_best?.sectors_ms ?? null;
  const pbRef = own?.best && own.bestMs ? refFromTrace("pb", own.best, own.length, own.bestMs, ownBestSectors) : null;
  const focusBest = frame?.best?.lap_ms ?? null;
  const target = !solo && recordRef && (focusBest == null || focusBest > recordRef.lapMs) ? recordRef : pbRef ?? recordRef;
  const delta = deltaTo(target, lap);
  const pred = target && delta != null ? target.lapMs + delta : null;
  const predPos = pred != null ? predictedPosition(entries, pred) : null;
  const sectorsDone = lap ? Math.min(lap.sector, 2) : 0;
  const lapSectors: (SectorTime | null)[] = lap ? [...lap.sectors] : [null, null, null];
  const doneRatings: Rating[] = [0, 1, 2].map((i) => (i < sectorsDone && lapSectors[i]?.rating ? SECTOR_RATING[lapSectors[i]!.rating!] ?? "y" : "n"));

  // Tower: drivers on an active rig in their rig colour.
  const activeColour = new Map<string, string>();
  for (const r of rigs) {
    const f = state.frames[r.rig_id];
    activeColour.set(driverKey(f?.driver ?? null, r.rig_id), r.colour);
  }
  const rows = towerRows(entries, (e) => activeColour.get(driverKey(e.driver, e.rig_id)) ?? null,
    focusRig && pred != null ? { name: frame?.driver ?? focusRig.name, colour, predMs: pred, sectors: doneRatings } : null);
  const trends = useTrends(entries);

  // Headlines.
  const name = (frame?.driver ?? focusRig?.name ?? "").toUpperCase();
  const chaserRig = rigs.find((r) => r.rig_id !== focusRig?.rig_id && state.frames[r.rig_id]?.state === "driving"
    && store.live.deltaToBest(r.rig_id) != null);
  const lines = headlines({
    focus: focusRig ? { name, delta, sectorsDone, vsRecord: target?.kind === "record", predMs: pred, predPos } : null,
    chaser: chaserRig ? { name: (state.frames[chaserRig.rig_id]?.driver ?? chaserRig.name).toUpperCase(),
      delta: store.live.deltaToBest(chaserRig.rig_id)! } : null,
    record: record ? { holder: (record.driver ?? record.rig_name).toUpperCase(), lapMs: record.lap_ms } : null,
    focusBestMs: focusBest,
  });
  const headline = useHeadline(lines);
  const clock = useClock();

  const ghosts: Ghost[] = [];
  if (recordRef) ghosts.push({ ref: recordRef, colour: COL.p, label: "RECORD" });
  if (solo && pbRef) ghosts.push({ ref: pbRef, colour: COL.g, label: "PB" });

  const track = (session?.track_name ?? board?.track_name ?? "").toUpperCase();
  const cafe = (state.cafe.name || "Sim racing").toUpperCase();
  return (
    <main className="pw live">
      <Decor />
      <header className="pw-head">
        <div className="pw-head__streaks" aria-hidden="true" />
        <div className="pw-head__left">
          <div className="pw-head__meta">
            <span className="pw-live"><span className="pw-live__dot" />LIVE</span>
            <span className="pw-head__session">
              {[track, (session?.session_type ?? "").toUpperCase(), `${rigs.length} RIG${rigs.length === 1 ? "" : "S"} LIVE`]
                .filter(Boolean).join(" · ")}
            </span>
          </div>
          <div className="pw-head__line">
            <div className="pw-headline" style={{ fontSize: headlineSize(headline.line), transform: `translateX(${headline.out ? -60 : 0}px)`, opacity: headline.out ? 0 : 1 }}>
              {headline.line.map(([t, c], i) => <span key={i} style={{ color: COL[c] }}>{t}</span>)}
            </div>
          </div>
        </div>
        <div className="pw-head__right">
          <div className="pw-cafe">
            <CafeBadge logo={state.cafe.logo ?? null} initial={cafe[0] ?? ""} />
            <span className="pw-cafe__name">{cafe}</span>
          </div>
          <div className="pw-head__clockrow">
            <span className="pw-powered">POWERED BY</span>
            <PitwallLogo height={18} />
            <span className="pw-clock">{clock}</span>
          </div>
        </div>
      </header>

      <div className="pw-mid">
        <Tower rows={rows} trends={trends} />
        <section className="pw-col pw-map">
          <div className="pw-colhead">
            <div className="pw-colhead__title"><span className="pw-tick" />{track || "TRACK"}
              {length ? <span className="pw-dim">{(length / 1000).toFixed(3)} KM</span> : null}</div>
            <div className="pw-hatch" />
            <div className="pw-dim">{solo ? `MINI-SECTORS · ${name || "—"} vs ${target?.kind === "record" ? "RECORD" : "PB"}` : "MINI-SECTORS · FASTEST RIG"}</div>
          </div>
          <div className="pw-map__stage">
            <div className="pw-map__arcs" aria-hidden="true"><span /><span /><span /></div>
            <div className="pw-map__dots" aria-hidden="true" />
            <PitwallMap store={store} state={state} trackKey={trackKey} focusRigId={focusRig?.rig_id ?? null} solo={solo}
                        ghosts={ghosts} displayOverride={mapDisplay} />
            {!state.outlines[trackKey ?? ""] && <p className="pw-map__note">The track outline appears after the first full lap.</p>}
          </div>
          <div className="pw-legend">
            <span><i className="pw-legend__ghost" />TODAY'S RECORD GHOST</span>
            <span><i className="pw-legend__ring" />HOTTEST LAP</span>
            <span><i className="pw-legend__band" />MINI-SECTOR OWNER</span>
          </div>
        </section>
        {focusRig && frame ? (
          <FocusCard store={store} state={state} rig={focusRig} frame={frame} colour={colour} delta={delta} pred={pred}
                     predPos={predPos} target={target} sectors={lapSectors} sectorsDone={sectorsDone} leaderMs={record?.lap_ms ?? null} />
        ) : (
          <section className="pw-card pw-card--empty"><div className="pw-card__empty">Waiting for a car on track</div></section>
        )}
      </div>

      <div className="pw-bottom">
        <Story state={state} trackKey={trackKey} solo={solo} focusKey={focusRig ? driverKey(frame?.driver ?? null, focusRig.rig_id) : null}
               recordMs={record?.lap_ms ?? null} pbMs={solo ? pbRef?.lapMs ?? focusBest : null} />
        <Moments state={state} />
      </div>
    </main>
  );
}

function Decor() {
  return (
    <div className="pw-decor" aria-hidden="true">
      <Flash className="pw-flash" width={480} height={170} corner="top-right" dots />
      <EdgeLines className="pw-notch" width={30} height={150} anchor="top" />
      <EdgeLines className="pw-steps" width={36} height={280} />
    </div>
  );
}

function Tower({ rows, trends }: { rows: TowerRow[]; trends: Map<string, 1 | -1> }) {
  return (
    <section className="pw-col pw-tower">
      <div className="pw-colhead">
        <div className="pw-colhead__title"><span className="pw-tick" />TODAY'S BOARD</div>
        <div className="pw-hatch" />
        <div className="pw-dim">OPEN · BEST LAP</div>
      </div>
      <div className="pw-tower__cols">
        <div className="c">POS</div><div /><div>DRIVER</div><div className="r">BEST</div><div className="r">GAP</div><div className="r">SECT</div><div />
      </div>
      <div className="pw-tower__rows">
        {rows.length === 0 && <p className="pw-tower__empty">No laps on the board yet today.</p>}
        {rows.map((r, i) => {
          const trend = trends.get(r.key);
          const rc = r.colour ?? COL.n;
          return (
            <div key={r.key} className={`pw-row${r.ghost ? " pw-row--ghost" : ""}${r.leader ? " pw-row--leader" : ""}`}
                 style={{ transform: `translateY(${i * 60}px)`, "--rc": rc } as React.CSSProperties}>
              <div className="pw-row__pos" style={r.leader ? { background: "#fff", color: "#0B0C0F" } : r.ghost ? { background: rc, color: "#0B0C0F" } : undefined}>{r.pos}</div>
              <div className="pw-row__stripe" style={{ background: rc }} />
              <div className="pw-row__who">
                <div className="pw-row__name" style={{ color: r.colour || r.ghost ? "#fff" : "#C9CCD3" }}>{r.name}</div>
                {r.sub && <div className="pw-row__sub" style={{ color: rc }}>{r.sub}</div>}
              </div>
              <div className="pw-row__best" style={{ color: r.ghost ? rc : r.leader ? COL.p : "#fff" }}>{fmtLap(r.lapMs)}</div>
              <div className="pw-row__gap" style={{ color: r.leader ? COL.p : r.ghost && r.gapMs < 0 ? COL.g : COL.grey }}>
                {r.leader ? "RECORD" : r.ghost ? fmtDelta(r.gapMs, 3) : `+${(r.gapMs / 1000).toFixed(3)}`}
              </div>
              <div className="pw-row__secs">{r.sectors.map((s, j) => <span key={j} style={{ background: RATING_COL[s] }} />)}</div>
              <div className="pw-row__trend" style={{ color: trend === 1 ? COL.g : COL.r }}>{trend === 1 ? "▲" : trend === -1 ? "▼" : ""}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

interface CardProps {
  store: DashboardStore;
  state: DashboardState;
  rig: RigInfo;
  frame: RigFrame;
  colour: string;
  delta: number | null;
  pred: number | null;
  predPos: number | null;
  target: RefLap | null;
  sectors: (SectorTime | null)[];
  sectorsDone: number;
  leaderMs: number | null;
}

function FocusCard({ store, state, rig, frame, colour, delta, pred, predPos, target, sectors, sectorsDone, leaderMs }: CardProps) {
  const driving = frame.state === "driving";
  const lap = driving ? frame.lap : null;
  const car = driving ? frame.car : null;
  const speed = driving ? Math.round(frame.speed_kph ?? 0) : 0;
  const lit = Math.round((Math.min(speed, 340) / 340) * 26);
  const thr = driving ? Math.round((frame.throttle ?? 0) * 100) : 0;
  const brk = driving ? Math.round((frame.brake ?? 0) * 100) : 0;
  const deltaColour = delta == null ? COL.grey : delta < 0 ? COL.g : COL.r;
  const predColour = pred == null ? "#fff" : leaderMs != null && pred < leaderMs ? COL.p : target && pred < target.lapMs ? COL.g : "#fff";
  const gear = !driving || frame.gear == null ? "–" : frame.gear < 0 ? "R" : frame.gear === 0 ? "N" : String(frame.gear);
  const drsOn = !!car?.drs_open;
  const tyres = ["FL", "FR", "RL", "RR"].map((k, i) => ({ k, t: car?.tyre_surface_c?.[i] ?? null, p: car?.tyre_pressure_psi?.[i] ?? null }));
  return (
    <section className="pw-card" style={{ "--fc": colour } as React.CSSProperties}>
      <div className="pw-card__dots" aria-hidden="true" />
      <div className="pw-card__streaks" aria-hidden="true" />
      <div className="pw-card__edge" aria-hidden="true" />
      <div className="pw-card__topline" aria-hidden="true" />
      <div className="pw-card__hatch" aria-hidden="true" />
      <div className="pw-card__row1">
        <div className="pw-tabs">
          <span className="pw-tabs__lap">LAP {lap?.number ?? "–"}</span>
          <span className="pw-tabs__mode">{!lap ? "IN MENU" : lap.valid ? "PUSH" : "INVALID"}</span>
        </div>
        <div className="pw-laptime"><span className="pw-dim">LAP TIME</span><span>{lap ? fmtLap(lap.current_ms) : "–:––.–––"}</span></div>
      </div>
      <div className="pw-card__name">
        <span className="pw-card__bar" />
        <span className="pw-card__driver">{(frame.driver ?? rig.name).toUpperCase()}</span>
        <span className="pw-card__rig">{rig.name.toUpperCase()}</span>
      </div>
      <div className="pw-card__delta">
        <div className="pw-bigdelta" style={{ color: deltaColour, textShadow: delta == null ? "none" : `0 0 28px ${deltaColour}66` }}>
          {delta == null ? "—" : fmtDelta(delta)}<span className="pw-bigdelta__s">s</span>
        </div>
        <div className="pw-target">
          <div className="pw-dim">{target?.kind === "record" ? "VS TODAY'S RECORD" : target ? "VS PERSONAL BEST" : "NO REFERENCE LAP YET"}</div>
          <div className="pw-target__time">{target ? fmtLap(target.lapMs) : ""}</div>
        </div>
      </div>
      <div className="pw-deltabar">
        <div className="pw-deltabar__track">
          <div className="pw-deltabar__side pw-deltabar__side--l"><div style={{ width: `${delta != null && delta < 0 ? Math.min(100, (-delta / 600) * 100) : 0}%` }}><span /><span /></div></div>
          <div className="pw-deltabar__mid" />
          <div className="pw-deltabar__side pw-deltabar__side--r"><div style={{ width: `${delta != null && delta > 0 ? Math.min(100, (delta / 600) * 100) : 0}%` }}><span /><span /></div></div>
        </div>
        <div className="pw-deltabar__labels"><span>FASTER</span><span>SLOWER</span></div>
      </div>
      <div className="pw-card__pred">
        <div>
          <div className="pw-dim">PREDICTED · {predPos ? `P${predPos} ON THIS LAP` : "—"}</div>
          <div className="pw-pred"><span className="pw-pred__on">ON FOR</span><span style={{ color: predColour }}>{pred != null ? fmtPred(pred) : "—"}</span></div>
        </div>
        <div className="pw-sectors">
          {[0, 1, 2].map((i) => {
            const done = i < sectorsDone && sectors[i];
            const isLive = lap != null && i === sectorsDone;
            const c = done ? RATING_COL[SECTOR_RATING[sectors[i]!.rating ?? "normal"] ?? "y"] : null;
            const ref = target?.sectorsMs?.[i];
            const d = done && ref ? sectors[i]!.ms - ref : null;
            return (
              <div key={i} className="pw-sector">
                <div className="pw-sector__head"><span className="pw-sector__dot" style={{ background: c ?? "transparent", borderColor: c ?? (isLive ? "#fff" : "#4A4E58") }} />S{i + 1}</div>
                <div className="pw-sector__time" style={{ color: c ?? (isLive ? "#fff" : "#4A4E58") }}>{done ? (sectors[i]!.ms / 1000).toFixed(3) : isLive ? "LIVE" : "—"}</div>
                <div className="pw-sector__d" style={{ color: d != null && d > 0 ? COL.r : COL.g }}>{d != null ? fmtDelta(d, 3) : ""}</div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="pw-card__drive">
        <div>
          <div className="pw-speed"><span className="pw-speed__v">{driving ? speed : "–"}</span><span className="pw-dim">KM/H</span></div>
          <div className="pw-barcode">{Array.from({ length: 26 }, (_, k) => (
            <span key={k} style={{ background: k < lit ? (k >= 22 ? "#E10600" : "#fff") : "rgba(255,255,255,0.09)" }} />))}</div>
        </div>
        <div className="pw-gear">
          <div className="pw-dim pw-small">GEAR</div>
          <div className="pw-gear__v">{gear}</div>
          <div className="pw-drs" style={{ color: drsOn ? COL.g : "#4A4E58", borderColor: drsOn ? COL.g : "#4A4E58" }}>DRS</div>
        </div>
        <div className="pw-wheel">
          <SteeringWheel store={store} rigId={rig.rig_id} frameHz={state.frameHz} rotationDeg={state.steeringRotationDeg} frame={frame} />
        </div>
      </div>
      <div className="pw-card__inputs">
        <div className="pw-pedals">
          {[["THROTTLE", thr, COL.g], ["BRAKE", brk, COL.r]].map(([label, v, c]) => (
            <div key={label as string}>
              <div className="pw-pedal__head"><span>{label}</span><span style={{ color: c as string }}>{v}%</span></div>
              <div className="pw-pedal__bars" style={{ width: `${Math.max(2, v as number)}%` }}>
                <span style={{ background: c as string }} /><span style={{ background: c as string }} />
              </div>
            </div>
          ))}
        </div>
        <div className="pw-tyres">
          {tyres.map((t) => (
            <div key={t.k} className="pw-tyre">
              <span className="pw-tyre__k">{t.k}</span>
              <span className="pw-tyre__t" style={{ color: t.t == null ? "#4A4E58" : tyreColour(t.t) }}>{t.t == null ? "–" : Math.round(t.t)}°</span>
              <span className="pw-tyre__p">{t.p == null ? "–" : t.p.toFixed(1)}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Story({ state, trackKey, solo, focusKey, recordMs, pbMs }: {
  state: DashboardState; trackKey: string | null; solo: boolean; focusKey: string | null; recordMs: number | null; pbMs: number | null;
}) {
  const colours = new Map(state.rigs.map((r) => [r.rig_id, r.colour]));
  const laps = state.storyLaps.filter((l) => !l.track_key || l.track_key === trackKey);
  const refs = [];
  if (recordMs != null) refs.push({ ms: recordMs, label: `REC ${fmtLap(recordMs)}`, colour: COL.p });
  if (solo && pbMs != null) refs.push({ ms: pbMs, label: `PB ${fmtLap(pbMs)}`, colour: COL.g });
  const c = storyChart(laps, Date.now(), (l) => colours.get(l.rig_id) ?? "#5A5E68", refs, solo ? focusKey : null);
  return (
    <section className="pw-story">
      <div className="pw-colhead pw-colhead--small">
        <div className="pw-colhead__title"><span className="pw-tick" />SESSION STORY</div>
        <div className="pw-hatch" />
        <div className="pw-story__legend">
          <span><i className="pw-story__pb" />PERSONAL BEST</span>
          <span><i className="pw-story__inv" />INVALID LAP</span>
          <span>LAP TIME · FASTER ↑</span>
        </div>
      </div>
      <div className="pw-story__plot">
        <svg viewBox={`0 0 ${CHART.W} ${CHART.H}`} width={CHART.W} height={CHART.H}>
          {c.yTicks.map((t, i) => <line key={i} x1={CHART.L} x2={CHART.R} y1={t.y} y2={t.y} stroke="rgba(255,255,255,0.06)" />)}
          {c.refs.map((r, i) => <line key={i} x1={CHART.L} x2={CHART.R} y1={r.y} y2={r.y} stroke={r.colour} strokeWidth={1.5} strokeDasharray="6 6" opacity={0.7} />)}
          <line x1={c.nowX} x2={c.nowX} y1={6} y2={CHART.B} stroke="rgba(255,255,255,0.25)" />
          <text x={c.nowX} y={190} className="pw-story__now">NOW</text>
          {c.lines.map((l, i) => <path key={i} d={l.d} fill="none" stroke={l.colour} strokeWidth={2.5} strokeLinejoin="round" style={{ filter: `drop-shadow(0 0 4px ${l.colour})` }} />)}
          {c.dots.map((d, i) => <circle key={i} cx={d.x} cy={d.y} r={d.r} fill={d.fill} stroke={d.stroke} strokeWidth={2} />)}
        </svg>
        <div className="pw-story__labels">
          {c.yTicks.map((t, i) => <div key={`y${i}`} className="pw-story__tick" style={{ transform: `translate(48px, ${t.y}px) translate(-100%, -50%)` }}>{t.label}</div>)}
          {c.xTicks.map((t, i) => <div key={`x${i}`} className="pw-story__tick" style={{ transform: `translate(${t.x}px, 185px) translate(-50%, -50%)` }}>{t.label}</div>)}
          {c.refs.map((r, i) => <div key={`r${i}`} className="pw-story__ref" style={{ color: r.colour, transform: `translate(1104px, ${r.y}px) translate(0, -50%)` }}>{r.label}</div>)}
          {c.names.map((n, i) => <div key={`n${i}`} className="pw-story__name" style={{ color: n.colour, transform: `translate(${n.x}px, ${n.y}px) translate(${n.right ? "-100%" : "0"}, -50%)` }}>{n.text}</div>)}
          {laps.length === 0 && <div className="pw-story__empty">Every lap of the session lands here.</div>}
        </div>
      </div>
    </section>
  );
}

function Moments({ state }: { state: DashboardState }) {
  const colours = new Map(state.rigs.map((r) => [r.rig_id, r]));
  const events = state.pitEvents.slice(0, 5);
  return (
    <section className="pw-moments">
      <div className="pw-colhead pw-colhead--small">
        <div className="pw-colhead__title"><span className="pw-tick" />MOMENTS</div>
        <div className="pw-hatch" />
        <div className="pw-dim">LAST 5</div>
      </div>
      {events.length === 0 && <p className="pw-moments__empty">Personal bests, records and new drivers show up here.</p>}
      {events.map((e, k) => {
        const rig = colours.get(e.rig_id);
        const d = new Date(e.at);
        return (
          <div key={`${e.at}-${k}`} className="pw-event" style={{ opacity: k === 0 ? 1 : 1 - k * 0.1 }}>
            <div className="pw-event__time">{`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`}</div>
            <div className="pw-event__stripe" style={{ background: rig?.colour ?? COL.n }} />
            <div className="pw-event__name">{(e.driver ?? rig?.name ?? "").toUpperCase()}</div>
            <div className="pw-event__label">{e.label}</div>
            <div className="pw-event__val" style={{ color: COL[e.tone], textDecoration: e.strike ? "line-through" : "none" }}>{e.value}</div>
          </div>
        );
      })}
    </section>
  );
}
