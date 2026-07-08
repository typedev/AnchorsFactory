# AnchorsFactory Studio

A visual debugger for anchor rules. Studio opens a font, runs your rules
against it live, and shows **why** each anchor landed where it did — the
scanline it sampled, the ink stems it found, the centroid it measured — with a
click-through from every anchor back to the rule line that placed it.

It is a small local web app: a stdlib HTTP server on your machine serving a
single page. The font is opened once and kept in memory; rule text is sent from
the browser on every edit. **No font bytes ever leave the machine, and Studio
never writes anything into the font** — it is a read-only debugger. To actually
place anchors, use the `anchorsfactory` CLI.

## Launching

Studio ships with the package as the `anchorsfactory-studio` console script
(also runnable as `python -m anchorsfactory.studio`):

```bash
.venv/bin/anchorsfactory-studio MyFont.ufo                 # debug a font
.venv/bin/anchorsfactory-studio MyFont.ufo -r my-rules.af  # open with your rules
.venv/bin/anchorsfactory-studio                            # no font → built-in demo
```

Then open the printed URL (default `http://127.0.0.1:8765/`) in a browser.
`Ctrl-C` stops the server.

For development there is a one-command launcher that starts the server **and**
opens it in a Playwright-driven Chromium window (needs the dev browser —
`make browsers`); closing the window or `Ctrl-C` stops the server:

```bash
make studio                              # demo font
make studio ARGS="MyFont.ufo -r my.af"   # a UFO + your rules
# or directly: python scripts/studio_dev.py [ufo] [-r rules] [--port N] [--headless]
```

| option | meaning |
|--------|---------|
| `ufo` (positional, optional) | a `.ufo` to debug; omitted → a built-in synthetic demo font |
| `-r`, `--rules NAME_OR_PATH` | the rule text to open with: a bundled preset name (`default`, `default-italics`) or a path to a `.af` file (default: `default`) |
| `--host HOST` | bind address (default `127.0.0.1`) |
| `--port PORT` | port (default `8765`) |
| `-v`, `--verbose` | log requests to the terminal |

With no font argument Studio builds a small in-memory demo font (schematic
`H O A n o a e` plus `acute`/`dieresis` marks and an `aacute` composite for
`!propagate`) — deliberately crude shapes, but real outlines, so every overlay
kind has something to show. You can drop a real font onto the page at any time
(see below).

## The window

Left: the **rule editors** and an **Output** panel. Right: the **glyph grid** on
top and the **inspector** (big canvas + anchor readout) below. All panes are
resizable by dragging the dividers (double-click a divider to reset); sizes,
theme, and your rule edits persist in the browser's `localStorage`.

Everything recomputes live: edits are debounced (~300 ms), sent to the server,
and the grid, canvas, and readout update in place — anchors glide to their new
positions so you can see what a change moved.

### Rule layers: base + custom

Rules live in a two-layer stack, both visible and both editable:

- **base** — starts as a copy of a bundled preset (a dropdown switches which
  one; switching replaces the layer's text). It is a working copy: edit it
  freely, the bundled preset itself is untouched.
- **custom** — an optional layer *on top*. Effective rules are base first,
  custom after, under the normal accumulation model — so custom **overrides**
  (`=` replaces, `+=` adds, `-=` removes against whatever base built up).

The custom layer is closed by default: click **+ custom** to open it, **✕** to
close it and work with the base alone. Closing it is an instant "preset only"
view — toggle it to compare the preset's placement with your overrides.

Getting rules in and out:

- **open** loads a `.af` file into the custom layer; so does dropping a single
  `.af`/`.dsl`/`.txt` file anywhere on the page.
- **⤓ .af** on either layer downloads that layer's text as a file.
- `-r/--rules` on the command line seeds the base layer on first visit.

`!extends` works inside a layer, but only **bundled preset names** can be
inherited (`!extends default`) — Studio has no access to your file paths, so
`!extends ./other.af` is rejected with a clear error. To debug a rules file
that extends another file, open the base file in the base layer and the child
in the custom layer: the stack gives you the same merge.

### The editors

Both layers use the same editor: syntax highlighting for the rule language,
line numbers, and autocompletion — keywords (`outline`, `centroid`, …), font
metrics (`capHeight`, …), plus every `@label` and `&variable` defined anywhere
in your rules. Accept a completion with `Tab`/`Enter`, dismiss with `Esc`.

`Ctrl+F` (or `Cmd+F`) opens find-in-rules for the focused layer; `Enter` /
`Shift+Enter` step through matches, `Esc` closes.

Parse and validation errors appear in the **Output** panel under the editors
(a titled, resizable panel — drag its splitter) and mark the offending line in
red; clicking a problem jumps to that line in the right layer. Per-anchor
geometry notes (fallbacks, missing crossings, unresolved `%refs`) appear there
too, tagged `glyph·anchor`; when there is nothing to report it reads
`ok · no problems`. The status pill in the header sums it up: `ok`,
`ok · N notes`, or `N problems`.

### The glyph grid

Two tabs:

- **affected** — every glyph at least one rule matched, in glyph order, each
  thumbnail showing its outline, anchors, and anchor count. This is the default
  and answers "what did my rules place".
- **all glyphs** — every glyph in the font (affected ones keep their anchors), so
  you can spot glyphs your rules *miss*. A **hide affected** checkbox drops the
  ones already covered, leaving exactly the unaddressed glyphs. Thumbnails render
  lazily (drawn as they scroll into view), so even large fonts stay responsive.

The filter box narrows either tab by substring; the count reads `affected · N` /
`all · N` / `unaffected · N`. Click a thumbnail to inspect it — an unaffected
glyph shows its outline and metrics with no anchors. The active tab and checkbox
persist in `localStorage`.

### The inspector

The big canvas shows the selected glyph with the evidence behind each anchor:

- horizontal guides for the font metrics (baseline, x-height, cap-height,
  ascender, descender) and the glyph's bounding box;
- for each `outline`-positioned anchor, the **scanline** it sampled (a
  horizontal line at a height for X, a vertical line at a column for Y), the
  contour **crossings** found on it, and the paired **ink stems**;
- a crosshair at the **centroid** when an axis uses `outline.centroid`;
- the anchors themselves, labelled `name (x, y)`. A ⚠ ring means the anchor
  was placed by a fallback (e.g. no crossing at the sample height → bbox edge)
  — the reason is listed on its card and in the Output panel.

The readout beside the canvas lists each anchor's exact coordinates, the
strategy family used per axis (`x: outline · y: metric`, …), any warnings, and
its **provenance**: `→ base L12` names the layer and line of the rule that
placed it. Clicking the card highlights the anchor on the canvas and jumps the
editor to that rule line. (Anchors inherited from a preset via `!extends` have
no editor line to jump to.) Two badges flag non-rule origins: **propagated**
(`↳ inherited from <component>`) for an anchor a composite got via `!propagate`,
and **↦ %ref** for a `%name` derived anchor.

## Loading a font

Besides the command-line argument, you can load a font from the browser:

- **drop** a `.ufo` folder, or a `.zip`/`.ufoz` containing one, anywhere on
  the page;
- or click **load .ufoz** in the header to pick a `.ufoz`/`.zip` file.

The files are sent to the local server, reconstructed in a temporary directory,
and opened; the previous font (and its temp dir) is discarded. Your original
font on disk is never touched. The header shows the loaded font's family name,
UPM, and italic angle.

## Typical workflows

**Debug one rule.** Load your font, find the glyph in the grid, click it, then
click the suspicious anchor's card — the editor jumps to the rule that placed
it, and the canvas shows the scanline/stems it measured. Edit the rule and
watch the anchor move.

**Build overrides on a preset.** Keep `default` in the base layer, open the
custom layer, and write only the exceptions (`Q += …`, `germandbls = …`).
Close the custom layer to see the preset's own placement, reopen to see yours
win; when happy, **⤓ .af** the custom layer and add `!extends default` at the
top for use with the CLI.

**Port rules to a new font.** Drop the new font onto a Studio that already has
your rules — the rules survive the font swap, and the Output panel shows
exactly which glyphs and anchors degraded.

## Troubleshooting

- **`Address already in use` on start** — another Studio (or something else)
  holds the port. Pick another: `--port 8766`.
- **A dropped font is rejected** — the drop must contain a `.ufo` (a *folder*,
  or a `.zip`/`.ufoz` with one inside; a directory holding `metainfo.plist`
  also counts). The server's error appears in the Output panel, tagged
  `font`, and the status pill shows `font error`.
- **`-r`/preset seems ignored on relaunch** — the browser restores your last
  session's rule text from `localStorage`, which takes precedence over the
  command-line seed. Re-select the preset in the base layer's dropdown to get
  a fresh copy of it.
- **A glyph is missing from the grid** — the grid only lists glyphs some rule
  matched *and* that exist in the font. Check the selector (name, `U+…` range,
  glob, category) against the font's actual glyph names.
- **`!extends 'path'` fails** — only bundled preset names can be inherited in
  Studio; put the file's contents in a layer instead (see above).
