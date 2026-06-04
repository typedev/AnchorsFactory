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

Rules are stacked: define reusable **labels**, then **mark** glyphs with them,
mixing labels and one-off anchors. An anchor is a name and a parenthesised
`X Y` placement.

```
# a label
@ = top (box.center capHeight), bottom (box.center 0)

# apply it, by name / unicode / range
A = @, ogonek (outline.right 0)
U+0410..U+044F = @            # all Russian Cyrillic
U+0413 += desc (outline.right 0)   # Г also gets a descender anchor
```

- **X** is `frame.position`: `width.*` (advance), `box.*` (bounding box) or
  `outline.*` (the contour at height Y, with `.first`/`.last` to pick a stem).
- **Y** is a number, a font metric (`capHeight`, `xHeight`, `ascender`, …), or a
  reference glyph (`$H`, `$H.bottom`, `$H*5/6`).
- Selectors: name, `U+XXXX`, range `U+A..U+B`, glob `*.sc`, category `{Lu}`.
- `=` replace · `+=` add · `-=` remove; `!extends default` inherits a ruleset.

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
