"""Unit tests for the IR (model.py): construction, validation, rendering."""

import pytest

from anchorsfactory.model import (
    Frame, HAlign, VEdge, Run, Frac, Axis,
    X, Pos, Centroid, Abs, XAbs, YAbs, Y, FontMetric, Sum, YSum, AnchorSpec,
)


# --- rendering: IR -> DSL token (round-trips the vocabulary) --------------- #
@pytest.mark.parametrize("spec, token", [
    (X(Frame.ADVANCE, HAlign.CENTER), "width.center"),
    (X(Frame.ADVANCE, HAlign.LEFT), "width.left"),
    (X(Frame.BOX, HAlign.CENTER), "box.center"),
    (X(Frame.BOX, HAlign.RIGHT), "box.right"),
    (X(Frame.OUTLINE, HAlign.LEFT), "outline.left"),
    (X(Frame.OUTLINE, HAlign.RIGHT), "outline.right"),
    (X(Frame.OUTLINE, HAlign.CENTER, run=Run.FIRST), "outline.first.center"),
    (X(Frame.OUTLINE, HAlign.CENTER, run=Run.LAST), "outline.last.center"),
    (X(Frame.OUTLINE, HAlign.CENTER, run=2), "outline.2.center"),
    (X(Frame.OUTLINE, HAlign.CENTER, at=VEdge.TOP), "outline.center@top"),
    (XAbs(400), "400"),
])
def test_x_token_rendering(spec, token):
    assert str(spec) == token


@pytest.mark.parametrize("spec, token", [
    (Y("H"), "$H"),
    (Y("H", VEdge.BOTTOM), "$H.bottom"),
    (Y("H", VEdge.MIDDLE), "$H.middle"),
    (Y("H", Frac(5, 6)), "$H*5/6"),
    (YAbs(575), "575"),
])
def test_y_token_rendering(spec, token):
    assert str(spec) == token


def test_anchorspec_rendering():
    spec = AnchorSpec("top", X(Frame.OUTLINE, HAlign.CENTER, run=Run.FIRST), Y("h", Frac(5, 6)))
    assert str(spec) == "top (outline.first.center $h*5/6)"


# --- validation: illegal combinations are rejected at construction --------- #
def test_run_requires_outline():
    with pytest.raises(ValueError):
        X(Frame.BOX, HAlign.CENTER, run=Run.FIRST)


def test_at_requires_outline():
    with pytest.raises(ValueError):
        X(Frame.ADVANCE, HAlign.CENTER, at=VEdge.TOP)


def test_run_index_is_one_based():
    with pytest.raises(ValueError):
        X(Frame.OUTLINE, HAlign.CENTER, run=0)


def test_at_middle_is_meaningless():
    with pytest.raises(ValueError):
        X(Frame.OUTLINE, HAlign.CENTER, at=VEdge.MIDDLE)


def test_frac_denominator_nonzero():
    with pytest.raises(ValueError):
        Frac(1, 0)


def test_specs_are_hashable():
    # frozen dataclasses → usable as dict keys / set members
    {X(Frame.BOX, HAlign.LEFT), Y("H"), AnchorSpec("top", XAbs(0), YAbs(0))}


# --- unified Pos: Y-axis positions, fractions, centroid -------------------- #
def test_x_is_pos_alias():
    assert X is Pos


@pytest.mark.parametrize("spec, token", [
    (Pos(Frame.BOX, VEdge.TOP, axis=Axis.Y), "box.top"),
    (Pos(Frame.BOX, VEdge.BOTTOM, axis=Axis.Y), "box.bottom"),
    (Pos(Frame.BOX, VEdge.MIDDLE, axis=Axis.Y), "box.middle"),
    (Pos(Frame.OUTLINE, VEdge.MIDDLE, axis=Axis.Y), "outline.middle"),
    (Pos(Frame.OUTLINE, VEdge.MIDDLE, run=Run.FIRST, axis=Axis.Y), "outline.first.middle"),
    (Pos(Frame.OUTLINE, VEdge.MIDDLE, run=1, axis=Axis.Y), "outline.1.middle"),
    # @-decoupling on Y is a column (left/right or an X value)
    (Pos(Frame.OUTLINE, VEdge.MIDDLE, at=HAlign.RIGHT, axis=Axis.Y), "outline.middle@right"),
    (Pos(Frame.OUTLINE, VEdge.MIDDLE, at=XAbs(40), axis=Axis.Y), "outline.middle@40"),
])
def test_y_pos_rendering(spec, token):
    assert str(spec) == token


@pytest.mark.parametrize("spec, token", [
    (Pos(Frame.ADVANCE, Frac(1, 3)), "width*1/3"),
    (Pos(Frame.BOX, Frac(2, 3)), "box*2/3"),
    (Pos(Frame.BOX, Frac(1, 4), axis=Axis.Y), "box*1/4"),
])
def test_fractional_rendering(spec, token):
    assert str(spec) == token


def test_centroid_rendering():
    assert str(Centroid()) == "outline.centroid"
    # polymorphic: legal in either slot
    assert str(AnchorSpec("c", Centroid(), Centroid())) == "c (outline.centroid outline.centroid)"


def test_abs_is_unified_and_polymorphic():
    assert XAbs is Abs and YAbs is Abs        # one class, two legacy names
    assert XAbs(40) == YAbs(40)               # no longer axis-typed
    assert str(Abs(-25)) == "-25"


def test_edge_offset_rendering_and_validation():
    from anchorsfactory.model import EdgeOffset
    assert str(EdgeOffset(VEdge.TOP, -10)) == "top-10"
    assert str(EdgeOffset(VEdge.BOTTOM, 8)) == "bottom+8"
    assert str(Pos(Frame.OUTLINE, HAlign.CENTER, at=EdgeOffset(VEdge.TOP, -10))) == \
        "outline.center@top-10"
    assert str(Pos(Frame.OUTLINE, VEdge.MIDDLE, at=EdgeOffset(HAlign.LEFT, -5), axis=Axis.Y)) == \
        "outline.middle@left-5"
    with pytest.raises(ValueError):                     # X sample height must be top/bottom
        Pos(Frame.OUTLINE, HAlign.CENTER, at=EdgeOffset(HAlign.LEFT, -5))
    with pytest.raises(ValueError):                     # Y sample column must be left/right
        Pos(Frame.OUTLINE, VEdge.MIDDLE, at=EdgeOffset(VEdge.TOP, -5), axis=Axis.Y)


def test_component_frame_rendering_and_validation():
    assert str(Pos(Frame.BOX, HAlign.RIGHT, component=2)) == "comp2.box.right"
    assert str(Pos(Frame.OUTLINE, HAlign.CENTER, at=VEdge.TOP, component=-1)) == \
        "complast.outline.center@top"
    assert str(Centroid(component=1)) == "comp1.outline.centroid"
    with pytest.raises(ValueError):                     # advance belongs to whole glyph
        Pos(Frame.ADVANCE, HAlign.CENTER, component=1)
    with pytest.raises(ValueError):                     # 1-based
        Pos(Frame.BOX, HAlign.CENTER, component=0)


def test_anchor_ref_rendering_and_hash():
    from anchorsfactory.model import AnchorRef, Neg
    assert str(AnchorRef("top")) == "%top"
    assert str(Sum((AnchorRef("bottom"), Neg(Abs(7))))) == "%bottom-7"
    assert str(AnchorSpec("b", AnchorRef("top"), Abs(0))) == "b (%top 0)"
    assert AnchorRef("top") == AnchorRef("top") and hash(AnchorRef("top"))   # frozen/hashable


def test_sum_rendering():
    assert YSum is Sum
    assert str(Sum((FontMetric("capHeight", Frac(1, 2)),
                    FontMetric("xHeight", Frac(1, 2))))) == "capHeight*1/2+xHeight*1/2"
    # a negative numeric term renders with '-', not '+-'
    assert str(Sum((Centroid(), Abs(-25)))) == "outline.centroid-25"
    assert str(Sum((Pos(Frame.BOX, HAlign.CENTER), Abs(20)))) == "box.center+20"


# --- unified Pos: validation ----------------------------------------------- #
def test_advance_has_no_vertical():
    with pytest.raises(ValueError):
        Pos(Frame.ADVANCE, VEdge.TOP, axis=Axis.Y)


def test_align_kind_must_match_axis():
    with pytest.raises(ValueError):
        Pos(Frame.BOX, HAlign.CENTER, axis=Axis.Y)   # HAlign on Y
    with pytest.raises(ValueError):
        Pos(Frame.BOX, VEdge.TOP, axis=Axis.X)       # VEdge on X


def test_fraction_not_on_outline():
    with pytest.raises(ValueError):
        Pos(Frame.OUTLINE, Frac(1, 2))


def test_y_at_must_be_a_column():
    with pytest.raises(ValueError):
        Pos(Frame.OUTLINE, VEdge.MIDDLE, at=HAlign.CENTER, axis=Axis.Y)  # @center meaningless
    with pytest.raises(ValueError):
        Pos(Frame.OUTLINE, VEdge.MIDDLE, at=VEdge.TOP, axis=Axis.Y)      # Y edge, not a column


def test_x_at_must_be_a_height():
    with pytest.raises(ValueError):
        Pos(Frame.OUTLINE, HAlign.CENTER, at=HAlign.LEFT)               # X edge, not a height
