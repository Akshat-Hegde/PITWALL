import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** The TV is laid out on a fixed design canvas, scaled to fit the screen (letterboxed if the aspect differs). */
export const TV_W = 1920;
export const TV_H = 1080;

export function fitScale(width: number, height: number, w = TV_W, h = TV_H): number {
  if (width <= 0 || height <= 0) return 1;
  return Math.min(width / w, height / h);
}

const ScaleContext = createContext(1);

/** Canvas-to-screen scale (2 on a 4K TV): canvases size their backing store with it to stay sharp. */
export function useTvScale(): number {
  return useContext(ScaleContext);
}

export function TvStage({ children, width = TV_W, height = TV_H }: { children: ReactNode; width?: number; height?: number }) {
  const [scale, setScale] = useState(() => fitScale(window.innerWidth, window.innerHeight, width, height));
  useEffect(() => {
    const onResize = () => setScale(fitScale(window.innerWidth, window.innerHeight, width, height));
    window.addEventListener("resize", onResize);
    onResize();
    return () => window.removeEventListener("resize", onResize);
  }, [width, height]);
  return (
    <div className="tvstage">
      <div className="tvstage__canvas" style={{ width, height, transform: `translate(-50%, -50%) scale(${scale})` }}>
        <ScaleContext.Provider value={scale}>{children}</ScaleContext.Provider>
      </div>
    </div>
  );
}

/** Font scale that makes text of width `text` fit `box`; never below `min` (then the text is ellipsised). */
export function fitRatio(text: number, box: number, min = 0.6): number {
  if (box <= 0 || text <= box) return 1;
  return Math.max(min, Math.floor((box / text) * 100) / 100);
}

/** One line of text that shrinks its font to fit its box before it is ever truncated. */
export function FitText({ text, className = "", min = 0.6 }: { text: string; className?: string; min?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [box, setBox] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setBox(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.fontSize = "";
    const ratio = fitRatio(el.scrollWidth, el.clientWidth, min);
    if (ratio < 1) el.style.fontSize = `${parseFloat(getComputedStyle(el).fontSize) * ratio}px`;
  }, [text, box, min]);
  return <span ref={ref} className={`fit ${className}`}>{text}</span>;
}
