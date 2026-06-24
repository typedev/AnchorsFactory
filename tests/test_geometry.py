"""Property tests for the geometry engine, run against any available UFO.

These are deliberately font-agnostic: they glob ``ufo-test/`` for a font and
skip if none is present, and they assert invariants that hold for any sane
Latin design rather than hard-coded coordinates (which would tie the test to
a specific, non-shipped font). Exact-value checks for the local test fonts
live in ``dev/check_numbers.py`` instead.
"""

from pathlib import Path

import pytest

from anchorsfactory.geometry import (
    resolve, resolve_x, resolve_y, _crossings, _spans, _centroid, AxisCycleError,
)
from anchorsfactory.model import (
    Frame, Axis, HAlign, VEdge, Run, Frac,
    X, Pos, Centroid, Abs, Y, FontMetric, Sum, YSum, AnchorSpec,
)

fontParts_world = pytest.importorskip("fontParts.world")

_UFOS = sorted(Path("ufo-test").glob("*.ufo"))
if not _UFOS:
    pytest.skip("no test UFO available in ufo-test/", allow_module_level=True)


@pytest.fixture(scope="module")
def font():
    return fontParts_world.OpenFont(str(_UFOS[0]))


def _has(font, name):
    if name not in font:
        pytest.skip(f"glyph {name!r} not in test font")
    return font[name]


# --- frame semantics ------------------------------------------------------- #
def test_advance_center_is_half_width(font):
    g = _has(font, "H")
    assert resolve_x(font, g, X(Frame.ADVANCE, HAlign.CENTER), 0) == pytest.approx(g.width / 2)


def test_box_edges_match_bounds(font):
    g = _has(font, "H")
    xMin, _, xMax, _ = g.bounds
    assert resolve_x(font, g, X(Frame.BOX, HAlign.LEFT), 0) == pytest.approx(xMin)
    assert resolve_x(font, g, X(Frame.BOX, HAlign.RIGHT), 0) == pytest.approx(xMax)
    assert resolve_x(font, g, X(Frame.BOX, HAlign.CENTER), 0) == pytest.approx((xMin + xMax) / 2)


# --- outline crossings: the core fix vs the old pixel scan ----------------- #
def test_outline_envelope_is_min_max_crossing(font):
    """With no run, outline.left/right are the leftmost/rightmost crossings,
    and every crossing stays within the glyph's bounding box (the bounded-
    intersection guarantee — no phantom infinite-line roots)."""
    g = _has(font, "O")
    y = g.bounds[3] * 0.2
    xMin, _, xMax, _ = g.bounds
    xs = _crossings(g, y)
    assert xs, "expected the scanline to cross the O outline"
    assert all(xMin - 1 <= x <= xMax + 1 for x in xs), "crossing outside bbox"
    assert resolve_x(font, g, X(Frame.OUTLINE, HAlign.RIGHT), y) == pytest.approx(max(xs))
    assert resolve_x(font, g, X(Frame.OUTLINE, HAlign.LEFT), y) == pytest.approx(min(xs))


def test_outline_handles_components(font):
    """Composites are decomposed: a precomposed accented glyph still crosses."""
    for name in ("Aacute", "Eacute", "Oacute"):
        if name in font:
            g = font[name]
            assert _crossings(g, g.bounds[3] * 0.3), f"{name} should have crossings"
            return
    pytest.skip("no precomposed accented glyph in test font")


# --- stems / spans: the ħ motivation --------------------------------------- #
def test_two_stem_glyph_has_distinct_stems(font):
    """For H high up, first and last stem centers differ and bracket the envelope."""
    g = _has(font, "H")
    y = g.bounds[3] * 5 / 6
    spans = _spans(_crossings(g, y))
    if len(spans) < 2:
        pytest.skip("H is single-span at this height in this font")
    first = resolve_x(font, g, X(Frame.OUTLINE, HAlign.CENTER, run=Run.FIRST), y)
    last = resolve_x(font, g, X(Frame.OUTLINE, HAlign.CENTER, run=Run.LAST), y)
    whole = resolve_x(font, g, X(Frame.OUTLINE, HAlign.CENTER), y)
    assert first < last
    assert first < whole < last          # envelope center sits in the gap
    # each stem center is the midpoint of its own span
    assert first == pytest.approx((spans[0][0] + spans[0][1]) / 2)
    assert last == pytest.approx((spans[-1][0] + spans[-1][1]) / 2)


def test_run_index_matches_first(font):
    g = _has(font, "H")
    y = g.bounds[3] * 5 / 6
    if len(_spans(_crossings(g, y))) < 1:
        pytest.skip("no spans")
    by_enum = resolve_x(font, g, X(Frame.OUTLINE, HAlign.CENTER, run=Run.FIRST), y)
    by_index = resolve_x(font, g, X(Frame.OUTLINE, HAlign.CENTER, run=1), y)
    assert by_enum == pytest.approx(by_index)


# --- vertical resolution --------------------------------------------------- #
def test_y_edges_and_fraction(font):
    g = _has(font, "H")
    _, yMin, _, yMax = g.bounds
    assert resolve_y(font, Y("H", VEdge.TOP)) == pytest.approx(yMax)
    assert resolve_y(font, Y("H", VEdge.BOTTOM)) == pytest.approx(yMin)
    assert resolve_y(font, Y("H", VEdge.MIDDLE)) == pytest.approx((yMin + yMax) / 2)
    assert resolve_y(font, Y("H", Frac(5, 6))) == pytest.approx(yMax * 5 / 6)


def test_font_metric_heights(font):
    assert resolve_y(font, FontMetric("xHeight")) == pytest.approx(font.info.xHeight)
    assert resolve_y(font, FontMetric("descender")) == pytest.approx(font.info.descender)
    assert resolve_y(font, FontMetric("capHeight", Frac(2, 3))) == pytest.approx(font.info.capHeight * 2 / 3)
    assert resolve_y(font, FontMetric("baseline")) == 0.0


def test_y_sum_is_additive(font):
    mid = YSum((FontMetric("capHeight", Frac(1, 2)), FontMetric("xHeight", Frac(1, 2))))
    assert resolve_y(font, mid) == pytest.approx((font.info.capHeight + font.info.xHeight) / 2)


# --- unified axes: Y-side frame positions ---------------------------------- #
def _xy(font, g, x, y):
    return resolve(font, g, AnchorSpec("a", x, y))


def test_box_position_on_both_axes(font):
    """box.center / box.middle resolve to the bbox centre on each axis."""
    g = _has(font, "H")
    xMin, yMin, xMax, yMax = g.bounds
    x, y = _xy(font, g, X(Frame.BOX, HAlign.CENTER),
               Pos(Frame.BOX, VEdge.MIDDLE, axis=Axis.Y))
    assert x == pytest.approx((xMin + xMax) / 2)
    assert y == pytest.approx((yMin + yMax) / 2)
    # box.top / box.bottom are the bbox extremes (subsumes the old $self need)
    _, top = _xy(font, g, X(Frame.BOX, HAlign.LEFT), Pos(Frame.BOX, VEdge.TOP, axis=Axis.Y))
    _, bot = _xy(font, g, X(Frame.BOX, HAlign.LEFT), Pos(Frame.BOX, VEdge.BOTTOM, axis=Axis.Y))
    assert (bot, top) == pytest.approx((yMin, yMax))


def test_outline_vertical_scanline(font):
    """outline.middle on Y is the vertical-span centre at the anchor's column."""
    g = _has(font, "H")
    xMin, _, xMax, _ = g.bounds
    col = (xMin + xMax) / 2
    ys = _crossings(g, col, Axis.Y)
    if not ys:
        pytest.skip("center column does not cross H here")
    # X is a fixed column (box.center), Y samples the vertical scanline there
    _, y = _xy(font, g, X(Frame.BOX, HAlign.CENTER),
               Pos(Frame.OUTLINE, VEdge.MIDDLE, axis=Axis.Y))
    assert y == pytest.approx((ys[0] + ys[-1]) / 2)


# --- unified axes: fractional positions ------------------------------------ #
def test_fractional_box_x(font):
    g = _has(font, "H")
    xMin, _, xMax, _ = g.bounds
    assert resolve_x(font, g, Pos(Frame.BOX, Frac(1, 2)), 0) == pytest.approx((xMin + xMax) / 2)
    assert resolve_x(font, g, Pos(Frame.BOX, Frac(1, 4)), 0) == pytest.approx(xMin + (xMax - xMin) / 4)


def test_fractional_advance_x(font):
    g = _has(font, "H")
    assert resolve_x(font, g, Pos(Frame.ADVANCE, Frac(1, 3)), 0) == pytest.approx(g.width / 3)


# --- centroid -------------------------------------------------------------- #
def test_centroid_is_inside_bounds(font):
    g = _has(font, "a")
    xMin, yMin, xMax, yMax = g.bounds
    cx, cy = _centroid(g)
    assert xMin <= cx <= xMax and yMin <= cy <= yMax
    # the 2-D point is what an anchor with centroid on both axes resolves to
    x, y = _xy(font, g, Centroid(), Centroid())
    assert (x, y) == pytest.approx((cx, cy))


# --- X arithmetic: base position + bias (acute/grave) ---------------------- #
def test_x_sum_biases_the_centroid(font):
    g = _has(font, "a")
    cx, _ = _centroid(g)
    cap = FontMetric("capHeight")
    left = resolve(font, g, AnchorSpec("t", Sum((Centroid(), Abs(-25))), cap))
    right = resolve(font, g, AnchorSpec("t", Sum((Centroid(), Abs(25))), cap))
    assert left[0] == pytest.approx(cx - 25)
    assert right[0] == pytest.approx(cx + 25)
    assert right[0] - left[0] == pytest.approx(50)


def test_x_sum_keeps_outline_dependency(font):
    """A sum with an outline term still samples at the anchor's Y, then biases."""
    g = _has(font, "H")
    y = g.bounds[3] * 0.4
    xs = _crossings(g, y)
    plain = resolve_x(font, g, X(Frame.OUTLINE, HAlign.RIGHT), y)
    biased = resolve_x(font, g, Sum((X(Frame.OUTLINE, HAlign.RIGHT), Abs(-10))), y)
    assert plain == pytest.approx(max(xs))
    assert biased == pytest.approx(plain - 10)


# --- axis cycle ------------------------------------------------------------ #
def test_both_outline_no_at_is_a_cycle(font):
    g = _has(font, "H")
    spec = AnchorSpec("a", X(Frame.OUTLINE, HAlign.RIGHT),
                      Pos(Frame.OUTLINE, VEdge.MIDDLE, axis=Axis.Y))
    with pytest.raises(AxisCycleError):
        resolve(font, g, spec)


def test_at_breaks_the_cycle(font):
    """Fixing one axis's scanline with @ makes the pair resolvable."""
    g = _has(font, "H")
    _, yMax = g.bounds[1], g.bounds[3]
    spec = AnchorSpec("a",
                      X(Frame.OUTLINE, HAlign.RIGHT, at=FontMetric("capHeight", Frac(1, 2))),
                      Pos(Frame.OUTLINE, VEdge.MIDDLE, axis=Axis.Y))
    x, y = resolve(font, g, spec)         # X fixed at a height → Y samples in that column
    assert x == pytest.approx(x) and y == pytest.approx(y)   # resolves without raising


def test_outline_sample_height_is_decoupled_from_y(font):
    """outline.center@xHeight samples at xHeight regardless of the anchor's Y."""
    g = _has(font, "o")
    xs = _crossings(g, font.info.xHeight)
    expected = (min(xs) + max(xs)) / 2
    spec = X(Frame.OUTLINE, HAlign.CENTER, at=FontMetric("xHeight"))
    # same result whether the anchor Y is 0 or high up
    assert resolve_x(font, g, spec, 0) == pytest.approx(expected)
    assert resolve_x(font, g, spec, 999) == pytest.approx(expected)


# --- out-of-ink sample heights are clamped, but flagged (issue #5) ---------- #
def test_outline_sample_above_ink_is_flagged_not_silent(font):
    """@ascender on an x-height glyph is clamped to the top edge — and warned."""
    g = _has(font, "x")
    _, _, _, yMax = g.bounds
    asc = font.info.ascender
    if asc is None or asc <= yMax:
        pytest.skip("font ascender is not above the x-height ink")
    warns: list[str] = []
    spec = X(Frame.OUTLINE, HAlign.RIGHT, at=FontMetric("ascender"))
    resolve_x(font, g, spec, 0, warnings=warns)
    assert any("outside the ink box" in w for w in warns)


def test_outline_sample_at_extreme_is_silent(font):
    """Sampling the glyph's own @top extreme, where it crosses, is no warning."""
    g = _has(font, "x")
    warns: list[str] = []
    spec = X(Frame.OUTLINE, HAlign.RIGHT, at=VEdge.TOP)
    resolve_x(font, g, spec, 0, warnings=warns)
    assert warns == []


def test_outline_at_extreme_is_literal_not_inset(font):
    """`@top` samples at exactly yMax — no ±1 inset. The result is the rightmost
    crossing at the extreme itself, not the (wider) one a unit inside (#8)."""
    g = _has(font, "O")
    _, _, _, yMax = g.bounds
    top = _crossings(g, yMax)
    if not top:
        pytest.skip("O has no crossing exactly at yMax in this font")
    got = resolve_x(font, g, X(Frame.OUTLINE, HAlign.RIGHT, at=VEdge.TOP), 0)
    assert got == pytest.approx(max(top))            # literal: the yMax crossing
    inside = _crossings(g, yMax - 1)                  # the height the inset used
    if inside and max(inside) != pytest.approx(max(top)):
        assert got != pytest.approx(max(inside))     # …and not the inset value
