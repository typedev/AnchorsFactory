# Studio as a static web app (Pyodide)

**Goal.** Turn the Studio into a site that anyone can open. The Python engine
runs **in the browser** (Pyodide, in a Web Worker), so fonts never leave the
tab and there is no server to run or secure. Proprietary fonts can be used on a
public site because nothing is uploaded. The local `anchorsfactory-studio`
server stays as the development mode and uses the same frontend.

The design follows `groups-control-web`, which already works this way: Pyodide
in a worker, typed RPC, UFO/designspace folders read in the browser, saving
back into the folder, and deployment to GitHub Pages.

## What we know already (2026-10-11)

- **Dependencies resolve.** Pyodide **314.0.7** (Python 3.14.2) ships
  `fonttools` 4.62.1, `lxml`, `pyclipper` 1.4.0 and `brotli`. The rest of the
  fontParts chain is pure Python (`defcon`, `fontMath`, `fontPens`,
  `booleanOperations`, `fontParts`, `anchorsfactory`).
- **One snag.** `fontParts`/`defcon` require `fontTools[unicode]`, which pulls
  `unicodedata2`. Pyodide has no build of it, and PyPI has only C wheels.
  Install with `micropip.install(..., deps=False)` and an explicit package
  list. fontTools falls back to the stdlib `unicodedata`.
- **The Studio backend is ready to move.** `render.py` / `compose.py` are pure
  functions returning JSON, and `server.py` is a thin wrapper over 6 endpoints
  (`state`, `compute`, `allglyphs`, `font`, `font/activate|remove|context`,
  `masters`). They can be called from a worker unchanged.
- **The Studio is not in the wheel.** Its sources must reach the worker
  separately: `groups-control-web` bundles them as text and writes them into
  MEMFS.

## Phase 0: spike: DONE, go (2026-10-11)

`web/spike/` (`index.html` + `worker.js`, no build step) loads Pyodide 314.0.7
in a **module** worker. A classic worker's `importScripts(pyodide.js)` fails;
use `import(".../pyodide.mjs")` as `groups-control-web` does. The page then
installs `fonttools lxml pyclipper micropip` from Pyodide and the pure wheels
plus `anchorsfactory==0.6.0` with `deps=False`, writes the Studio sources into
site-packages, and runs `build_view`, `build_composite_view` and
`masters_report` **unchanged**.

| | CPython 3.12 | Pyodide (Chromium) |
|---|---|---|
| start: Pyodide / packages / sources | – | 1.2 s / 2.5 s / 0.9 s (cold, no cache) |
| demo font: view / composites | – | 13 ms / 120 ms |
| real font (3060 glyphs): open | 9 ms | 224 ms |
| real font: `build_view` warm / cold | 1.0 s / 2.1 s | 2.2 s / 4.1 s |
| real font: `build_composite_view` | 3.7 s | 7.4 s |
| real font: `masters_report` (2 masters) | – | 12 s |

The results are identical (3503 anchors, 161 composites). Conditional blocks,
dimming and the masters report all work. **Pyodide is about 2× slower than
CPython**, and on a big font the Studio is already too slow for per-keystroke
compute **in CPython**.

## Phase 0.5: speed: DONE (2026-10-11)

Results on the same real font, with `speedups.enable()` and a warm path cache:

| | before (CPython / Pyodide) | after (CPython / Pyodide) |
|---|---|---|
| `build_view` (per keystroke) | 1.0 s / 2.2 s | **0.25 s / 0.57 s** |
| `build_composite_view` | 3.7 s / 7.4 s | **0.25 s / 0.55 s** |
| `masters_report` (2 masters) | – / 12 s | – / 1.4 s |

The payloads are identical with and without the speedups (apart from the
order of `uncovered`, now fixed to glyph order). The composites match the old
copy-and-apply path exactly on all 161 composites, and golden is unchanged
(1743/1743, 0 moved). The first view of a font still draws every outline
(2.8 s in Pyodide); do that while the font loads.

The original analysis:

The profile (CPython, real font) puts the cost in fontParts overhead, not in
our geometry:

1. **`name in font` is O(n) in fontParts.** `layer._contains` rebuilds the key
   list on every call, and there are about 20k calls per view: ~1.3 of 3 s.
   Build the name set once per compute (in the engine's `compute_document` /
   `explain_document` and in the Studio's `build_view`).
2. **`font.copy()` for composites:** 5.2 of 9.5 s, plus 2.3 s of
   `apply_document`. Instead, build composites against a light glyphset proxy
   over the original font that serves the computed anchors. Use
   `compute_document` only, and only for the glyphs the constructions use.
3. `glyph_to_svg_path` draws components through fontParts (~1 s). Cache paths
   per glyph and invalidate them when the font changes, not per keystroke.
4. If it is still slow, compute the selected and visible glyphs per keystroke
   and the rest in the background.

Target: real font `build_view` ≤ 0.3 s in CPython (≤ 0.7 s in Pyodide).
Composites ≤ 1 s. Golden must stay identical.

## Phase 1: one API, two transports: DONE (2026-10-11)

Done as planned, with three simplifications:

- **One frontend, not a port.** The page stays in `anchorsfactory/studio/static/`
  as plain JS and the local server keeps serving it unbuilt (no Node for the
  local Studio). `web/` is a Vite + TS project that imports `app.js`/`app.css`
  as they are, takes the markup from `static/index.html` through a small Vite
  plugin, and supplies only the worker transport (`web/src/transport.ts`) and
  the worker (`web/src/worker/python.worker.ts`).
- **`Studio.dispatch(method, body)`** in `studio/api.py` is the whole API; the
  HTTP routes and the worker calls are the same method names. The worker adds
  `open_font_tree(root, warm=True)` for dropped files, which it writes into
  MEMFS itself (no base64), and draws all outlines during the load.
- **The engine comes from the checkout**, not the PyPI wheel: the site is built
  from a release tag, so it is the same code, and `web/` stays usable on
  unreleased changes. Only the five pure dependencies are pinned wheels
  (`web/wheels.txt`, fetched sha256-checked by `scripts/fetch_web_wheels.py`).

Measured in Chromium against the production build (cold browser cache):
start + first view of the demo 2.5 s; a 3060-glyph UFO load 4.3 s with every
outline drawn; an edit to the rules → updated view and composites about 1.2 s
(0.3 s of it the editor's debounce). Results match the local Studio
(161 composites).

The original plan:

- Extract `anchorsfactory/studio/api.py`, a facade with one function per
  endpoint that returns JSON-ready dicts. `server.py` becomes an HTTP adapter
  over it. The worker calls the same functions. Tests stay plain pytest.
- In `app.js`, replace direct `fetch("/api/…")` calls with an `api` object that
  has two backends: HTTP (local server) and Worker (Pyodide). The backend is
  chosen at startup.
- Python errors cross the worker as messages (last traceback line only, as in
  `groups-control-web`).

## Phase 2: fonts and files in the browser

- **Open:** a `.ufo` folder, `.ufoz`/zip, or a folder with a `.designspace`.
  Port `files.ts` from `groups-control-web`: `webkitGetAsEntry` /
  `showDirectoryPicker`, `normalizeRelative` against `..`, and read only the
  UFOs the designspace references. Files go into MEMFS. Masters and their
  `!if` contexts come from `contexts_from_designspace` (already in 0.6.0).
- **Rules:** open and save `.anchors` / `.glyphsConstruction` with file pickers
  (localStorage already keeps the session).
- **Save anchors back (after v1, which is preview only):** `apply_document` on the font, then write **only the
  changed `.glif` files**. On Chromium they go into the original folder (File
  System Access); elsewhere a zip of the changed files is downloaded. The diffs
  must stay minimal. Check what defcon/ufoLib rewrite, or port
  `groups-control-web`'s glif patching.
- Later: IndexedDB session autosave with a "changed on disk" warning.

## Phase 3: deploy

Done in Phase 1 in a simpler form: `.github/workflows/pages.yml` builds `web/`
on each release tag (or by hand) and deploys it to GitHub Pages; `ci.yml`
type-checks and bundles `web/` on every push. No service worker yet. The plan
was:

- `scripts/build_web.py` builds `web/dist/` from the static files, the Studio
  sources and pinned wheels in `web/wheels/` with a manifest, so nothing is
  fetched from PyPI at runtime. Python only, no Node toolchain.
- `.github/workflows/pages.yml` builds and deploys to GitHub Pages on each
  release tag. The site pins the **released** `anchorsfactory` wheel, so the web
  Studio always matches a PyPI version.
- Optional: a service worker for offline use (cache keyed by the Pyodide
  version), plus a CSP.

## Decisions (2026-10-11)

1. **Hosting:** GitHub Pages under `typedev.github.io`. The project page is
   `https://typedev.github.io/AnchorsFactory/`, so the build needs the base
   path `/AnchorsFactory/`.
2. **Frontend:** **Vite + TypeScript without React**. The existing DOM
   code moves over almost as is, the `groups-control-web` TS modules (folder
   and designspace reading, worker protocol) are reused, and CodeMirror 6 can
   replace the textarea editor. React only if the UI grows. **Confirmed.**
3. **Rule library:** the sample sets from `examples/rules/` are offered on the
   site (the spike already loads them from an index).
4. **First public version: preview only.** No writing back into the UFO. Rules
   and constructions can be downloaded. Saving anchors into the font is a later
   phase.
