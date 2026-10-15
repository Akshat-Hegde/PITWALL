// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import { CardPage } from "./CardPage";
import { cardFileName, isIOS } from "./save";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const IPADOS = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36";
const WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36";

afterEach(() => vi.restoreAllMocks());

test("iOS: iPhone, iPad and iPadOS's desktop user agent with touch; not a Mac, Android or Windows", () => {
  expect(isIOS(IPHONE, "iPhone", 5)).toBe(true);
  expect(isIOS("Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X)", "iPad", 5)).toBe(true);
  expect(isIOS(IPADOS, "MacIntel", 5)).toBe(true);
  expect(isIOS(IPADOS, "MacIntel", 0)).toBe(false);       // a real Mac: no touch screen
  expect(isIOS(ANDROID, "Linux armv8l", 5)).toBe(false);
  expect(isIOS(WINDOWS, "Win32", 0)).toBe(false);
});

test("card file name: the driver's name, or plain lap-card.png for a name with no Latin letters", () => {
  expect(cardFileName("session", "Alex")).toBe("lap-card-Alex.png");
  expect(cardFileName("race", "Maya R")).toBe("race-card-Maya_R.png");
  expect(cardFileName("session", "अर्जुन")).toBe("lap-card.png");
  expect(cardFileName("session", "李明")).toBe("lap-card.png");
  expect(cardFileName("race", "王")).toBe("race-card.png");
  expect(cardFileName("session", "")).toBe("lap-card.png");
  expect(cardFileName("session", null)).toBe("lap-card.png");
});

async function renderCard(ua: string, platform: string, touch: number) {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(ua);
  vi.spyOn(navigator, "platform", "get").mockReturnValue(platform);
  Object.defineProperty(navigator, "maxTouchPoints", { configurable: true, get: () => touch });   // not in jsdom
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  await act(async () => root.render(<CardPage token="demo" />));
  return { el, root };
}

test("on an iPhone, Save shows the card full-screen to press and hold, and Done closes it", async () => {
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/png;base64,AAAA");
  const toBlob = vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(() => undefined);
  const { el, root } = await renderCard(IPHONE, "iPhone", 5);
  await act(async () => (el.querySelector(".cardpage__btn--primary") as HTMLButtonElement).click());
  const img = el.querySelector(".cardpage__preview img") as HTMLImageElement;
  expect(img.getAttribute("src")).toBe("data:image/png;base64,AAAA");
  expect(el.textContent).toContain("Press and hold the picture, then tap Save to Photos");
  expect(toBlob).not.toHaveBeenCalled();                    // no download on iOS
  const done = [...el.querySelectorAll(".cardpage__preview button")].find((b) => b.textContent === "Done") as HTMLButtonElement;
  await act(async () => done.click());
  expect(el.querySelector(".cardpage__preview")).toBeNull();
  await act(async () => root.unmount());
  el.remove();
});

test("on Android the card downloads as a file (no full-screen picture)", async () => {
  const blob = new Blob(["x"], { type: "image/png" });
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((cb: BlobCallback) => cb(blob));
  (URL as unknown as { createObjectURL: (b: Blob) => string }).createObjectURL = () => "blob:card";
  (URL as unknown as { revokeObjectURL: (u: string) => void }).revokeObjectURL = () => undefined;
  const clicks: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicks.push(this.download);
  });
  const { el, root } = await renderCard(ANDROID, "Linux armv8l", 5);
  await act(async () => (el.querySelector(".cardpage__btn--primary") as HTMLButtonElement).click());
  expect(clicks).toHaveLength(1);
  expect(clicks[0]).toMatch(/^lap-card(-[\w-]+)?\.png$/);
  expect(el.querySelector(".cardpage__preview")).toBeNull();
  await act(async () => root.unmount());
  el.remove();
});
