# Atithi marketing site

The public website for Atithi. It is **separate from the owner portal** in `../web/`, which it does not touch.

The stack is Vite + React + TypeScript, with Motion for React used only for state changes in the sample booking. The site is static: at build time the page is prerendered into `dist/index.html`, so it is readable before (and without) JavaScript. It needs no backend.

## Run it

```bash
npm ci            # once (Node 20+)
npm run dev       # http://localhost:5173, live reload
npm run build     # dist/: client bundle + prerendered HTML
npm run preview   # serves dist/ on http://localhost:4173
npm run typecheck
```

## Deploy

Upload `dist/` to any static host. Free options:

- **Cloudflare Pages:** build command `npm run build`, output directory `dist`, root directory `site`.
- **Netlify:** the same three settings.
- **GitHub Pages:** push `dist/` to a `gh-pages` branch. Paths are relative (`base: "./"`), so a sub-path works.

Nothing has been deployed yet.

## Where things are

| Path | What |
|---|---|
| `src/components/` | Page sections. `Signal.tsx` is the Welcome Signal; `SampleBooking.tsx` is the scripted demo |
| `src/data/scenarios.ts` | The three sample conversations. Only behaviour the product really has |
| `src/styles/tokens.css` | Every colour, size and timing |
| `public/product/` | Genuine portal screens (WebP), cropped from the 2026-10-20 walkthrough |
| `public/media/` | The walkthrough video. It is fetched only when the visitor presses play |
| `docs/PRODUCT_TRUTH.md` | **What the site may claim**, with evidence. Check it before changing copy |
| `docs/REFERENCE_RESEARCH.md`, `docs/DESIGN_DECISION.md` | Research and why this direction was chosen |
| `prototypes/` | The three competing hero directions (static HTML) |
| `qa/shots.py`, `qa/interact.py` | Browser QA (Python Playwright + installed Chrome). `shots.py` fails on horizontal overflow or console errors |

## QA

```bash
python qa/shots.py http://localhost:4173 qa/raw/<name>      # 1440/1280/768/390/320, reduced motion, no JS
python qa/interact.py http://localhost:4173 qa/raw/<name>   # keyboard, menu, sample failure path, video, no JS
```

`qa/raw/` is gitignored, and screenshots from it are never committed.
