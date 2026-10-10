import { useEffect, useState } from "react";
import { formatGear, formatLapTime, formatSpeed } from "../format";
import type { CarDetail, PerWheel, RigFrame, RigInfo } from "../schema";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { GForce, LapShareBars, brakeTempBand, tyreTempBand } from "./Gauges";
import { DriverName, PedalBars, TyreTag } from "./Timing";

/** Cars side by side; with more driving, the view pages through them. */
export const ONBOARD_PER_PAGE = 2;
export const ONBOARD_PAGE_MS = 7500;
const SAVE_SHOW_MS = 2500;
const SPEED_BAR_MAX_KPH = 360;

const ERS_MODE_TEXT: Record<string, string> = { none: "Off", medium: "Medium", hotlap: "Hotlap", overtake: "Overtake" };
const WHEELS = ["FL", "FR", "RL", "RR"] as const;
const DAMAGE_PARTS: [string, string][] = [
  ["front_wing_left", "Front wing L"],
  ["front_wing_right", "Front wing R"],
  ["rear_wing", "Rear wing"],
  ["floor", "Floor"],
  ["diffuser", "Diffuser"],
  ["sidepod", "Sidepod"],
];

/** Rigs to show onboard: the ones driving, else any with data. */
export function onboardRigs(state: DashboardState): RigInfo[] {
  const driving = state.rigs.filter((r) => state.frames[r.rig_id]?.state === "driving");
  return driving.length ? driving : state.rigs.filter((r) => (state.frames[r.rig_id]?.state ?? "no_data") !== "no_data");
}

function usePage(pages: number): number {
  const [page, setPage] = useState(0);
  useEffect(() => {
    if (pages <= 1) return;
    const timer = setInterval(() => setPage((p) => p + 1), ONBOARD_PAGE_MS);
    return () => clearInterval(timer);
  }, [pages]);
  return pages <= 1 ? 0 : page % pages;
}

export function OnboardView({ store, state }: { store: DashboardStore; state: DashboardState }) {
  const rigs = onboardRigs(state);
  const pages = Math.max(1, Math.ceil(rigs.length / ONBOARD_PER_PAGE));
  const page = usePage(pages);
  const shown = rigs.slice(page * ONBOARD_PER_PAGE, page * ONBOARD_PER_PAGE + ONBOARD_PER_PAGE);
  return (
    <main className="onboard">
      <header className="viewhead">
        <h1 className="viewhead__title">Onboard</h1>
        {pages > 1 && <span className="viewhead__sub t3">{page + 1} / {pages}</span>}
      </header>
      {shown.length === 0 ? (
        <p className="analysis__empty">Onboard data appears when a rig is on track.</p>
      ) : (
        <div className={`onboard__grid onboard__grid--${shown.length}`}>
          {shown.map((rig) => (
            <OnboardCar key={rig.rig_id} rig={rig} frame={state.frames[rig.rig_id]}
                        trail={store.gTrail.get(rig.rig_id) ?? []}
                        share={store.lapShare.thisLap(rig.rig_id)} last={store.lapShare.lastLap(rig.rig_id)}
                        rotationDeg={state.steeringRotationDeg} />
          ))}
        </div>
      )}
    </main>
  );
}

interface CarProps {
  rig: RigInfo;
  frame: RigFrame | undefined;
  trail: [number, number][];
  share: ReturnType<DashboardStore["lapShare"]["thisLap"]>;
  last: ReturnType<DashboardStore["lapShare"]["lastLap"]>;
  rotationDeg: number;
  now?: number;
}

function OnboardCar({ rig, frame, trail, share, last, rotationDeg, now = Date.now() }: CarProps) {
  const driving = frame?.state === "driving";
  const car = frame?.car ?? null;
  const lap = frame?.lap ?? null;
  const kph = driving ? frame?.speed_kph ?? null : null;
  const rpm = driving ? frame?.rpm ?? null : null;
  const maxRpm = frame?.max_rpm ?? null;
  const saving = car?.last_save_at != null && now - car.last_save_at < SAVE_SHOW_MS;
  return (
    <article className="obcar" style={{ "--rig-colour": rig.colour } as React.CSSProperties} aria-label={rig.name}>
      <header className="obcar__head">
        <DriverName rig={rig} frame={frame} />
        <TyreTag frame={frame} />
        <span className="obcar__lap">
          <span className="label">{lap ? `Lap ${lap.number}` : "Lap"}</span>
          <span className={lap && !lap.valid ? "is-invalid" : ""}>{formatLapTime(driving ? lap?.current_ms : null)}</span>
        </span>
      </header>

      <section className="obcar__drive">
        <div className="speed speed--xl">
          <div className="speed__nums">
            <span className="speed__value">{formatSpeed(kph)}</span>
            <span className="unit">km/h</span>
            <span className="speed__gear">{driving ? formatGear(frame?.gear) : "–"}</span>
          </div>
          <span className="bar">
            <span className="bar__fill" style={{ width: `${kph == null ? 0 : Math.min(100, (kph / SPEED_BAR_MAX_KPH) * 100)}%` }} />
          </span>
        </div>
        <div className="obcar__inputs">
          <Meter label="Revs" pct={rpm != null && maxRpm ? (rpm / maxRpm) * 100 : null}
                 value={rpm == null ? "–" : rpm.toLocaleString("en-US")} unit="rpm" />
          <PedalBars frame={driving ? frame : undefined} />
          <Steering steer={driving ? car?.steer ?? null : null} rotationDeg={rotationDeg} />
        </div>
      </section>

      <section className="obcar__mid">
        <div className="obcar__block">
          <span className="label obcar__title">G-force</span>
          <GForce lat={driving ? car?.g_lat ?? null : null} long={driving ? car?.g_long ?? null : null}
                  trail={driving ? trail : []} />
        </div>
        <div className="obcar__block">
          <span className="label obcar__title">Tyres and brakes</span>
          <Tyres car={car} />
        </div>
      </section>

      <section className="obcar__systems">
        <Stat label="Fuel" value={car?.fuel_kg == null ? "–" : car.fuel_kg.toFixed(1)} unit="kg"
              sub={car?.fuel_laps == null ? null : `${car.fuel_laps >= 0 ? "+" : ""}${car.fuel_laps.toFixed(1)} laps`} />
        <div className="field obcar__ers">
          <span className="label">ERS {car?.ers_mode ? `· ${ERS_MODE_TEXT[car.ers_mode] ?? car.ers_mode}` : ""}</span>
          <span className="field__value">{car?.ers_pct == null ? "–" : Math.round(car.ers_pct)}<span className="unit">%</span></span>
          <span className="bar"><span className="bar__fill" style={{ width: `${Math.max(0, Math.min(100, car?.ers_pct ?? 0))}%` }} /></span>
        </div>
        <Stat label="DRS" value={!driving ? "–" : car?.drs_open ? "Open" : car?.drs_allowed ? "Ready" : "Off"}
              className={car?.drs_open && driving ? "is-on" : ""} />
        <Stat label="Top speed" value={car?.top_speed_kph ?? "–"} unit="km/h" />
        <div className="field obcar__slide">
          <span className="label">Slide</span>
          <span className="field__value">
            {driving && car?.slide_deg != null ? Math.round(Math.abs(car.slide_deg)) : "–"}
            <span className="unit">°</span>
            {saving && (
              <span className="save" role="status">
                Save!{car?.last_save_peak_deg != null && ` ${Math.round(car.last_save_peak_deg)}°`}
              </span>
            )}
          </span>
          <span className="t2">{car?.saves ? `${car.saves} ${car.saves === 1 ? "save" : "saves"}` : "No saves yet"}</span>
        </div>
      </section>

      <section className="obcar__bottom">
        <div className="obcar__block">
          <span className="label obcar__title">This lap · tick = last lap</span>
          <LapShareBars share={driving ? share : null} last={last} />
        </div>
        <div className="obcar__block">
          <span className="label obcar__title">Damage</span>
          <Damage damage={car?.damage ?? null} />
        </div>
      </section>
    </article>
  );
}

function Stat({ label, value, unit, sub = null, className = "" }: { label: string; value: React.ReactNode;
  unit?: string; sub?: string | null; className?: string }) {
  return (
    <div className={`field ${className}`}>
      <span className="label">{label}</span>
      <span className="field__value">{value}{unit && <span className="unit">{unit}</span>}</span>
      {sub && <span className="t2">{sub}</span>}
    </div>
  );
}

function Meter({ label, pct, value, unit }: { label: string; pct: number | null; value: string; unit: string }) {
  return (
    <div className="meter">
      <span className="label">{label}</span>
      <span className="bar"><span className="bar__fill" style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%` }} /></span>
      <span className="meter__value">{value}<span className="unit">{unit}</span></span>
    </div>
  );
}

/** Steering as a centred bar (no wheel icon): left of centre is left lock. */
function Steering({ steer, rotationDeg }: { steer: number | null; rotationDeg: number }) {
  const s = steer == null ? 0 : Math.max(-1, Math.min(1, steer));
  const deg = Math.round(s * (rotationDeg / 2));
  return (
    <div className="meter meter--steer">
      <span className="label">Steering</span>
      <span className="bar bar--centred">
        <span className="bar__fill" style={{ left: `${50 + Math.min(0, s) * 50}%`, width: `${Math.abs(s) * 50}%` }} />
        <span className="bar__centre" />
      </span>
      <span className="meter__value">{steer == null ? "–" : `${deg > 0 ? "+" : ""}${deg}`}<span className="unit">°</span></span>
    </div>
  );
}

function Tyres({ car }: { car: CarDetail | null }) {
  const at = (v: PerWheel | null | undefined, i: number) => (v ? v[i]! : null);
  return (
    <div className="tyres">
      {WHEELS.map((w, i) => {
        const temp = at(car?.tyre_surface_c, i);
        const inner = at(car?.tyre_inner_c, i);
        const wear = at(car?.tyre_wear_pct, i);
        const psi = at(car?.tyre_pressure_psi, i);
        const brake = at(car?.brake_c, i);
        return (
          <div key={w} className="tyre-block">
            <span className="label">{w}</span>
            <span className={`tyre-block__temp temp--${tyreTempBand(temp)}`}>{temp ? `${Math.round(temp)}°` : "–"}</span>
            <span className="tyre-block__row">
              <span className="t2">Wear</span>
              <span>{wear == null ? "–" : `${Math.round(wear)}%`}</span>
            </span>
            <span className="tyre-block__row">
              <span className="t2">Inner</span>
              <span>{inner ? `${Math.round(inner)}°` : "–"}</span>
            </span>
            <span className="tyre-block__row">
              <span className="t2">PSI</span>
              <span>{psi == null ? "–" : psi.toFixed(1)}</span>
            </span>
            <span className="tyre-block__row">
              <span className="t2">Brake</span>
              <span className={`temp--${brakeTempBand(brake)}`}>{brake ? `${Math.round(brake)}°` : "–"}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Damage({ damage }: { damage: Record<string, number> | null }) {
  return (
    <div className="damage">
      {DAMAGE_PARTS.map(([key, label]) => {
        const v = damage?.[key] ?? null;
        return (
          <div key={key} className="damage__row">
            <span className="share__label">{label}</span>
            <span className="bar damage__bar">
              <span className={`bar__fill${v && v > 50 ? " is-bad" : ""}`} style={{ width: `${Math.min(100, v ?? 0)}%` }} />
            </span>
            <span className={v ? "" : "t3"}>{v == null ? "–" : `${Math.round(v)}%`}</span>
          </div>
        );
      })}
    </div>
  );
}
