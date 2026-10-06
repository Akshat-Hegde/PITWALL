import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow-condensed/500.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { chooseSource } from "./data/sources";
import { DashboardStore } from "./state/store";

const query = new URLSearchParams(location.search);
const { kind, source } = chooseSource(query, import.meta.env.DEV);
const store = new DashboardStore(kind);
source(store);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App store={store} />
  </StrictMode>,
);
