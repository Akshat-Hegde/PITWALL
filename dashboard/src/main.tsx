// Self-hosted (DESIGN.md, SIL OFL): Saira variable (weight and width axes) and Saira Condensed for labels.
import "@fontsource-variable/saira/wdth.css";
import "@fontsource/saira-condensed/latin-500.css";
import "@fontsource/saira-condensed/latin-600.css";
import "@fontsource/saira-condensed/latin-700.css";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { CardPage } from "./card/CardPage";
import { chooseSource } from "./data/sources";
import { displayFromQuery } from "./map/geometry";
import { DashboardStore } from "./state/store";
import { viewModeFromQuery } from "./views";

const query = new URLSearchParams(location.search);
const cardPath = /^\/card\/([\w-]+)/.exec(location.pathname);
if (cardPath) {
  // The customer's story card: no live feed needed.
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <CardPage token={cardPath[1]!} />
    </StrictMode>,
  );
} else {
  const { kind, source } = chooseSource(query, import.meta.env.DEV);
  const store = new DashboardStore(kind);
  source(store);

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App store={store} mapDisplay={displayFromQuery(query)} viewMode={viewModeFromQuery(query)}
           demo={query.get("demo") === "1"}
           layout={location.pathname.startsWith("/portrait") || query.get("layout") === "portrait" ? "portrait" : "tv"} />
    </StrictMode>,
  );
}
