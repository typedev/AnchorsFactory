"""Property tests for the geometry engine, run against any available UFO.

These are deliberately font-agnostic: they glob ``ufo-test/`` for a font and
skip if none is present, and they assert invariants that hold for any sane
Latin design rather than hard-coded coordinates (which would tie the test to
a specific, non-shipped font). Exact-value checks for the local test fonts
live in ``dev/check_numbers.py`` instead.
"""

from pathlib import Path

import pytest

from anchorsfactory.geometry import resolve_x, resolve_y, _crossings, _spans
from anchorsfactory.model import Frame, HAlign, VEdge, Run, Frac, X, Y

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
