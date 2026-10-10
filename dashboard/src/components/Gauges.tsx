import type { CarDetail } from "../schema";
import type { LapShare } from "../state/lapshare";

// ---- Speed dial --------------------------------------------------------------------------------

const DIAL_MAX_KPH = 360;
const DIAL_START = 135; // degrees, 0 = right, clockwise
const DIAL_SWEEP = 270;

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

function arc(cx: number, cy: number, r: number, from: number, to: number): string {
  const [x0, y0] = polar(cx, cy, r, from);
  const [x1, y1] = polar(cx, cy, r, to);
  return `M ${x0} ${y0} A ${r} ${r} 0 ${to - from > 180 ? 1 : 0} 1 ${x1} ${y1}`;
}

/** 270° speed dial with the speed in the middle and the gear underneath. */
export function SpeedDial({ speed, gear, colour }: { speed: number | null; gear: string; colour: string }) {
  const k = speed == null ? 0 : Math.min(1, Math.max(0, speed / DIAL_MAX_KPH));
  const end = DIAL_START + DIAL_SWEEP * Math.max(k, 0.002);
  const ticks = [];
  for (let v = 0; v <= DIAL_MAX_KPH; v += 40) {
    const deg = DIAL_START + (DIAL_SWEEP * v) / DIAL_MAX_KPH;
    const [x0, y0] = polar(100, 100, 74, deg);
    const [x1, y1] = polar(100, 100, v % 120 === 0 ? 64 : 68, deg);
    ticks.push(<line key={v} x1={x0} y1={y0} x2={x1} y2={y1} className="dial__tick" />);
  }
  return (
    <svg className="dial" viewBox="0 0 200 186" role="img" aria-label={`${speed ?? "unknown"} km/h, gear ${gear}`}>
      <path d={arc(100, 100, 84, DIAL_START, DIAL_START + DIAL_SWEEP)} className="dial__track" />
      {speed != null && <path d={arc(100, 100, 84, DIAL_START, end)} className="dial__value" style={{ stroke: colour }} />}
      {ticks}
      <text x="100" y="98" className="dial__speed">{speed == null ? "–" : Math.round(speed)}</text>
      <text x="100" y="120" className="dial__unit">km/h</text>
      <text x="100" y="170" className="dial__gear" style={{ fill: colour }}>{gear}</text>
    </svg>
  );
}

// ---- Rev lights (F1 wheel style: green, red, blue) --------------------------------------------

const LEDS = 15;

export function RevLights({ pct, rpm }: { pct: number | null; rpm: number | null }) {
  const lit = pct == null ? 0 : Math.round((Math.min(100, Math.max(0, pct)) / 100) * LEDS);
  return (
    <div className="leds" aria-label={rpm == null ? "Revs unknown" : `${rpm} rpm`}>
      <div className="leds__row">
        {Array.from({ length: LEDS }, (_, i) => (
          <span key={i} className={`led led--${i < 5 ? "g" : i < 10 ? "r" : "b"}${i < lit ? " is-on" : ""}`} />
        ))}
      </div>
      <span className="leds__rpm">{rpm == null ? "–" : rpm.toLocaleString("en-US")} rpm</span>
    </div>
  );
}

// ---- Pedals ----------------------------------------------------------------------------------

export function Pedals({ throttle, brake }: { throttle: number | null; brake: number | null }) {
  const pct = (v: number | null) => Math.round(Math.min(1, Math.max(0, v ?? 0)) * 100);
  return (
    <div className="pedals2">
      {(
        [
          ["Throttle", "thr", throttle],
          ["Brake", "brk", brake],
        ] as const
      ).map(([label, kind, value]) => (
        <div key={kind} className={`pedal2 pedal2--${kind}`}>
          <span className="pedal2__track">
            <span className="pedal2__fill" style={{ height: `${pct(value)}%` }} />
          </span>
          <span className="pedal2__pct">{value == null ? "–" : pct(value)}</span>
          <span className="micro">{label}</span>
        </div>
      ))}
    </div>
  );
}

// ---- Tyres: four corners coloured by surface temperature, with wear ---------------------------

/** Surface temperature to a colour band (cold blue, working green, hot red). */
export function tyreTempBand(c: number | null): string {
  if (c == null || c <= 0) return "none";
  if (c < 70) return "cold";
  if (c < 85) return "cool";
  if (c < 105) return "ok";
  if (c < 115) return "warm";
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
        {has && <circle cx={x} cy={y} r="6" className="gforce__dot" />}
      </svg>
      <span className="gforce__value">{total == null ? "–" : `${total.toFixed(1)} g`}</span>
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
            <span className="label">{label}</span>
            <span className="share__track">
              <span className="share__fill" style={{ width: `${Math.min(100, value ?? 0)}%` }} />
              {prev != null && <span className="share__last" style={{ left: `${Math.min(100, prev)}%` }} />}
            </span>
            <span className="share__pct">{value == null ? "–" : `${Math.round(value)}%`}</span>
          </div>
        );
      })}
    </div>
  );
}

// ---- DRS / ERS / fuel ------------------------------------------------------------------------

const ERS_MODE_TEXT: Record<string, string> = { none: "Off", medium: "Medium", hotlap: "Hotlap", overtake: "Overtake" };

export function Systems({ car, inline = false }: { car: CarDetail | null; inline?: boolean }) {
  const drs = car?.drs_open ? "open" : car?.drs_allowed ? "ready" : "off";
  const ers = car?.ers_pct ?? null;
  return (
    <div className={`systems${inline ? " systems--inline" : ""}`}>
      <span className={`drs drs--${drs}`}>DRS</span>
      <div className="ers">
        <span className="micro ers__label">
          ERS {!inline && car?.ers_mode ? ERS_MODE_TEXT[car.ers_mode] ?? car.ers_mode : ""}
        </span>
        <span className="ers__track">
          <span className="ers__fill" style={{ width: `${Math.max(0, Math.min(100, ers ?? 0))}%` }} />
        </span>
        <span className="ers__pct">{ers == null ? "–" : `${Math.round(ers)}%`}</span>
      </div>
      <div className="fuel">
        <span className="micro">Fuel</span>
        <span className="fuel__value">{car?.fuel_kg == null ? "–" : `${car.fuel_kg.toFixed(1)} kg`}</span>
        {car?.fuel_laps != null && (
          <span className={`fuel__laps${car.fuel_laps < 0 ? " is-short" : ""}`}>
            {car.fuel_laps >= 0 ? "+" : ""}
            {car.fuel_laps.toFixed(1)} laps
          </span>
        )}
      </div>
    </div>
  );
}
