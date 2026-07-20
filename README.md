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
# place anchors using a rule set, save to font_anchored.ufo
# (none ship with the package — start from a copy of examples/rules/default.anchors)
anchorsfactory MyFont.ufo --rules my-rules.anchors

# overwrite in place, with a backup of existing anchors
anchorsfactory MyFont.ufo --rules my-rules.anchors --in-place --backup-dir backups/

# a whole folder of UFOs, addressing the set by name off a rule library
anchorsfactory masters/ --rules-path my-rules --rules default
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
- `@top-10` / `@bottom+8` sample just inside an edge (the fix for a scanline
  grazing a smooth peak); `@xHeight-20` and other metric/variable insets too.

Full reference: **[docs/anchor-rules.md](docs/anchor-rules.md)**.

### Rule sets: the host carries them

**No rule sets ship with the package.** Rules are data, not code: bundled, they
sat where a user could not edit them, and a change of data went out on a version
of code. The library carries the engine and a resolver; you carry the rules.

The sample sets live in this repository under [`examples/rules/`](examples/rules/) —
copy them and make them yours. Address one by path, or by bare name once a
search path is configured:

```bash
anchorsfactory MyFont.ufo -r path/to/default.anchors           # by path
anchorsfactory MyFont.ufo --rules-path my-rules -r default     # by name
export ANCHORSFACTORY_RULES_PATH=my-rules                      # or by environment
```

A name is also looked up **next to the file doing the referencing**, so a set
can `!extends default` its neighbour with no configuration at all. In Python,
`load_document(ref, base_dir=…, search_paths=[…])`; process-wide,
`anchorsfactory.set_search_paths([…])`.

`default` and `default-italics` are the samples to start from. The italic one is
an **overlay**: the shear itself is automatic, so it only restates what a slanted
*drawing* changes — eight rules on top of `default` rather than a second copy of
it.

`examples/rules/default.anchors` covers **Latin core** — Basic Latin, Latin-1
Supplement and Latin Extended-A — and is *generated from the Unicode database*:
every composite comes from a canonical decomposition, and every base carries
exactly the anchors those composites ask of it. It ships with a matching
`default.glyphsConstruction`, so the two halves of the pipeline stay in step —
AnchorsFactory places the anchors, GlyphConstruction assembles the composites.

Rules address glyphs **by codepoint** (`U+00C1`) wherever the name would be a
guess, so they make no assumption about a font's naming scheme; the ASCII
letters, which every font names alike, stay spelled out as `A`–`Z` / `a`–`z`.

Accents get both treatments, because fonts ship them both ways: each mark is
ruled on its **combining** codepoint *and* its spacing twin (`U+0301` and
`U+00B4`), and again under the **legacy names** a font may use for glyphs that
carry no codepoint at all — `acutecomb`, and the capital-height set `Acute` /
`acute.case`, which is anchored at cap height rather than the lowercase
midpoint.

Wider Latin sits alongside it: `examples/rules/latin-ext-b.*` and
`latin-ext-additional.*` (Vietnamese and the dot-below accents), plus the
pre-generation `legacy-*` sets and the script sets `devanagari` / `hebrew` /
`thai`.

Old `.txt` rule files (see `examples/`) convert to the new syntax — verified
lossless:

```bash
anchorsfactory-convert examples/default-anchors-list.txt -o my-rules.anchors
```

## Library API

```python
from anchorsfactory import process_ufo, load_document, apply_document

process_ufo("MyFont.ufo", "my-rules.anchors")  # high-level: open, apply, save

from fontParts.world import OpenFont
font = OpenFont("MyFont.ufo")
apply_document(font, load_document("my-rules.anchors"))
font.save()
```

### Composites (GlyphConstruction)

`anchorsfactory.composites` assembles composite glyphs from the anchors just
placed, using a vendored, unmodified [GlyphConstruction](https://github.com/typemytype/GlyphConstruction).

```python
from anchorsfactory import load_document, apply_document
from anchorsfactory.composites import build_composites
from anchorsfactory.presets import construction_text

RULES = ["examples/rules"]                              # your rule library
apply_document(font, load_document("default", search_paths=RULES))   # anchors first
built = build_composites(font, construction_text("default", search_paths=RULES))
built["Aacute"].glyph        # a ConstructionGlyph: .draw(pen) / .width / .components
built["Aacute"].source_line  # the construction's line, for click-to-rule
built["Aacute"].problems     # missing base/mark glyph or anchor, if any
```

Constructions use stock GlyphConstruction syntax with **one AnchorsFactory
extension**: a glyph may be addressed as `U+XXXX`, resolved to the font's own
glyph name before the engine sees it (the font's cmap first, then a combining
mark's spacing twin, then the AGL name, then `uniXXXX`). Plain names still work
and are the better choice where a name is unambiguous.

A mark may take a **`.case`** suffix, asking for the font's capital-height accent
set — a legacy cut that exists under a name (`Acute`, `acute.case`) but never a
codepoint. Fonts without one fall back to the plain mark, so the same file builds
either way:

```
U+00C1 = A + U+0301.case@top   | 00C1  # Á · LATIN CAPITAL LETTER A WITH ACUTE
U+00E1 = a + U+0301@top        | 00E1  # á · LATIN SMALL LETTER A WITH ACUTE
```

That keeps a rule set portable across naming schemes, at the cost of stock
GlyphConstruction not reading such a file — call `resolve_unicode_refs(text, font)`
to get plain-name text back. Files with no `U+` token are untouched, so
name-based constructions keep working unchanged.

### Compute without mutating (preview)

`compute_document` is the functional core: it returns the anchors a rule
document *would* place, keyed by glyph, without touching the font. It owns the
same orchestration as `apply_document` (suffix expansion, `shift_x`, rounding,
same-name dedup), so a preview never drifts from what gets written.

```python
from anchorsfactory import compute_document, load_document, accumulate, resolve

doc = load_document("my-rules.anchors")
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

### Editor support (`anchorsfactory.vocabulary`)

Everything an editor needs to highlight and complete the rule language, taken
from the same tables the parser is built from — so a client never hard-codes a
word the parser might later reject.

```python
from anchorsfactory.vocabulary import (
    FRAMES, X_ALIGNS, Y_EDGES, RUNS, METRICS, CENTROID,
    DIRECTIVES, PROPAGATE_VALUES, SUFFIX_KEYWORDS, OPERATORS, SIGILS,
    completions_after_dot, completions_for_slot, as_dict,
)

completions_after_dot("box", axis="y")     # ("bottom", "middle", "top")
completions_after_dot("width", axis="y")   # () — the advance frame is X-only
completions_for_slot("x")                  # what may open the X slot (no metrics)
as_dict()                                  # the whole thing, JSON-serialisable
```

Both axes share one `frame.position` grammar but not one alignment table:
`left/center/right` is X, `bottom/middle/top` is Y, and a font metric only opens
a Y slot. Passing the slot the caret sits in therefore narrows a menu from six
words to three; pass `axis=None` when the slot is unknown and both come back.

Note it is deliberately not the IR: `Frame.ADVANCE` is a node name, the word a
user types is `width`. A client completing straight off `anchorsfactory.model`
gets the former and offers a token the parser rejects.

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
