// Self-hosted (DESIGN.md, SIL OFL): Saira variable (weight and width axes) and Saira Condensed for labels.
import "@fontsource-variable/saira/wdth.css";
import "@fontsource/saira-condensed/latin-500.css";
import "@fontsource/saira-condensed/latin-600.css";
import "@fontsource/saira-condensed/latin-700.css";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { chooseSource } from "./data/sources";
import { displayFromQuery } from "./map/geometry";
import { DashboardStore } from "./state/store";
import { viewModeFromQuery } from "./views";

const query = new URLSearchParams(location.search);
const { kind, source } = chooseSource(query, import.meta.env.DEV);
const store = new DashboardStore(kind);
source(store);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App store={store} mapDisplay={displayFromQuery(query)} viewMode={viewModeFromQuery(query)} />
  </StrictMode>,
);
