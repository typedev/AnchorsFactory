# Changelog

All notable changes to this project are documented in this file.
Sections below the *Unreleased* heading are filled in automatically by
`make release` from the commit messages of each release.

## [Unreleased]

### Added

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
- `outline.*@<height>` with a sample height outside the glyph's ink box (e.g.
  `@ascender` on an x-height glyph) is still clamped to the nearest edge — but
  now records a `severity="warning"` degradation instead of masking it, so the
  request "sample where there is no outline" is surfaced rather than silent.

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

