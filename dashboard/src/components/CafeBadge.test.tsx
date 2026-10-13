// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test } from "vitest";
import { CafeBadge } from "./Pitwall";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

test("badge shows the logo, falls back to the initial when it fails, and retries on a new URL", async () => {
  const el = document.createElement("div");
  const root = createRoot(el);
  await act(async () => root.render(<CafeBadge logo="/api/cafe/logo?v=a.png" initial="L" />));
  const img = el.querySelector("img");
  expect(img?.getAttribute("src")).toBe("/api/cafe/logo?v=a.png");
  await act(async () => { img?.dispatchEvent(new Event("error")); });
  expect(el.querySelector("img")).toBeNull();
  expect(el.textContent).toBe("L");
  await act(async () => root.render(<CafeBadge logo="/api/cafe/logo?v=b.png" initial="L" />));
  expect(el.querySelector("img")?.getAttribute("src")).toBe("/api/cafe/logo?v=b.png");
  await act(async () => root.render(<CafeBadge logo={null} initial="L" />));
  expect(el.textContent).toBe("L");
});
