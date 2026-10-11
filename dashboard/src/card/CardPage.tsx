import { useEffect, useRef, useState } from "react";
import { formatLapTime } from "../format";
import type { StoryCard } from "../schema";
import { drawCard } from "./drawCard";
import { demoCard } from "./demo";

/** /card/<token>: the customer's session card. Draws the 1080 x 1920 image; save it or share it. */
export function CardPage({ token }: { token: string }) {
  const [card, setCard] = useState<StoryCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (token === "demo") {
      setCard(demoCard());
      return;
    }
    fetch(`/api/cards/${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `The hub answered ${r.status}.`);
        return r.json() as Promise<StoryCard>;
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
    document.title = `${card.driver}: ${formatLapTime(card.best_ms)}`;
    // Draw once the fonts are in, so the image uses Saira.
    Promise.all([
      document.fonts.load('900 100px "Saira Variable"'),
      document.fonts.load('600 30px "Saira Condensed"'),
    ]).catch(() => undefined).finally(() => drawCard(canvas.current!, card, accent));
  }, [card]);

  const save = () => {
    canvas.current?.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `lap-card-${(card?.driver ?? "driver").replace(/[^\w-]+/g, "_")}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    }, "image/png");
  };

  const shareText = card
    ? `My best lap at ${card.cafe.name} on ${card.track_name ?? "the track"}: ${formatLapTime(card.best_ms)}. Beat it!`
    : "";
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
      <canvas ref={canvas} className="cardpage__canvas" aria-label={card ? `${card.driver}'s session card` : "Loading"} />
      {card && (
        <div className="cardpage__actions">
          <button type="button" className="cardpage__btn cardpage__btn--primary" onClick={save}>Save image</button>
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
