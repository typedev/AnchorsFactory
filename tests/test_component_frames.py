"""`compN.` / `complast.` per-component frames — measure one component's outline.

Ligatures and other composites seat marks per component; the qualifier scopes a
frame (box / outline / centroid) to the N-th component's decomposed outline.
Built on synthetic fontParts composites.
"""

from __future__ import annotations

import math

import pytest

fpw = pytest.importorskip("fontParts.world")

from anchorsfactory.apply import compute_document
from anchorsfactory.dsl import DSLError, parse_dsl


def _rect(glyph, x0, y0, x1, y1):
    pen = glyph.getPen()
    pen.moveTo((x0, y0)); pen.lineTo((x1, y0)); pen.lineTo((x1, y1)); pen.lineTo((x0, y1))
    pen.closePath()


def _font(italic=0):
    """A `box` unit (0..200 × 0..400) and a `lig` = two boxes, the 2nd offset +500."""
    f = fpw.RFont()
    f.info.unitsPerEm = 1000
    f.info.capHeight = 700
    f.info.italicAngle = italic
    b = f.newGlyph("box"); b.width = 200; _rect(b, 0, 0, 200, 400)
    lig = f.newGlyph("lig"); lig.width = 800
    p = lig.getPen()
    p.addComponent("box", (1, 0, 0, 1, 0, 0))
    p.addComponent("box", (1, 0, 0, 1, 500, 0))
    return f


def _d(rules, font=None, on_error="raise"):
    font = font or _font()
    placed = compute_document(font, parse_dsl(rules.splitlines()), on_error=on_error)
    return {n: (x, y) for n, x, y in placed["lig"]}, placed


# --------------------------------------------------------------------------- #

def test_box_per_component():
    d, _ = _d("lig = a (comp1.box.center 0), b (comp2.box.center 0), "
              "l (comp2.box.left 0), r (comp2.box.right 0)")
    assert d["a"][0] == 100                       # first box centre
    assert d["b"][0] == 600                       # second box centre (offset +500)
    assert (d["l"][0], d["r"][0]) == (500, 700)   # second box edges


def test_outline_per_component():
    d, _ = _d("lig = a (comp1.outline.center@200 0), b (comp2.outline.right@200 0)")
    assert d["a"][0] == 100
    assert d["b"][0] == 700


def test_complast_is_last_component():
    d, _ = _d("lig = z (complast.box.center 0)")
    assert d["z"][0] == 600                        # same as comp2 here


def test_centroid_per_component():
    d, _ = _d("lig = a (comp1.outline.centroid 0), b (comp2.outline.centroid 0)")
    assert d["a"][0] == 100 and d["b"][0] == 600


def test_at_top_uses_component_bbox():
    # @top on a component-qualified outline is that component's top, not the glyph's.
    d, _ = _d("lig = a (comp1.outline.center@top 0)")
    assert d["a"][0] == 100                        # samples within the first box


def test_fewer_components_falls_back_with_warning():
    d, placed = _d("lig = a (comp3.box.center 0)", on_error="collect")
    assert d["a"][0] == 350                        # whole-glyph bbox centre (ink 0..700)
    assert any("component 3 not available" in dg.reason for dg in placed.diagnostics)


def test_width_qualifier_rejected_at_parse():
    with pytest.raises(DSLError):
        parse_dsl(["lig = a (comp1.width.center 0)"])


def test_component_zero_rejected():
    with pytest.raises(DSLError):
        parse_dsl(["lig = a (comp0.box.center 0)"])


def test_italic_shear_uses_component_height():
    # X follows the slant from the height its source is defined at; for a box that
    # is the middle of *the component's* bounds (0..400), not the whole glyph's.
    d, _ = _d("lig = a (comp2.box.center 300)", font=_font(italic=-12))
    expected = 600 + math.tan(math.radians(12)) * (300 - 200)
    assert d["a"][0] == round(expected)
    assert d["a"][1] == 300
