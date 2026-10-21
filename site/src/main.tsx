import { StrictMode } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";
import "@fontsource/instrument-sans/latin-400.css";
import "@fontsource/instrument-sans/latin-500.css";
import "@fontsource/instrument-sans/latin-600.css";
import "@fontsource/instrument-serif/latin-400.css";
import "./styles/tokens.css";
import "./styles/site.css";
import App from "./App";

const root = document.getElementById("root")!;
const app = <StrictMode><App /></StrictMode>;
// Production HTML is prerendered (scripts/prerender.mjs): hydrate it.
// The dev server serves an empty root: render from scratch.
if (root.firstElementChild) hydrateRoot(root, app);
else createRoot(root).render(app);
