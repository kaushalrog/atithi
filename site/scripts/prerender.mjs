// Render the React page to HTML at build time and inject it into dist/index.html.
// The browser then hydrates it, so the page is readable before (and without) JS.
import { readFileSync, writeFileSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { render } = await import(join(root, "dist-ssr", "entry-server.js"));
const file = join(root, "dist", "index.html");
const template = readFileSync(file, "utf8");
if (!template.includes("<!--app-html-->")) throw new Error("placeholder missing in index.html");
writeFileSync(file, template.replace("<!--app-html-->", render()));
rmSync(join(root, "dist-ssr"), { recursive: true, force: true });
console.log("prerendered dist/index.html");
