import { useEffect, useState } from "react";
import { formatLapTime } from "../format";
import type { DashboardState } from "../state/reducer";
import { Tab } from "./Motifs";
import { Qr } from "./Qr";

/** How long the TV shows a new story card's QR code. */
export const CARD_QR_MS = 30_000;

/** Lower-left card with a QR code to the session card that was just made (30 s, not full screen). */
export function CardQr({ state }: { state: DashboardState }) {
  const [now, setNow] = useState(() => Date.now());
  const latest = state.cards[state.cards.length - 1];
  const showing = latest && state.features.sharing && now - latest.at < CARD_QR_MS ? latest : null;
  useEffect(() => {
    if (!latest) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [latest]);
  if (!showing) return null;
  const colour = state.rigs.find((r) => r.rig_id === showing.rig_id)?.colour ?? "var(--text-3)";
  return (
    <aside className="cardqr cutcard" role="status" style={{ "--rig-colour": colour } as React.CSSProperties}>
      <Qr text={showing.url} className="cardqr__code" />
      <div className="cardqr__text">
        <Tab left="Your session card" />
        <span className="cardqr__name">{showing.driver}</span>
        <span className="t2">Best lap <strong className="cardqr__time">{formatLapTime(showing.best_ms)}</strong></span>
        <span className="t3">Scan on the cafe Wi-Fi to save and share it</span>
      </div>
    </aside>
  );
}
