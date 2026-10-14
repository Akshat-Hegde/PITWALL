import { useEffect, useRef, useState } from "react";
import { formatLapTime } from "../format";
import type { AnyStoryCard } from "../schema";
import { drawCard, raceCardText } from "./drawCard";
import { demoCard, demoRaceCard } from "./demo";

/** /card/<token>: the customer's session or race card. Draws the 1080 x 1920 image (an Instagram story's size);
 *  save it, then post it from the gallery. No Web Share of files: the LAN page is plain HTTP. */
export function CardPage({ token }: { token: string }) {
  const [card, setCard] = useState<AnyStoryCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (token === "demo" || token === "demo-race") {
      setCard(token === "demo" ? demoCard() : demoRaceCard());
      return;
    }
    fetch(`/api/cards/${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `The hub answered ${r.status}.`);
        return r.json() as Promise<AnyStoryCard>;
      })
      .then(setCard)
      .catch((e: Error) => setError(e.message));
  }, [token]);

  useEffect(() => {
    if (!card || !canvas.current) return;
    const accent = card.cafe.branding["--brand-accent"] ?? "#e10600";
    for (const [key, value] of Object.entries(card.cafe.branding)) {
      if (key.startsWith("--")) document.documentElement.style.setProperty(key, value);
    }
    document.title = card.kind === "race"
      ? `${card.driver}: ${raceCardText(card).big}`
      : `${card.driver}: ${formatLapTime(card.best_ms)}`;
    // Draw once the fonts are in, so the image uses Saira.
    const fonts = document.fonts
      ? Promise.all([
        document.fonts.load('900 100px "Saira Variable"'),
        document.fonts.load('600 30px "Saira Condensed"'),
        document.fonts.load('700 28px "Saira Condensed"'),
      ])
      : Promise.resolve();
    fonts.catch(() => undefined).finally(() => {
      if (canvas.current) drawCard(canvas.current, card, accent);
    });
  }, [card]);

  const save = () => {
    canvas.current?.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${card?.kind === "race" ? "race" : "lap"}-card-${(card?.driver ?? "driver").replace(/[^\w-]+/g, "_")}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    }, "image/png");
  };

  const shareText = !card ? ""
    : card.kind === "race"
      ? `I finished ${raceCardText(card).big} in a race at ${card.cafe.name} on ${card.track_name ?? "the track"}. Race me!`
      : `My best lap at ${card.cafe.name} on ${card.track_name ?? "the track"}: ${formatLapTime(card.best_ms)}. Beat it!`;
  const whatsapp = `https://wa.me/?text=${encodeURIComponent(`${shareText} ${location.href}`)}`;

  if (error) {
    return (
      <main className="cardpage">
        <h1 className="cardpage__title">Card not found</h1>
        <p className="t2">{error}</p>
      </main>
    );
  }
  return (
    <main className="cardpage">
      <canvas ref={canvas} className="cardpage__canvas" aria-label={card ? `${card.driver}'s ${card.kind === "race" ? "race" : "session"} card` : "Loading"} />
      {card && (
        <div className="cardpage__actions">
          <button type="button" className="cardpage__btn cardpage__btn--primary" onClick={save}>
            Save for Instagram story
          </button>
          <p className="cardpage__help">Then post it from your gallery to your Instagram story.</p>
          <a className="cardpage__btn cardpage__btn--whatsapp" href={whatsapp} target="_blank" rel="noopener">
            Share on WhatsApp
          </a>
          <p className="cardpage__note t3">
            Save the image to post it anywhere. The link works for phones on {card.cafe.name}'s Wi-Fi.
          </p>
        </div>
      )}
    </main>
  );
}
