"""Vendored third-party code, frozen and unmodified.

Currently: ``glyphconstruction`` — Frederik Berlaen's GlyphConstruction, the
composite-assembly half of the pipeline (snaps mark anchors onto base anchors).
AnchorsFactory places the anchors; GlyphConstruction reads them to build glyphs.

Do NOT edit ``glyphconstruction.py`` — its contents are a byte-for-byte copy of
upstream (only the filename is lower-cased) so it can be re-synced. Our own logic
(the public ``anchorsfactory.composites`` API and app adapters) belongs in
modules that import from here, never inside the vendored file. See ``README.md``
for provenance and licence.
"""
