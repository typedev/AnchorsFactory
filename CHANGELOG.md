# Changelog

All notable changes to this project are documented in this file.
Curate entries under *Unreleased* as you work; `make release` promotes that
section to the new version (with today's date) and uses it as the release notes.

Changes to the **rule sets** in `examples/rules/` get their own
*Rule sets* section, separate from the engine's. They are data, not code, and
downstream copies them: a consumer needs to see "the content of `default`
changed" without inferring it from a version number.

## [Unreleased]

### Fixed

- **0.5.0's wheel shipped the Studio** despite `packages` excluding it. A stale
  `anchorsfactory.egg-info/` in the working tree — left by an editable install
  from when the Studio *was* a listed package — takes precedence over
  `pyproject.toml` for setuptools, so the release build put it back. `make build`
  was safe (it runs `clean` first); the release script cleared only `dist/`, and
  that is the path that published. It now clears `build/` and `*.egg-info` too,
  **and inspects the built wheel before uploading**: a rule set or a studio
  module in it aborts the release. The build config was already correct for
  0.5.0 and the artifact still came out wrong, so the artifact is what gets
  checked. Nothing else differs between 0.5.0 and 0.5.1.

## [0.5.0] - 2026-07-20

### Changed (breaking)

- **No rule sets ship with the package.** Rules are data, and bundling them was
  a mistake: `list_presets()` answered differently from a wheel than from a
  checkout, the default set sat in `site-packages` where a user could not edit
  it, and a change of *data* went out on a version of *code*. The library now
  carries the engine and a **resolver**; the host carries the rules. Every set
  (`default`, `default-italics`, `latin-ext-*`, `devanagari`, `hebrew`, `thai`,
  `legacy-*`) moved to `examples/rules/` in the repository — copy them.
  - `load_document(ref, base_dir=None, search_paths=None)` and
    `process_ufo(..., search_paths=None)` take the directories a **bare name**
    resolves in; `anchorsfactory.set_search_paths()` / `$ANCHORSFACTORY_RULES_PATH`
    set them process-wide; the CLI and Studio take `--rules-path` (repeatable).
    An explicit `search_paths=` replaces the process-wide list rather than
    extending it, so `[]` means "nowhere".
  - A name is tried in the **referencing file's own directory first**, so a set
    inherits its neighbour (`!extends default`) with no configuration at all.
  - `anchorsfactory.presets` keeps its function names but resolves off the search
    path, and each takes an optional `search_paths=`/`base_dir=`. New:
    `is_name()` (syntactic name-vs-path), `resolve()`, `search_paths()`,
    `set_search_paths()`, `add_search_path()`. `is_preset(name)` now means
    "resolves on the path", not "is bundled". An unresolvable name raises a
    `KeyError` naming every directory searched.
  - `resolve_ref(ref, base_dir=…, search_paths=…)` answers which file a
    reference loads from — the same decision `load_document` makes internally,
    so a host that lets a user *edit* an inherited set writes back to the file
    the engine actually read instead of re-deriving the search order.
  - `RuleSetNotFound` (a `KeyError` subclass) for a name nothing answers, kept
    distinct from `FileNotFoundError` (mistyped path) and `DSLError` (bad rule
    text): three different things to tell a user.
  - A rule inherited via a name now carries the base **file's path** as its
    `RuleSource.origin` (was `preset:<name>`) — the exact string `resolve_ref`
    returns, so the two compare directly. Documents are never cached, so a set
    edited mid-session is re-read on the next load.
  - `is_name()` treats any extension as a path, so a bare legacy `old.txt`
    reference still loads as a file.

- **The Studio no longer ships in the wheel.** It has no third-party dependency
  to gate an extra on (stdlib `http.server` + the fontTools/fontParts the core
  already needs), and an extra cannot exclude code from a distribution anyway.
  It stays in the repository as the library's reference consumer, importable
  from a checkout — `make studio`, or
  `python -m anchorsfactory.studio.server`. The `anchorsfactory-studio` console
  script is gone. `anchorsfactory.composites` and the vendored GlyphConstruction
  are **unaffected**: they are core, always installed.

### Added

- **`anchorsfactory.vocabulary`** — the rule language's surface words as public
  data, for editors that highlight, complete or diagnose it: `FRAMES`,
  `X_ALIGNS`, `Y_EDGES`, `RUNS`, `METRICS`, `CENTROID`, `DIRECTIVES`,
  `PROPAGATE_VALUES`, `SUFFIX_KEYWORDS`, `OPERATORS`, `SIGILS`, plus
  `completions_after_dot(head, axis)`, `completions_for_slot(axis)` and
  `as_dict()` (JSON-serialisable, for non-Python clients). The tables are derived
  from the IR enums and the **parser now reads them from here**, so the two
  cannot drift; the axis-aware functions carry knowledge a client would otherwise
  re-derive — `width` has no vertical form, a font metric opens a Y slot only,
  `outline` also takes runs and the centroid. Requested by a downstream editor.
  Note the module is deliberately not the IR: `Frame.ADVANCE` is a node name, the
  word a user types is `width`.

### Fixed

- **Studio completion offered tokens the parser rejects** — its dictionary was a
  hand-kept copy that had drifted: it listed `advance` (an IR name, never a DSL
  frame) and treated `advance.` as a valid frame, while `unitsPerEm` was missing
  from its metric list. It now builds every table from `anchorsfactory.vocabulary`,
  and knows which slot of `name ( X Y )` the caret is in — so after `box.` it
  offers three alignments instead of all six, and no longer suggests a font
  metric in the X slot.

- **`@`-edge offsets** — a signed offset after an own-edge sample line:
  `outline.center@top-10` samples 10 units below the bbox top (the fix for a
  scanline grazing a smooth peak), plus `@bottom+8` and, on Y, `@left-5` /
  `@right+5`. Glyph-relative (the italic projection follows the shifted line);
  bare `@top`/`@bottom` keep the exact-edge behaviour. (A metric/variable tail
  like `@xHeight-20` / `@capHeight*1/2+10` already worked.)

- **`%name` derived anchors** — a new polymorphic term giving the position of
  another anchor on the same glyph (its x in an X slot, its y in a Y slot), so an
  anchor can track another instead of being measured independently:
  `bottom (%top 0)` reuses `top`'s x. Composes in `+`/`-` sums (`%top-25`) and in
  an `@` sample line (`outline.center@%top`); resolved in dependency order (a
  reference cycle is rejected, a missing target degrades). Cannot appear in a
  `&variable`.
- **`!propagate` directive** — `none` (default) / `composites` / `all`: a
  composite glyph inherits its components' anchors (as computed in the same run,
  pushed through the component transform; falling back to a component's existing
  font anchors), seeding its accumulator before its own rules run. Mark-side
  (`_`-prefixed) anchors are never propagated; later components override earlier
  by name; composes through `!extends`.
- **`compN.` / `complast.` per-component frames** — a frame qualifier measuring
  only the N-th component's outline (`comp1.outline.center@top`,
  `comp2.box.right`, `complast.outline.centroid`), for seating marks on ligature
  parts. `width` takes no qualifier; too-few-components degrades to the whole
  glyph with a warning.
- **Studio: an Output panel** replacing the old unlabeled strip under the rules —
  a titled, resizable panel (with a splitter) that lists rule problems and
  per-anchor notes, with a "no problems" empty state. Invalid rules now surface
  there instead of 500-ing the compute endpoint. Inherited and derived anchors
  render `propagated` / `↦ %ref` provenance badges.
- **Playwright** added as a dev dependency for an end-to-end studio UI test
  (`make browsers` downloads the headless chromium; the test skips without it).

### Rule sets (`examples/rules/`)

Content changes, listed apart from the engine's because downstream copies these
files. All of them predate the move out of the package (they landed on master in
`59d7fd6`/`946c450`/`0f496d0`) and are collected here.

- **`default` is now generated from the Unicode database** and covers **Latin
  core only** — Basic Latin, Latin-1 Supplement, Latin Extended-A. Every
  composite comes from a canonical decomposition and every base carries exactly
  the anchors its composites ask for. **Cyrillic is gone from it**; the previous
  hand-maintained set (Latin + Cyrillic + foundry-specific component marks)
  is kept verbatim as `legacy-default.anchors`.
- **Glyphs are addressed by codepoint** (`U+00C1`) wherever a name would be a
  guess, so a set no longer assumes a naming scheme; ASCII letters stay spelled
  out. Marks are ruled three ways at once — combining codepoint, spacing twin,
  and the legacy names (`acutecomb`, plus the cap-height set `Acute` /
  `acute.case`).
- **`default.glyphsConstruction`** added — the pipeline's second half alongside
  the anchors, generated from the same decompositions.
- **`default-italics` is now an overlay**: `!extends default` plus the eight
  rules a slanted *drawing* changes (the shear itself is automatic since the
  `box.*` fix below). The previous 111-line standalone copy is kept as
  `legacy-default-italics.anchors`.
- **`latin-ext-b.*` and `latin-ext-additional.*`** added (Latin Extended-B; Latin
  Extended Additional — Vietnamese and the dot-below accents). Each covers its
  own block only and layers over `default`.
- **`devanagari`** derives `bottom2` from `bottom` with a `%bottom` reference
  (the stacking level tracks the base anchor); placement is identical (69% smoke
  accuracy unchanged), the intent is explicit.

The generated sets (`default`, `latin-ext-*`) come from a maintainer-side script
(`dev/gen_latin_rules.py`); do not hand-edit them, layer your own rules on top.

## [0.4.1] - 2026-06-24

### Added

- **`&variables`** — name a reusable X or Y axis expression once and reference
  it as `&name`, the per-axis sibling of a `@label`. Variables are composable
  (as a `+`-sum term, as an `@` sample height, or aliasing another variable),
  late-bound like labels (an `!extends` child can override one), and typed by
  axis — an X-in-Y misuse, an undefined variable, or a reference cycle is
  reported up front, before any glyph is touched.
- **Unified `frame.position` on both axes** — the X vocabulary now works on Y
  too (`box.top`/`box.middle`/`box.bottom`, `outline.*` sampled on a vertical
  scanline, `outline.N.center` for a bar of `E`/`Ё`), so an anchor can read its
  own glyph's geometry without naming it — `box.top` replaces the old need to
  write `$Glyph` for the current glyph. On Y an `outline` position's `@` is a
  column (`@left`/`@right` or a fixed X), the mirror of X's sample height.
- **`outline.centroid`** — the area centre of mass, a 2-D point (its x on X,
  its y on Y) for centring marks over a lopsided base, and on both axes for
  enclosing/overlay marks.
- **Fractional positions** — `box*2/3`, `width*1/3`: the `*n/m` operator (the
  same as `capHeight*2/3`) as a proportional position along a frame.
- **Arithmetic on positions** — terms combine with `+`/`-` on either axis, for
  summed heights (`ascender-descender`) and a bias off a base position
  (`outline.centroid-25`, to nudge a slanted acute/grave off the optical centre).

### Changed

- Bundled `default` / `default-italics` presets refactored for readability:
  repeated math extracted into `&variables`, cryptic labels renamed (`@` →
  `@baseUC`, `@xtop` → `@baseLC`, mark labels keyed by attach height), and
  never-referenced labels removed. Placement output is byte-for-byte unchanged.
- Documentation synced with the implementation: fixed an invalid selector-list
  example, documented the `$` sigil and one-letter `{L}` categories, and
  corrected the geometry description (samples at exactly the requested height,
  no inset).
- **Italic shear is now height-aware.** Every X is projected along the italic
  angle from the height it was *measured* at to the anchor's own height
  (`tan(-angle)·(Y - S)`): `outline.center@xHeight` placed higher now slides onto
  the stem at that height instead of landing left of it, while an anchor whose
  sample height equals its Y (e.g. an `H` top at cap-height) is unchanged.
  Previously `outline` positions got no shear and `box`/`width` sheared from the
  baseline only. Upright fonts are unaffected (angle 0 → no shift).
- The geometry engine resolves the two axes in dependency order: an `outline`
  position with no `@` samples on the other axis's resolved coordinate; both at
  once is rejected up front as an axis cycle (pin one with `@`). Internally
  `XAbs`/`YAbs` were unified into one axis-neutral `Abs`. Placement output for
  existing rules is byte-for-byte unchanged.

## [0.3.0] - 2026-06-09

### Added

- `!suffixes` now takes the same operators as rules — `=` sets the list,
  `+=` adds, `-=` removes — and they **compose through `!extends`** (a child can
  narrow or reset an inherited list, not just extend it; `= none` resets to base
  glyphs only). Previously `!extends` could only union suffix lists.
- `!suffixes = all` — discover suffixes from the font: every `base.<suffix>`
  glyph is treated as a variant of `base`, so rules apply to all suffixed glyphs
  without listing each suffix. `!suffixes = all except .numr, .dnom` excludes
  suffixes that need different anchors; in `all` mode `-=`/`+=` adjust that
  exclusion set.
- Comma-separated selector lists on a rule's left-hand side —
  `C, O, S += top (...), bottom (...)` applies the same right-hand side to each
  listed selector (one rule per entry). Entries may mix selector kinds
  (`A, U+0421, *.sc = @round`). An empty entry (blank or trailing comma) is
  ignored; a wholly empty left-hand side is now a parse error.
- `compute_document(..., names=<iterable>)` / `apply_document(..., names=...)`
  — restrict computation (and the write) to a subset of **target (suffixed)**
  glyph names; `None` (default) keeps the whole-font behaviour, an empty
  iterable computes nothing. With `clear=True`, non-selected glyphs are left
  untouched — the "apply only to the selected glyphs" path an interactive
  editor needs. Also skips `resolve` for non-selected glyphs (a perf win).
- `compute_document(font, doc)` — a compute-only entry point that returns the
  anchors a rule document would place (`{glyph: [(name, x, y), ...]}`) without
  mutating the font, for previewing placement before applying. `apply_document`
  is now a thin write step on top, so a preview can't drift from what gets
  written. It owns suffix expansion, `shift_x`, rounding, and same-name dedup.
- Error-collection mode: `compute_document(..., on_error="collect")` never
  raises — it places what it can and returns structured `ComputeDiagnostic`s
  on the result's `.diagnostics`. Hard geometry failures are `severity="error"`
  (anchor skipped); soft degradations (no outline crossing, missing metric or
  reference glyph) are `severity="warning"` with the anchor still placed.
- `resolve` (the pure single-anchor primitive) and `compute_document`,
  `ComputeResult`, `ComputeDiagnostic` are now exported from the top-level
  package.
- `resolve(..., warnings=<list>)` — an optional sink that collects soft
  geometry degradations as reason strings; the coordinate is still returned.
  Without it, behaviour (and logging) is unchanged.
- `outline.*@<height>` with a sample height that finds no crossing (outside the
  glyph's ink box, e.g. `@ascender` on an x-height glyph, or a flat collinear
  edge) falls back to the bounding-box edge **and** records a `severity="warning"`
  degradation, so the request is surfaced rather than silently masked.

### Changed

- `outline.*@<height>` now samples the contour at **exactly** the requested
  height — the ±1u edge inset is gone. A height that coincides with the glyph's
  own extreme (e.g. `outline.right@0` where `0` is the top of an open hook) is
  honoured: its clean crossings are no longer discarded. **Behaviour change:**
  at a smooth round top, `@top`/`@bottom` with `left`/`right` now returns the
  tangent point at the extreme rather than the slightly wider envelope a unit
  inside (e.g. a round `O`'s right edge shifts in by ~1–2% of its width).

### Fixed

- `outline.<align>@<y>` no longer overshoots by ~slope×1u at horizontal extremes
  (#8). The old code insets every scanline landing on an extreme, which on a
  sloped open edge moved the anchor 1–2u sideways and propagated into composite
  placement; the exact-height crossing is now used when it is clean.

## [0.2.0] - 2026-06-04

First public release on PyPI.

- Rule-driven anchor placement for UFO fonts: anchors computed from each
  glyph's own geometry (advance, bounding box, or analytic contour
  intersection) and written into the font.
- A compact rule language (labels, selectors by name/Unicode/range/glob/
  category, `=`/`+=`/`-=` operators, `!extends` inheritance).
- Analytic geometry engine: stem pairing, italic shift, fixed-height sampling,
  font-metric and reference-glyph heights.
- CLI `anchorsfactory` with safe-save (`*_anchored.ufo`) and `--in-place`,
  plus `anchorsfactory-convert` for legacy `.txt` rules.
- Bundled `default` and `default-italics` presets.

