# AnchorsFactory

Rule-driven **anchor placement** for [UFO](https://unifiedfontobject.org/)
fonts. You describe, in a compact text file, where anchors should sit on your
glyphs; AnchorsFactory computes the coordinates from each glyph's own geometry
and writes the anchors into the font.

It does the *pre-marking* step of accent handling: place `top`/`bottom`/`_top`/…
anchors consistently across hundreds of glyphs, so a tool like
[GlyphConstruction](https://github.com/typemytype/GlyphConstruction) can then
assemble composite glyphs by snapping mark anchors to base anchors.

## Install

```bash
pip install anchorsfactory
# or, from a checkout:
pip install -e .
```

Requires Python 3.10+, `fontParts` and `fontTools`.

## Quick start

```bash
# place anchors using the bundled default ruleset, save to font_anchored.ufo
anchorsfactory MyFont.ufo --rules default

# your own rules, overwrite in place, with a backup of existing anchors
anchorsfactory MyFont.ufo --rules my-rules.af --in-place --backup-dir backups/

# a whole folder of UFOs
anchorsfactory masters/ --rules default
```

By default the source UFO is never overwritten — output goes to
`*_anchored.ufo` unless you pass `--in-place`.

## The rule language

Rules are stacked: define reusable **labels** (`@`, a list of anchors) and
**variables** (`&`, one axis's value), then **mark** glyphs with them, mixing
them with one-off anchors. An anchor is a name and a parenthesised `X Y`
placement.

```
# a variable (reuse one axis value) and a label (reuse a set of anchors)
&mid = capHeight*1/2+xHeight*1/2
@ = top (box.center capHeight), bottom (box.center 0)

# apply it, by name / unicode / range
A = @, ogonek (outline.right 0)
U+0410..U+044F = @            # all Russian Cyrillic
U+0413 += desc (outline.right 0)   # Г also gets a descender anchor
```

- **`frame.position`** works on **both axes**: `width.*` (advance), `box.*`
  (bounding box) or `outline.*` (the contour, sampled on a scanline at the other
  coordinate, with `.first`/`.last` to pick a stem). On X the words are
  `left/center/right`, on Y `bottom/middle/top`; `box*1/3` is a fractional
  position (same `*n/m` as `capHeight*2/3`) and `outline.centroid` the area
  centre of mass.
- **Y** may also be a number, a font metric (`capHeight`, `xHeight`, …), or a
  reference glyph (`$H`, `$H.bottom`, `$H*5/6`); `box.top` reads *this* glyph's
  own height.
- Selectors: name, `U+XXXX`, range `U+A..U+B`, glob `*.sc`, category `{Lu}`.
- `=` replace · `+=` add · `-=` remove; `!extends default` inherits a ruleset.
- Terms combine with `+`/`-` (on either axis) for a base position plus a bias —
  `outline.centroid-25` nudges a slanted mark off the optical centre.
- `&name` names a reusable X/Y value; `@name` a reusable set of anchors. Both
  are late-bound, so an extending file can override either.
- `%name` places an anchor relative to **another anchor** on the same glyph —
  `bottom (%top 0)` reuses `top`'s x so the two don't drift apart.
- `compN.`/`complast.` measure **one component's** outline (`comp1.outline.center@top`),
  for seating marks on ligature parts.
- `!propagate = composites` makes composite glyphs **inherit** their components'
  anchors — write rules for the base letters, precomposed glyphs get theirs free.

Full reference: **[docs/anchor-rules.md](docs/anchor-rules.md)**.

### Presets and migration

Bundled rulesets `default` and `default-italics` are usable by name in
`--rules` or `!extends`. Old `.txt` rule files (see `examples/`) convert to the
new syntax — verified lossless:

```bash
anchorsfactory-convert examples/default-anchors-list.txt -o my-rules.af
```

## Library API

```python
from anchorsfactory import process_ufo, load_document, apply_document

process_ufo("MyFont.ufo", "default")          # high-level: open, apply, save

from fontParts.world import OpenFont
font = OpenFont("MyFont.ufo")
apply_document(font, load_document("my-rules.af"))
font.save()
```

### Compute without mutating (preview)

`compute_document` is the functional core: it returns the anchors a rule
document *would* place, keyed by glyph, without touching the font. It owns the
same orchestration as `apply_document` (suffix expansion, `shift_x`, rounding,
same-name dedup), so a preview never drifts from what gets written.

```python
from anchorsfactory import compute_document, load_document, accumulate, resolve

doc = load_document("default")
placed = compute_document(font, doc)          # {glyph_name: [(anchor, x, y), ...]}

# resolve() is the pure, single-anchor primitive behind it:
specs = accumulate(doc, "A", font["A"].unicodes)   # the anchors due on glyph A
x, y = resolve(font, font["A"], specs[0])
```

For an interactive editor, `on_error="collect"` never raises — it places what
it can and reports the rest as structured diagnostics:

```python
result = compute_document(font, doc, on_error="collect")
for d in result.diagnostics:
    # d.severity == "error"   -> anchor skipped (geometry raised)
    # d.severity == "warning" -> anchor placed via a fallback, but suspect
    print(d.severity, d.glyph, d.anchor, d.reason)
```

`result` is a plain `dict` subclass (so it works anywhere a dict does) carrying
a `.diagnostics` list of `ComputeDiagnostic(glyph, anchor, reason, severity,
rule)`. The default `on_error="raise"` is unchanged and keeps `.diagnostics`
empty.

## Development

```bash
make venv      # create .venv, install the package (editable) + dev deps, via uv
make test      # run the test suite
make build     # build sdist + wheel into dist/
make release   # bump minor, update CHANGELOG, build, upload to PyPI, tag + push
```

Releases are cut with `make release`: it bumps the minor version, fills in a
[CHANGELOG](CHANGELOG.md) section from the commit log, publishes to PyPI, and
tags `vX.Y.Z`. Set `UV_PUBLISH_TOKEN` first; use `make release-test` to rehearse
against TestPyPI.

## License

MIT — see [LICENSE](LICENSE).
