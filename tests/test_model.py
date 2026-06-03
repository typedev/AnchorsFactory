"""Unit tests for the IR (model.py): construction, validation, rendering."""

import pytest

from anchorsfactory.model import (
    Frame, HAlign, VEdge, Run, Frac,
    X, XAbs, Y, YAbs, AnchorSpec,
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
    assert str(spec) == "top:outline.first.center:$h*5/6"


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
