# Changelog

All notable changes to this project are documented in this file.
Sections below the *Unreleased* heading are filled in automatically by
`make release` from the commit messages of each release.

## [Unreleased]

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

