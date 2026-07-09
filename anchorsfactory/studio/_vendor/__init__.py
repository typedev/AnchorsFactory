"""Vendored third-party code, frozen and unmodified.

Currently: ``glyphConstruction`` — Frederik Berlaen's GlyphConstruction, the
composite-assembly half of the pipeline (snaps mark anchors onto base anchors).
AnchorsFactory places the anchors; GlyphConstruction reads them to build glyphs.

Do NOT edit ``glyphConstruction.py`` — it is a byte-for-byte copy of upstream so
it can be re-synced. Our own logic (adapters, the grouping expander) belongs in
sibling modules that import from here, never inside the vendored file. See
``README.md`` for provenance and licence.
"""
