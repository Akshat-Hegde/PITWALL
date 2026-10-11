import { formatDelta, formatGear, formatLapTime, formatSector, formatSpeed } from "../format";
import type { ComparisonEntry, RigFrame, RigInfo, SectorTime } from "../schema";
import { MINI_SECTORS, type MiniRating } from "../state/laptrace";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { Avatar, Barcode, SlantBar, Tab } from "./Motifs";

/** Cards (two lines of detail per car) up to this many rigs; a one-line-per-car tower above it. */
export const MAX_CARDS = 4;
const SPEED_BAR_MAX_KPH = 360;

const STATE_TEXT: Record<RigFrame["state"], string> = {
  driving: "On track",
  in_menu_paused: "In menu",
  no_data: "No data",
};

/** Rigs in running order: best lap on the shown track first, then the rest in rig order. */
export function runningOrder(state: DashboardState, trackKey: string | null): { rig: RigInfo; position: number | null }[] {
  const best = (rig: RigInfo) => {
    const f = state.frames[rig.rig_id];
    return f && f.session.track_key === trackKey && f.best ? f.best.lap_ms : null;
  };
  const sorted = state.rigs
    .map((rig, i) => ({ rig, i, ms: best(rig) }))
    .sort((a, b) => (a.ms ?? Infinity) - (b.ms ?? Infinity) || a.i - b.i);
  return sorted.map(({ rig, ms }, i) => ({ rig, position: ms == null ? null : i + 1 }));
}

interface Props {
  store: DashboardStore;
  state: DashboardState;
  trackKey: string | null;
  /** Today's fastest lap on the shown track: that best is purple, other bests green. */
  sessionBestMs: number | null;
}

export function Timing({ store, state, trackKey, sessionBestMs }: Props) {
  const order = runningOrder(state, trackKey);
  const deltas = new Map((state.comparison?.rigs ?? []).map((c) => [c.rig_id, c]));
  const cards = order.length <= MAX_CARDS;
  const density = order.length <= 2 ? "l" : order.length <= MAX_CARDS ? "m" : "s";
  return (
    <section className={`timing timing--${density}`} aria-label="Timing"
             style={{ "--rows": Math.max(order.length, cards ? 2 : 6) } as React.CSSProperties}>
      {!cards && <TowerHead />}
      {order.map(({ rig, position }) => {
        const props: RowProps = {
          rig, position, frame: state.frames[rig.rig_id], delta: deltas.get(rig.rig_id), sessionBestMs,
          minis: store.laps.liveMinis(rig.rig_id)?.ratings ?? [],
        };
        return cards ? <Card key={rig.rig_id} {...props} /> : <TowerRow key={rig.rig_id} {...props} />;
      })}
    </section>
  );
}

interface RowProps {
  rig: RigInfo;
  position: number | null;
  frame: RigFrame | undefined;
  delta: ComparisonEntry | undefined;
  sessionBestMs: number | null;
  minis: MiniRating[];
}

function rigStyle(rig: RigInfo): React.CSSProperties {
  return { "--rig-colour": rig.colour } as React.CSSProperties;
}

function Card({ rig, position, frame, delta, sessionBestMs, minis }: RowProps) {
  const state = frame?.state ?? "no_data";
  const driving = state === "driving";
  const lap = frame?.lap ?? null;
  return (
    <article className={`card is-${state.replace(/_/g, "-")}`} style={rigStyle(rig)}
             aria-label={`${rig.name}: ${frame?.driver ?? rig.name}`}>
      <header className="card__head">
        <Position position={position} />
        <Avatar name={frame?.driver ?? rig.name} />
        <DriverName rig={rig} frame={frame} />
        <TyreTag frame={frame} />
        <LapTab frame={frame} />
      </header>
      {state === "no_data" ? (
        <p className="card__hint">
          Nothing from {rig.address}. In F1 25 turn UDP telemetry on and drive out in Time Trial.
        </p>
      ) : (
        <div className="card__body">
          <Speed frame={driving ? frame : undefined} />
          <PedalBars frame={driving ? frame : undefined} />
          <Clock frame={frame} />
          <Sectors frame={frame} minis={minis} />
          <Field label="Last">{formatLapTime(lap?.last_ms ?? null)}</Field>
          <BestField frame={frame} sessionBestMs={sessionBestMs} />
          <GapField delta={delta} />
        </div>
      )}
    </article>
  );
}

function TowerHead() {
  return (
    <div className="trow trow--head" aria-hidden="true">
      <span>Pos</span>
      <span>Driver</span>
      <span>Tyre</span>
      <span className="r">Lap time</span>
      <span>Sectors</span>
      <span className="r">Last</span>
      <span className="r">Best</span>
      <span className="r">Gap</span>
      <span className="r">Speed</span>
      <span>Thr / Brk</span>
    </div>
  );
}

function TowerRow({ rig, position, frame, delta, sessionBestMs, minis }: RowProps) {
  const state = frame?.state ?? "no_data";
  const driving = state === "driving";
  const lap = frame?.lap ?? null;
  const live = delta?.live_delta_ms ?? null;
  return (
    <div className={`trow is-${state.replace(/_/g, "-")}`} style={rigStyle(rig)}
         aria-label={`${rig.name}: ${frame?.driver ?? rig.name}, ${STATE_TEXT[state]}`}>
      <Position position={position} />
      <DriverName rig={rig} frame={frame} />
      <TyreTag frame={frame} />
      <span className={`trow__clock r ${clockClass(frame)}`}>
        {state === "driving" && lap ? formatLapTime(lap.current_ms) : <span className="t3">{STATE_TEXT[state]}</span>}
      </span>
      <Sectors frame={frame} minis={minis} bare />
      <span className={`r${lap?.last_ms == null ? " t3" : ""}`}>{formatLapTime(lap?.last_ms ?? null)}</span>
      <span className={`r ${bestClass(frame, sessionBestMs)}`}>{formatLapTime(frame?.best?.lap_ms ?? null)}</span>
      <span className={`r ${gapClass(live)}`}>{live == null ? "–" : formatDelta(live, 2)}</span>
      <span className="trow__speed r">
        {driving ? formatSpeed(frame?.speed_kph) : "–"}
        <span className="trow__gear">{driving ? formatGear(frame?.gear) : ""}</span>
      </span>
      <PedalBars frame={driving ? frame : undefined} bare />
    </div>
  );
}

// ---- Pieces --------------------------------------------------------------------------------------

/** Motif 5 angled tab: LAP 4 | PUSH, LAP 4 | INVALID, IN MENU, NO DATA. */
function LapTab({ frame }: { frame: RigFrame | undefined }) {
  const state = frame?.state ?? "no_data";
  const lap = frame?.lap ?? null;
  if (state !== "driving" || !lap) return <Tab left={STATE_TEXT[state]} className="tab-badge--muted" />;
  if (lap.distance_m < 0) return <Tab left={`Lap ${lap.number}`} right="Out lap" className="tab-badge--muted" />;
  return <Tab left={`Lap ${lap.number}`} right={lap.valid ? "Push" : "Invalid"}
              className={lap.valid ? "" : "tab-badge--muted"} />;
}

function Position({ position }: { position: number | null }) {
  return <span className="pos">{position ?? "–"}</span>;
}

/** "8 min left" from a staff booking; null without a timer. */
export function timeLeft(frame: RigFrame | undefined, now = Date.now()): { text: string; low: boolean } | null {
  const ends = frame?.booking?.ends_at;
  if (ends == null) return null;
  const ms = ends - now;
  if (ms <= 0) return { text: "Time up", low: true };
  const min = Math.ceil(ms / 60_000);
  return { text: min <= 1 ? "Last minute" : `${min} min left`, low: ms <= 5 * 60_000 };
}

export function DriverName({ rig, frame, sub = true }: { rig: RigInfo; frame: RigFrame | undefined; sub?: boolean }) {
  const pb = frame?.personal_best && frame.state !== "no_data" ? frame.personal_best.lap_ms : null;
  const left = timeLeft(frame);
  return (
    <span className="who">
      <span className="stripe" aria-hidden="true" />
      <span className="who__text">
        <span className="who__name">{frame?.driver ?? rig.name}</span>
        {sub && (
          <span className="who__sub">
            {rig.name}
            {left && <span className={left.low ? "time-left is-low" : "time-left"}> · {left.text}</span>}
            {pb != null && <span> · PB {formatLapTime(pb)}</span>}
          </span>
        )}
      </span>
    </span>
  );
}

const COMPOUND_LETTER: Record<string, string> = { soft: "S", medium: "M", hard: "H", inter: "I", wet: "W" };

export function TyreTag({ frame }: { frame: RigFrame | undefined }) {
  const tyre = frame?.tyre;
  if (!tyre || frame?.state === "no_data") return <span className="tyre" />;
  return (
    <span className="tyre" title={`${tyre.label} (${tyre.compound})`}>
      <span className={`tyre__letter compound-text--${tyre.compound}`} aria-hidden="true">
        {COMPOUND_LETTER[tyre.compound] ?? "?"}
      </span>
      <span className="tyre__label">{tyre.label}</span>
      {tyre.age_laps != null && <span className="tyre__age">{tyre.age_laps}L</span>}
    </span>
  );
}

function Field({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`field ${className}`}>
      <span className="label">{label}</span>
      <span className="field__value">{children}</span>
    </div>
  );
}

function clockClass(frame: RigFrame | undefined): string {
  const lap = frame?.lap;
  if (!lap || frame?.state !== "driving") return "t3";
  return lap.valid ? "" : "is-invalid";
}

function bestClass(frame: RigFrame | undefined, sessionBestMs: number | null): string {
  const ms = frame?.best?.lap_ms ?? null;
  if (ms == null) return "t3";
  return ms === sessionBestMs ? "c-purple" : "c-green";
}

function gapClass(live: number | null): string {
  return live == null ? "t3" : live <= 0 ? "c-green" : "c-yellow";
}

function Clock({ frame }: { frame: RigFrame | undefined }) {
  const lap = frame?.lap ?? null;
  const live = frame?.state === "driving";
  return (
    <Field label={lap && !lap.valid ? "Lap invalid" : "Lap time"} className="field--clock">
      <span className={clockClass(frame)}>{formatLapTime(live && lap ? lap.current_ms : null)}</span>
    </Field>
  );
}

function BestField({ frame, sessionBestMs }: { frame: RigFrame | undefined; sessionBestMs: number | null }) {
  return (
    <Field label="Best">
      <span className={bestClass(frame, sessionBestMs)}>{formatLapTime(frame?.best?.lap_ms ?? null)}</span>
    </Field>
  );
}

function GapField({ delta }: { delta: ComparisonEntry | undefined }) {
  const live = delta?.live_delta_ms ?? null;
  return (
    <Field label="Gap">
      <span className={gapClass(live)}>{live == null ? "–" : formatDelta(live, 2)}</span>
    </Field>
  );
}

const RATING_CLASS: Record<string, string> = {
  session_best: "c-purple",
  personal_best: "c-green",
  normal: "",
};

/** S1-S3 as text (purple / green / white) with the lap's mini-sectors as short lines underneath. */
function Sectors({ frame, minis, bare = false }: { frame: RigFrame | undefined; minis: MiniRating[]; bare?: boolean }) {
  const lap = frame?.lap ?? null;
  const live = frame?.state === "driving";
  const sectors: (SectorTime | null)[] = lap?.sectors ?? [null, null, null];
  const perSector = MINI_SECTORS / 3;
  return (
    <div className={`sectors${bare ? " sectors--bare" : ""}`}>
      {[0, 1, 2].map((i) => {
        const s = live ? sectors[i] ?? null : null;
        const current = live && lap && !s && lap.sector === i;
        return (
          <div key={i} className={`sector${current ? " is-current" : ""}`}>
            {!bare && <span className="label">S{i + 1}</span>}
            <span className={`sector__time ${s ? RATING_CLASS[s.rating ?? "normal"] ?? "" : "t3"}`}>
              {formatSector(s?.ms ?? null)}
            </span>
            <span className="minis" aria-hidden="true">
              {Array.from({ length: perSector }, (_, k) => {
                const r = live ? minis[i * perSector + k] : undefined;
                return <span key={k} className={`mini${r ? ` mini--${r}` : ""}`} />;
              })}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function Speed({ frame, ticks = 36 }: { frame: RigFrame | undefined; ticks?: number }) {
  const kph = frame?.speed_kph ?? null;
  return (
    <div className="speed">
      <Barcode value={kph} max={SPEED_BAR_MAX_KPH} ticks={ticks} />
      <div className="speed__nums">
        <span className="speed__value">{formatSpeed(kph)}</span>
        <span className="unit">km/h</span>
        <span className="speed__gear">{formatGear(frame?.gear)}</span>
      </div>
    </div>
  );
}

export function PedalBars({ frame, bare = false }: { frame: RigFrame | undefined; bare?: boolean }) {
  const thr = frame ? Math.min(1, Math.max(0, frame.throttle ?? 0)) : null;
  const brk = frame ? Math.min(1, Math.max(0, frame.brake ?? 0)) : null;
  return (
    <div className={`pedals${bare ? " pedals--bare" : ""}`}>
      {(
        [
          ["Throttle", "thr", thr, "light"],
          ["Brake", "brk", brk, "accent"],
        ] as const
      ).map(([label, kind, value, tone]) => (
        <div key={kind} className={`pedal pedal--${kind}`}>
          {!bare && <span className="label">{label}</span>}
          <SlantBar value={value} tone={tone} label={label} />
          {!bare && <span className="pedal__pct">{value == null ? "–" : Math.round(value * 100)}</span>}
        </div>
      ))}
    </div>
  );
}
