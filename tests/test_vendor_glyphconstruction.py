"""Smoke test for the vendored GlyphConstruction and the AnchorsFactory→GC seam.

Proves two things on the current fontTools/fontParts stack:
1. the vendored module imports with no dependency beyond fontTools (its
   ``defcon``/``fontPens`` uses are confined to its own ``__main__`` self-tests);
2. anchors AnchorsFactory places are exactly what GlyphConstruction reads to
   assemble a composite — i.e. the pipeline seam (AF places anchors → GC snaps
   marks onto them) actually works, not just in theory.
"""

import pytest

pytest.importorskip("fontParts.world")

from anchorsfactory.apply import apply_document
from anchorsfactory.runner import load_document
from anchorsfactory.studio.demo import build_demo_font
from anchorsfactory.studio._vendor.glyphConstruction import (
    GlyphConstructionBuilder,
    ParseGlyphConstructionListFromString,
)


def test_vendored_module_imports_without_extra_deps():
    # Importing must not require defcon/fontPens — they are referenced only in
    # the module's __main__ self-tests, never at module import time.
    assert callable(GlyphConstructionBuilder)
    assert callable(ParseGlyphConstructionListFromString)


def test_gc_assembles_composite_from_af_anchors():
    font = build_demo_font()
    apply_document(font, load_document("default"))

    a_anchors = {a.name: (a.x, a.y) for a in font["a"].anchors}
    acute_anchors = {a.name: (a.x, a.y) for a in font["acute"].anchors}
    # AF placed the pair GC needs: a base `top` and a mark `_top`.
    assert "top" in a_anchors
    assert "_top" in acute_anchors

    # `acute@top` = snap acute's `_top` anchor onto a's `top` anchor.
    dest = GlyphConstructionBuilder("aacuteGC = a + acute@top", font)
    assert dest.name == "aacuteGC"
    assert [gn for gn, _ in dest.components] == ["a", "acute"]

    # GC positioned acute exactly by the anchor delta (top − _top) — this is the
    # seam under test. (In the demo both anchors share y, so the delta is on x.)
    ax, ay = a_anchors["top"]
    mx, my = acute_anchors["_top"]
    _, _, _, _, dx, dy = dict(dest.components)["acute"]
    assert (round(dx), round(dy)) == (round(ax - mx), round(ay - my))
    assert (round(dx), round(dy)) != (0, 0)   # GC actually used the anchors

    # The write path (draw → pen.addComponent) round-trips into a real glyph.
    target = font.newGlyph(dest.name)
    dest.draw(target.getPen())
    assert [c.baseGlyph for c in target.components] == ["a", "acute"]
