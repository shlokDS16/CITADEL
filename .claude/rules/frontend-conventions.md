# Rule: Frontend Conventions

> Applies to: `CITADEL.html`, `components.jsx`, `pages.jsx`, `styles.css`, `tweaks-panel.jsx`.

## Architecture
- **Standalone React 18.3** loaded from CDN. Babel compiles JSX in-browser. **No bundler.**
- File load order in `CITADEL.html`: `components.jsx` → `pages.jsx` → `tweaks-panel.jsx`.
- Components, hooks, and helpers attach to `window` via `Object.assign(window, { ... })` at the bottom of each file.
- React state is local to App + components. No external store (Redux/Zustand) — keep it lean.

## File responsibilities
- `components.jsx` — reusable primitives (≤ 100 LOC each ideally). Cross-module visual elements live here.
- `pages.jsx` — module-level pages (one component per module: `DocumentIntelligence`, `ResumeScreening`, etc.).
- `styles.css` — single neo-brutalist stylesheet. Add new sections at the bottom with a clear `/* === SECTION === */` header.
- `CITADEL.html` — App shell, routing, role/login state. Keep this thin.
- `tweaks-panel.jsx` — runtime theme tweaks (don't touch unless the user asks for theme changes).

## Visual language (non-negotiable)
- Borders: `3px solid #000` (or 2px for dense grids)
- Shadows: hard offset, no blur — e.g. `box-shadow: 6px 6px 0 var(--gold)`
- Border radius: **0**. Never round corners.
- Palette: `--gold #D4A843`, `--red #E63946`, `--cyan #5BC0EB`, `--green #2EC04A`, `--bg #F2F0EB`
- Fonts: `Chakra Petch` (display, headers), `JetBrains Mono` (body, data), `Space Mono` (terminal)
- Icons: SVG only (Heroicons / Lucide / inline). **No emoji as icons.** (Existing emoji decorations are grandfathered.)

## Mock-first data flow
- All module data is **mocked** inside `pages.jsx` until backend contracts are signed off.
- When wiring a real backend, gate it behind a per-module flag — e.g. `const useLive = new URLSearchParams(location.search).get('live') === '1';`
- Mock generators should produce shapes that exactly match the backend spec in `docs/module-specs/<module>.md`.

## Accessibility (must-have)
- Keep contrast ≥ 4.5:1 on body text (we already meet this — don't break it).
- Touch targets ≥ 44×44px on tabs, buttons, pills.
- `:focus-visible { outline: 3px solid var(--cyan); outline-offset: 2px; }` is global — don't remove.
- Respect `prefers-reduced-motion` (already wired — disables tickers, scan lines, pulses).
- Every icon-only button gets a `title` (and ideally `aria-label`).

## Adding a new component
1. Decide: primitive (reusable) → `components.jsx`. Module-specific → `pages.jsx`.
2. Match an existing similar component for prop shape and CSS class names.
3. Add the CSS at the bottom of `styles.css` under a new `/* === COMPONENT NAME === */` section.
4. Append to the `Object.assign(window, { ... })` block.
5. Smoke-test by reloading `http://127.0.0.1:8080/CITADEL.html`.

## Anti-patterns
- ❌ Introducing TypeScript, Vite, Webpack, or any build step.
- ❌ Inline styles for anything reusable — put it in `styles.css`.
- ❌ `import` / `export` syntax — won't work without a bundler.
- ❌ Soft shadows (`0 4px 12px rgba(...)`), rounded corners, gradients.
- ❌ Mixing icon styles (emoji + SVG) within the same module.
