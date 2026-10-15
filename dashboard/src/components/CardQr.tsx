import { useEffect, useState } from "react";
import { formatLapTime } from "../format";
import { hubNow } from "../state/hubclock";
import type { DashboardState } from "../state/reducer";
import { Tab } from "./Motifs";
import { Qr, WifiQr } from "./Qr";

/** How long the TV shows a new story card's QR code. */
export const CARD_QR_MS = 30_000;

/** Lower-left card with a QR code to the story card that was just made (30 s, not full screen), and the cafe's
 *  "Join our Wi-Fi" QR beside it when a guest network is set (SSID as text, never the password). */
export function CardQr({ state }: { state: DashboardState }) {
  const [now, setNow] = useState(() => hubNow());
  const latest = state.cards[state.cards.length - 1];
  const showing = latest && state.features.sharing && now - latest.at < CARD_QR_MS ? latest : null;
  useEffect(() => {
    if (!latest) return;
    setNow(hubNow());
    const timer = setInterval(() => setNow(hubNow()), 1000);
    return () => clearInterval(timer);
  }, [latest]);
  if (!showing) return null;
  const colour = state.rigs.find((r) => r.rig_id === showing.rig_id)?.colour ?? "var(--text-3)";
  const race = showing.card_kind === "race";
  const wifi = state.cafe.wifi ?? null;
  return (
    <aside className="cardqr cutcard" role="status" style={{ "--rig-colour": colour } as React.CSSProperties}>
      <Qr text={showing.url} className="cardqr__code" />
      <div className="cardqr__text">
        <Tab left={race ? "Your race card" : "Your session card"}
             right={race && showing.position != null ? `P${showing.position}` : null} />
        <span className="cardqr__name">{showing.driver}</span>
        <span className="t2">Best lap <strong className="cardqr__time">{formatLapTime(showing.best_ms)}</strong></span>
        <span className="t3">Scan on the cafe Wi-Fi to save and share it</span>
      </div>
      {wifi && (
        <div className="cardqr__wifi">
          <WifiQr wifi={wifi} className="cardqr__code" />
          <div className="cardqr__text">
            <Tab left="Join our Wi-Fi" className="tab-badge--muted" />
            <span className="cardqr__ssid">{wifi.ssid}</span>
            <span className="t3">Scan to join, then scan your card</span>
          </div>
        </div>
      )}
    </aside>
  );
}
