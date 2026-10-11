import type { LapShare } from "../state/lapshare";
import { SlantBar } from "./Motifs";

// ---- Tyre temperatures -------------------------------------------------------------------------

/** Surface temperature to a band; shown as text colour (cold blue, in range white, warm amber, hot red). */
export function tyreTempBand(c: number | null): string {
  if (c == null || c <= 0) return "none";
  if (c < 70) return "cold";
  if (c < 85) return "cool";
  if (c < 105) return "ok";
  if (c < 115) return "warm";
  return "hot";
}

/** Brake temperature band: cold below 300 °C, hot above 900 °C. */
export function brakeTempBand(c: number | null): string {
  if (c == null || c <= 0) return "none";
  if (c < 300) return "cold";
  if (c <= 900) return "ok";
  return "hot";
}

// ---- G-force circle --------------------------------------------------------------------------

const G_MAX = 5;

function gPoint(lat: number, long: number): [number, number] {
  return [
    60 + (Math.max(-G_MAX, Math.min(G_MAX, lat)) / G_MAX) * 50,
    60 - (Math.max(-G_MAX, Math.min(G_MAX, long)) / G_MAX) * 50,
  ];
}

/** Friction circle: the current g as a dot, with a fading trail of the last couple of seconds. */
export function GForce({ lat, long, trail = [] }: { lat: number | null; long: number | null;
                                                   trail?: [number, number][] }) {
  const has = lat != null && long != null;
  const [x, y] = has ? gPoint(lat!, long!) : [60, 60];
  const total = has ? Math.hypot(lat!, long!) : null;
  const points = trail.map(([a, b]) => gPoint(a, b));
  return (
    <div className="gforce">
      <svg viewBox="0 0 120 120" role="img" aria-label={total == null ? "g-force unknown" : `${total.toFixed(1)} g`}>
        {[1, 2, 3, 4, 5].map((g) => (
          <circle key={g} cx="60" cy="60" r={(g / G_MAX) * 50} className={`gforce__ring${g % 2 ? "" : " is-major"}`} />
        ))}
        <line x1="10" y1="60" x2="110" y2="60" className="gforce__axis" />
        <line x1="60" y1="10" x2="60" y2="110" className="gforce__axis" />
        {points.slice(1).map(([px, py], i) => {
          const [qx, qy] = points[i]!;
          return (
            <line key={i} x1={qx} y1={qy} x2={px} y2={py} className="gforce__trail"
                  style={{ opacity: ((i + 1) / points.length) * 0.85 }} />
          );
        })}
        {has && <circle cx={x} cy={y} r="4" className="gforce__dot" />}
      </svg>
      <div className="gforce__nums">
        <span className="field">
          <span className="label">Total</span>
          <span className="gforce__value">{total == null ? "–" : total.toFixed(1)}<span className="unit">g</span></span>
        </span>
        <span className="field">
          <span className="label">Lateral</span>
          <span>{lat == null ? "–" : Math.abs(lat).toFixed(1)}</span>
        </span>
        <span className="field">
          <span className="label">Long.</span>
          <span>{long == null ? "–" : long.toFixed(1)}</span>
        </span>
      </div>
    </div>
  );
}

// ---- Share of the lap: full throttle / heavy braking / cornering ------------------------------

const SHARE_ROWS: [keyof LapShare, string][] = [
  ["fullThrottle", "Full throttle"],
  ["heavyBraking", "Heavy braking"],
  ["cornering", "Cornering"],
];

/** "% lap time" bars: this lap so far, with a tick at last lap's value. */
export function LapShareBars({ share, last }: { share: LapShare | null; last: LapShare | null }) {
  return (
    <div className="share" aria-label="Share of this lap">
      {SHARE_ROWS.map(([key, label]) => {
        const value = share ? share[key] : null;
        const prev = last ? last[key] : null;
        return (
          <div key={key} className="share__row">
            <span className="share__label">{label}</span>
            <span className="share__bar">
              <SlantBar value={value == null ? null : value / 100} tone="rig" label={label} />
              {prev != null && <span className="share__last" style={{ left: `${Math.min(100, prev)}%` }} />}
            </span>
            <span className="share__pct">{value == null ? "–" : Math.round(value)}<span className="unit">%</span></span>
          </div>
        );
      })}
    </div>
  );
}
