import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Static site: the client bundle goes to dist/, a server bundle to dist-ssr/,
// and scripts/prerender.mjs renders the page into dist/index.html so the
// content is in the HTML (fast first paint, readable without JavaScript).
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { target: "es2020", assetsInlineLimit: 0 },
});
