import { useEffect, useState } from "react";
import { formatLapTime, formatRaceTime, ordinal, raceResult } from "../format";
import type { RaceDriver, RacePodiumMoment } from "../schema";
import type { DashboardState } from "../state/reducer";
import { EdgeLines, Flash, Tab } from "./Motifs";
import { Qr, WifiQr } from "./Qr";

/** The race podium moment (40 s, MOMENT_MS) shows the podium this long, then "Grab your card". */
export const RACE_PODIUM_PHASE_MS = 15_000;
/** At most this many QR tiles of drivers on the "Grab your card" screen. */
export const GRID_MAX = 10;

/**
 * A race with 2 or more cafe drivers just ended. Phase 1: the top three cafe drivers on a podium (P1 centre,
 * raised), each with a big QR code to their race card beside the name. Phase 2: every finisher's QR, plus the
 * cafe's guest Wi-Fi QR so phones can reach the hub. Only the SSID is ever text; the password lives in the QR.
 */
export function RacePodium({ m, state }: { m: RacePodiumMoment; state: DashboardState }) {
  const [phase, setPhase] = useState<"podium" | "grid">("podium");
  useEffect(() => {
    const timer = setTimeout(() => setPhase("grid"), RACE_PODIUM_PHASE_MS);
    return () => clearTimeout(timer);
  }, [m.at]);
  const colour = (rigId: string) => state.rigs.find((r) => r.rig_id === rigId)?.colour ?? "var(--text-3)";
  const rigName = (rigId: string) => state.rigs.find((r) => r.rig_id === rigId)?.name ?? null;
  const wifi = m.wifi ?? state.cafe.wifi ?? null;
  const drivers = [...m.drivers].sort((a, b) => a.rank - b.rank);
  return phase === "podium"
    ? <PodiumPhase m={m} drivers={drivers.slice(0, 3)} colour={colour} rigName={rigName} />
    : <GridPhase m={m} drivers={drivers.slice(0, GRID_MAX)} colour={colour} wifi={wifi} />;
}

/** Font size (rem) for a podium name beside its QR: the longest word must fit the ~11 rem column on one line. */
export function nameRem(name: string): number {
  const longest = Math.max(...name.split(/\s+/).map((w) => w.length));
  return longest <= 9 ? 1.7 : longest <= 11 ? 1.4 : longest <= 14 ? 1.15 : 1;
}

const rigStyle = (colour: string) => ({ "--rig-colour": colour }) as React.CSSProperties;

function PodiumPhase({ m, drivers, colour, rigName }: {
  m: RacePodiumMoment; drivers: RaceDriver[]; colour: (rigId: string) => string; rigName: (rigId: string) => string | null;
}) {
  // P2, P1, P3 like a podium (P1 in the centre); two drivers: P2, P1.
  const order = [1, 0, 2].map((i) => drivers[i]).filter((d): d is RaceDriver => d !== undefined);
  return (
    <div className="racepodium racepodium--podium">
      <header className="racepodium__head">
        <Tab left="Race result" right={m.session_type ?? "Race"} />
        <h1 className="racepodium__title">{m.track_name ?? "Race"}</h1>
      </header>
      <div className={`racepodium__podium racepodium__podium--n${order.length}`}>
        {order.map((d) => (
          <section key={d.card_token} className={`racepodium__step racepodium__step--r${d.rank} cutcard`}
                   style={rigStyle(colour(d.rig_id))}>
            {d.rank === 1 && <Flash width={170} height={84} corner="top-right" rules={false}
                                    className="racepodium__flash" />}
            <div className="racepodium__top">
              <span className={`racepodium__pos${d.rank === 1 ? " racepodium__pos--win" : ""}`}>
                {raceResult(d.status, d.position)}
              </span>
              <Tab left={`${ordinal(d.rank)} here`} right={rigName(d.rig_id)} className="racepodium__tab" />
            </div>
            <div className="racepodium__body">
              <Qr text={d.card_url} className="racepodium__qr" />
              <div className="racepodium__who">
                <span className="racepodium__name" style={{ fontSize: `${nameRem(d.driver)}rem` }}>{d.driver}</span>
                <span className="racepodium__stat">
                  <span className="label">Best lap</span>
                  <span className="racepodium__value">{formatLapTime(d.best_lap_ms)}</span>
                </span>
                <span className="racepodium__stat">
                  <span className="label">Race time</span>
                  <span className="racepodium__value">{formatRaceTime(d.total_time_s)}</span>
                </span>
                <span className="racepodium__scan">Scan for your card</span>
              </div>
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function GridPhase({ m, drivers, colour, wifi }: {
  m: RacePodiumMoment; drivers: RaceDriver[]; colour: (rigId: string) => string; wifi: { ssid: string; qr: string } | null;
}) {
  const tiles = drivers.length + (wifi ? 1 : 0);
  const cols = tiles <= 5 ? tiles : Math.ceil(tiles / 2);
  return (
    <div className="racepodium racepodium--grid">
      <header className="racepodium__head racepodium__head--grid">
        <Tab left="Race result" right={m.track_name ?? m.session_type ?? "Race"} />
        <h1 className="racepodium__title">Grab your card</h1>
        <span className="racepodium__sub">Scan your code to save your race card for your story</span>
      </header>
      <div className={`racepodium__grid${tiles > 5 ? " racepodium__grid--two" : ""}`}
           style={{ "--cols": cols } as React.CSSProperties}>
        {drivers.map((d) => (
          <section key={d.card_token} className="racepodium__tile racepodium__tile--driver cutcard"
                   style={rigStyle(colour(d.rig_id))}>
            <Qr text={d.card_url} className="racepodium__tileqr" />
            <span className="racepodium__tilename">{d.driver}</span>
            <span className="racepodium__tilepos">{raceResult(d.status, d.position)}</span>
          </section>
        ))}
        {wifi && (
          <section className="racepodium__tile racepodium__tile--wifi cutcard">
            <WifiQr wifi={wifi} className="racepodium__tileqr" />
            <span className="racepodium__tilename">Join our Wi-Fi</span>
            <span className="racepodium__ssid">{wifi.ssid}</span>
          </section>
        )}
      </div>
      <EdgeLines className="racepodium__lines" width={360} height={140} from="right" />
    </div>
  );
}
