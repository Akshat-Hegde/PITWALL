import type { CarDetail, PerWheel } from "../schema";
import { tyreTempBand } from "./Gauges";

// ---- Top-down car: tyres, brakes, damage, slide meter, SAVE! -----------------------------------

const SLIDE_SHOW_MAX = 35; // degrees the car outline may rotate
const SAVE_SHOW_MS = 2500;

/** Damage percentage to a colour band for wings and floor. */
export function damageBand(pct: number | null | undefined): string {
  if (!pct) return "ok";
  if (pct <= 25) return "light";
  if (pct <= 60) return "heavy";
  return "severe";
}

// Tyre boxes in the 160 x 230 drawing: front-left, front-right, rear-left, rear-right.
const TYRES = [
  { x: 2, y: 34, w: 38, h: 44 },
  { x: 120, y: 34, w: 38, h: 44 },
  { x: 0, y: 146, w: 42, h: 52 },
  { x: 118, y: 146, w: 42, h: 52 },
];

interface CarProps {
  car: CarDetail | null;
  /** Clock for the SAVE! flash (Unix ms); defaults to now. */
  now?: number;
}

/** The car seen from above. It rotates with the slide angle and flashes SAVE! when a slide is caught. */
export function CarTopDown({ car, now = Date.now() }: CarProps) {
  const slide = car?.slide_deg ?? 0;
  const shown = Math.max(-SLIDE_SHOW_MAX, Math.min(SLIDE_SHOW_MAX, slide));
  const surface = car?.tyre_surface_c ?? null;
  const wear = car?.tyre_wear_pct ?? null;
  const brakes = car?.brake_c ?? null;
  const dmg = car?.damage ?? null;
  const at = (v: PerWheel | null, i: number) => (v ? v[i]! : null);
  const saving = car?.last_save_at != null && now - car.last_save_at < SAVE_SHOW_MS;
  const sliding = Math.abs(slide) >= 8;
  return (
    <div className={`topcar${saving ? " is-save" : ""}${sliding ? " is-sliding" : ""}`}>
      <svg viewBox="0 0 160 230" role="img"
           aria-label={`Tyres, damage and slide ${Math.round(Math.abs(slide))} degrees`}>
        <g transform={`rotate(${shown} 80 115)`}>
          {/* floor */}
          <path className={`topcar__floor dmg--${damageBand(dmg?.floor)}`}
                d="M48 84 L112 84 L116 184 L44 184 Z" />
          {/* front wing, two halves */}
          <rect className={`topcar__wing dmg--${damageBand(dmg?.front_wing_left)}`} x="8" y="6" width="71" height="14" />
          <rect className={`topcar__wing dmg--${damageBand(dmg?.front_wing_right)}`} x="81" y="6" width="71" height="14" />
          {/* nose, cockpit, sidepods, engine cover */}
          <path className="topcar__body"
                d="M74 20 L86 20 L90 68 L108 90 L110 150 L95 198 L65 198 L50 150 L52 90 L70 68 Z" />
          <ellipse className="topcar__cockpit" cx="80" cy="104" rx="10" ry="17" />
          {/* rear wing */}
          <rect className={`topcar__wing dmg--${damageBand(dmg?.rear_wing)}`} x="36" y="206" width="88" height="16" />
          {TYRES.map((r, i) => {
            const temp = at(surface, i);
            const w = at(wear, i);
            const b = at(brakes, i);
            const left = i % 2 === 0;
            return (
              <g key={i}>
                <rect className={`topcar__tyre band--${tyreTempBand(temp)}`} x={r.x} y={r.y} width={r.w} height={r.h} />
                <text className="topcar__temp" x={r.x + r.w / 2} y={r.y + r.h / 2 + 1}>{temp ? `${temp}°` : "–"}</text>
                <text className="topcar__wear" x={r.x + r.w / 2} y={r.y + r.h / 2 + 15}>
                  {w == null ? "" : `${Math.round(w)}%`}
                </text>
                {b != null && b > 0 && (
                  <text className="topcar__brake" x={left ? r.x + r.w + 3 : r.x - 3} y={r.y + r.h + 10}
                        textAnchor={left ? "start" : "end"}>
                    {b}°
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      {saving && (
        <div className="topcar__save" role="status">
          SAVE!
          {car?.last_save_peak_deg != null && <span>{Math.round(car.last_save_peak_deg)}°</span>}
        </div>
      )}
      <span className="topcar__slide">
        <span className="micro">Slide {Math.round(Math.abs(slide))}°</span>
        {car?.saves ? <span className="micro">{car.saves === 1 ? "1 save" : `${car.saves} saves`}</span> : null}
      </span>
    </div>
  );
}

// ---- Steering wheel --------------------------------------------------------------------------

/** F1-style wheel rotating with the driver's input: steer (-1..1) x half the lock-to-lock rotation. */
export function SteeringWheel({ steer, rotationDeg }: { steer: number | null; rotationDeg: number }) {
  const angle = steer == null ? 0 : Math.max(-1, Math.min(1, steer)) * (rotationDeg / 2);
  return (
    <div className="wheel">
      <svg viewBox="0 0 110 80" role="img" aria-label={`Steering ${Math.round(angle)} degrees`}>
        <g transform={`rotate(${angle} 55 40)`}>
          {/* side grips */}
          <rect className="wheel__grip" x="4" y="14" width="18" height="54" rx="8" />
          <rect className="wheel__grip" x="88" y="14" width="18" height="54" rx="8" />
          {/* body with the display, buttons and the centre marker on top */}
          <path className="wheel__face" d="M16 18 L94 18 L98 50 L84 66 L26 66 L12 50 Z" />
          <rect className="wheel__screen" x="38" y="25" width="34" height="16" rx="2" />
          {[28, 82].map((cx) => <circle key={cx} className="wheel__button" cx={cx} cy="33" r="3.5" />)}
          {[30, 45, 65, 80].map((cx) => <circle key={cx} className="wheel__knob" cx={cx} cy="54" r="3" />)}
          <rect className="wheel__marker" x="52" y="8" width="6" height="12" />
        </g>
      </svg>
      <span className="wheel__angle">{steer == null ? "–" : `${angle > 0 ? "+" : ""}${Math.round(angle)}°`}</span>
    </div>
  );
}
