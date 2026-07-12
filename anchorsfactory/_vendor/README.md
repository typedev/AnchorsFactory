# Vendored: GlyphConstruction

`glyphconstruction.py` is a **frozen** copy of Frederik Berlaen's
GlyphConstruction — the language + engine that assembles composite glyphs by
snapping a mark's anchor onto a base's anchor. It is the assembly half of the
pipeline whose first half (placing the anchors) is AnchorsFactory itself. The
file **contents** are byte-for-byte upstream; only the filename is lower-cased
(`glyphConstruction.py` → `glyphconstruction.py`) for the module import. The
public wrapper is `anchorsfactory.composites`.

## Provenance

- **Upstream:** https://github.com/typemytype/GlyphConstruction
- **File:** `Lib/glyphConstruction.py`
- **Fetched from:** `master` @ commit `338f46770f54b4e48edde9dded14876bedc6dae8`
  (2023-11-13), the latest commit touching that file.
- **Licence:** MIT © 2014 Frederik Berlaen — see `LICENSE` (shipped alongside;
  the source file carries no header, so the separate `LICENSE` is the attribution).

## Rules

- **Do not edit `glyphconstruction.py`.** Keep its contents byte-for-byte with
  upstream so it can be re-synced. Our own code (the `anchorsfactory.composites`
  wrapper, app adapters) lives in sibling modules that import from here — never
  as edits to the vendored file.
- Its module-level imports are stdlib + fontTools only (already a core
  dependency). `defcon`/`fontPens` are referenced only inside its own `__main__`
  self-tests, so importing the module pulls in nothing extra.

## Re-syncing

```bash
curl -fsSL https://raw.githubusercontent.com/typemytype/GlyphConstruction/master/Lib/glyphConstruction.py \
  -o anchorsfactory/_vendor/glyphconstruction.py
curl -fsSL https://raw.githubusercontent.com/typemytype/GlyphConstruction/master/LICENSE \
  -o anchorsfactory/_vendor/LICENSE
```

Then update the commit/date above and re-run `tests/test_vendor_glyphconstruction.py`.
