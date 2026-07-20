"""Italic shear: an X measured at height S is projected along the italic angle
to the anchor's own height Y (shift = tan(-angle)·(Y - S)).

Self-contained — builds a tiny in-memory font with a known upright stem and a
slant, so it needs no shipped fixture and the expected numbers are exact.
"""

import math

import pytest

fpw = pytest.importorskip("fontParts.world")

from anchorsfactory.geometry import resolve_x
from anchorsfactory.model import Frame, HAlign, Abs, Pos, Centroid, Sum, FontMetric

ANGLE = -10.0                       # forward-leaning italic
TAN = math.tan(math.radians(-ANGLE))   # ≈ 0.17633; shear per unit of height gap


@pytest.fixture
def italic():
    """A font slanted -10° with one glyph: an upright rectangle x∈[80,120]
    (centre 100), y∈[0,700] — centre constant at every height, so any shear in
    the result is the engine's, not the outline's."""
    f = fpw.RFont()
    f.info.unitsPerEm = 1000
    f.info.italicAngle = ANGLE
    f.info.xHeight = 500
    f.info.capHeight = 700
    f.info.ascender = 750
    f.info.descender = -200
    g = f.newGlyph("stem")
    g.width = 200
    pen = g.getPen()
    pen.moveTo((80, 0)); pen.lineTo((120, 0))
    pen.lineTo((120, 700)); pen.lineTo((80, 700))
    pen.closePath()
    return f, g


@pytest.fixture
def slanted(italic):
    """The same stem, actually sheared to the font's angle — a real italic glyph,
    where the upright centre 100 sits at 100 + TAN·y."""
    f, _ = italic
    g = f.newGlyph("slantedstem")
    g.width = 200
    pen = g.getPen()
    pen.moveTo((80, 0)); pen.lineTo((120, 0))
    pen.lineTo((120 + TAN * 700, 700)); pen.lineTo((80 + TAN * 700, 700))
    pen.closePath()
    return f, g


def test_plain_outline_is_not_sheared(italic):
    # sampled at the anchor's own height (S == Y) → gap 0 → no shear
    f, g = italic
    assert resolve_x(f, g, Pos(Frame.OUTLINE, HAlign.CENTER), 600) == pytest.approx(100)


def test_outline_at_sample_height_projects_up_the_slant(italic):
    # the `l` case: X measured at xHeight, anchor higher → shear tan·(Y - xHeight)
    f, g = italic
    spec = Pos(Frame.OUTLINE, HAlign.CENTER, at=FontMetric("xHeight"))
    assert resolve_x(f, g, spec, 600) == pytest.approx(100 + TAN * (600 - 500))
    # the `H` invariant: when the sample height equals the anchor height, no shear
    assert resolve_x(f, g, spec, 500) == pytest.approx(100)


def test_advance_reference_shears_from_baseline(italic):
    # the advance box is upright whatever the outline does (S = 0) → the full tan·Y
    f, g = italic
    assert resolve_x(f, g, Pos(Frame.ADVANCE, HAlign.CENTER), 600) == pytest.approx(100 + TAN * 600)
    assert resolve_x(f, g, Pos(Frame.ADVANCE, HAlign.CENTER), 0) == pytest.approx(100)


def test_box_projects_from_its_bbox_middle(italic):
    # the bbox is measured on the outline, so its centre already sits where the
    # ink is at mid-height: S = (yMin + yMax) / 2, not 0.
    f, g = italic
    assert resolve_x(f, g, Pos(Frame.BOX, HAlign.CENTER), 600) == pytest.approx(100 + TAN * (600 - 350))


@pytest.fixture
def wedge(italic):
    """A slanted `V`: a wedge whose X extremes are both at the top, drawn on the
    same centre (100) as the stem. The shape where a mid-height rule breaks."""
    f, _ = italic
    g = f.newGlyph("wedge")
    g.width = 200
    pen = g.getPen()
    pen.moveTo((100 + TAN * 700 - 60, 700))        # top left
    pen.lineTo((100 + TAN * 700 + 60, 700))        # top right
    pen.lineTo((100 + 10, 0)); pen.lineTo((100 - 10, 0))   # narrow foot
    pen.closePath()
    return f, g


def test_box_centre_is_shape_independent(slanted, wedge):
    """The bug this rule exists for: a V's box extremes sit at the top and an A's
    at the bottom, so a box measured on the slanted outline puts letters drawn on
    one centre in different places. Deslanting before measuring makes the centre a
    property of the drawing, not of where the shape happens to be widest."""
    f, stem = slanted
    _, v = wedge
    for y in (0, 350, 700):
        assert (resolve_x(f, v, Pos(Frame.BOX, HAlign.CENTER), y)
                == pytest.approx(resolve_x(f, stem, Pos(Frame.BOX, HAlign.CENTER), y), abs=1e-6))


def test_box_on_slanted_ink_lands_on_the_ink(slanted):
    """The point of the S = bbox-middle rule: on a genuinely slanted glyph,
    `box.center` must name the same place as the advance centre and the contour
    itself — anything else counts the slant twice."""
    f, g = slanted
    for y in (0, 350, 600):
        ink = resolve_x(f, g, Pos(Frame.OUTLINE, HAlign.CENTER), y)
        assert resolve_x(f, g, Pos(Frame.BOX, HAlign.CENTER), y) == pytest.approx(ink)
        assert resolve_x(f, g, Pos(Frame.ADVANCE, HAlign.CENTER), y) == pytest.approx(ink)


def test_centroid_projects_from_its_own_height(italic):
    # rectangle centroid is (100, 350); as X it projects from cy to the anchor Y
    f, g = italic
    assert resolve_x(f, g, Centroid(), 600) == pytest.approx(100 + TAN * (600 - 350))


def test_sum_shears_per_term(italic):
    # the outline term shears by its gap; the constant bias does not
    f, g = italic
    spec = Sum((Pos(Frame.OUTLINE, HAlign.CENTER, at=FontMetric("xHeight")), Abs(30)))
    assert resolve_x(f, g, spec, 600) == pytest.approx(100 + TAN * (600 - 500) + 30)


def test_upright_font_has_no_shear(italic):
    # the whole correction vanishes when the angle is 0
    f, g = italic
    f.info.italicAngle = 0
    spec = Pos(Frame.OUTLINE, HAlign.CENTER, at=FontMetric("xHeight"))
    assert resolve_x(f, g, spec, 600) == pytest.approx(100)
    assert resolve_x(f, g, Pos(Frame.BOX, HAlign.CENTER), 600) == pytest.approx(100)
