import { useEffect, useRef, useState } from "react";
import { formatLapTime } from "../format";
import type { AnyStoryCard } from "../schema";
import { drawCard, raceCardText } from "./drawCard";
import { demoCard, demoRaceCard } from "./demo";
import { cardFileName, isThisIOS } from "./save";

/** /card/<token>: the customer's session or race card. Draws the 1080 x 1920 image (an Instagram story's size);
 *  save it, then post it from the gallery. No Web Share of files: the LAN page is plain HTTP. On iPhone and iPad
 *  Safari ignores the download, so the image is shown full-screen to press and hold ("Save to Photos"). */
export function CardPage({ token }: { token: string }) {
  const [card, setCard] = useState<AnyStoryCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);   // iOS: the card image to press and hold
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (token === "demo" || token === "demo-race") {
      setCard(token === "demo" ? demoCard() : demoRaceCard());
      return;
    }
    fetch(`/api/cards/${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? "This card couldn't be loaded. Check your phone is on the cafe's Wi-Fi, then try again.");
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
    const c = canvas.current;
    if (!c) return;
    if (isThisIOS()) {
      try {
        const url = c.toDataURL("image/png");
        if (url && url.startsWith("data:image/png")) setPreview(url);
      } catch {
        /* the canvas can't be read: nothing to show */
      }
      return;
    }
    c.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = cardFileName(card?.kind, card?.driver);
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
      {preview && (
        <div className="cardpage__preview" role="dialog" aria-modal="true" aria-label="Save your card">
          <img className="cardpage__preview-img" src={preview} alt={card ? `${card.driver}'s card` : "Your card"} />
          <p className="cardpage__preview-help">Press and hold the picture, then tap Save to Photos</p>
          <button type="button" className="cardpage__btn" onClick={() => setPreview(null)}>Done</button>
        </div>
      )}
    </main>
  );
}
