# Changelog

All notable changes to this project are documented in this file.
Curate entries under *Unreleased* as you work; `make release` promotes that
section to the new version (with today's date) and uses it as the release notes.

## [Unreleased]

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

