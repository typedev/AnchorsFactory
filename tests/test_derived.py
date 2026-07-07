"""`%name` derived anchors — an anchor placed relative to another already-placed
anchor on the same glyph.

Resolved above the geometry layer: the referenced anchor's coordinate is
substituted in (its x on the X axis, its y on the Y axis), so `%name` composes
in sums and works on either axis. Uses the studio demo font (real geometry) plus
a couple of hand-built specs.
"""

from __future__ import annotations

import pytest

fpw = pytest.importorskip("fontParts.world")

from anchorsfactory.apply import compute_document
from anchorsfactory.dsl import parse_dsl
from anchorsfactory.studio.demo import build_demo_font


def _d(placed, gname):
    return {n: (x, y) for n, x, y in placed[gname]}


def _placed(rules, on_error="raise"):
    return compute_document(build_demo_font(), parse_dsl(rules.splitlines()), on_error=on_error)


# --------------------------------------------------------------------------- #

def test_motivating_case_bottom_reuses_top_x():
    # top and bottom both sample the contour centre but at different heights, so
    # their x can drift; `%top` pins bottom to top's x.
    d = _d(_placed("a = top (outline.center@xHeight 500), bottom (%top 0)"), "a")
    assert d["bottom"][0] == d["top"][0]
    assert d["bottom"][1] == 0


def test_order_independent():
    # bottom declared before its referent top — resolution is by dependency, not
    # source order.
    d = _d(_placed("a = bottom (%top 0), top (box.center 500)"), "a")
    assert d["bottom"][0] == d["top"][0]


def test_ref_plus_bias():
    d = _d(_placed("a = top (box.center 500), bottom (%top-25 0)"), "a")
    assert d["bottom"][0] == d["top"][0] - 25


def test_polymorphic_on_y_axis():
    # %top in a Y slot yields the referent's y.
    d = _d(_placed("a = top (box.center 480), side (box.right %top)"), "a")
    assert d["side"][1] == d["top"][1] == 480


def test_ref_chain():
    d = _d(_placed("a = top (box.center 500), mid (%top -10), low (%mid -5)"), "a")
    assert d["mid"][0] == d["top"][0] and d["low"][0] == d["top"][0]


def test_ref_in_at_sample_line_equals_explicit_height():
    # outline.center@%top must sample at top's y — same as @<that height>.
    ref = _d(_placed("a = top (box.center 480), b (outline.center@%top 0)"), "a")
    lit = _d(_placed("a = top (box.center 480), b (outline.center@480 0)"), "a")
    assert ref["b"] == lit["b"]


def test_cycle_raises_in_batch():
    with pytest.raises(ValueError):
        _placed("a = p (%q 0), q (%p 0)")


def test_cycle_flagged_in_collect():
    placed = _placed("a = p (%q 0), q (%p 0)", on_error="collect")
    assert "a" not in placed                          # neither anchor could resolve
    assert any("cycle" in d.reason for d in placed.diagnostics)


def test_missing_target_skips_with_warning():
    placed = _placed("a = top (box.center 500), bad (%nope 0)", on_error="collect")
    assert set(_d(placed, "a")) == {"top"}            # bad skipped, top kept
    assert any("undefined anchor" in d.reason for d in placed.diagnostics)


def test_missing_target_degrades_in_batch():
    # batch (raise) mode skips the unresolved anchor silently (missing-$glyph policy),
    # rather than aborting the whole run.
    d = _d(_placed("a = top (box.center 500), bad (%nope 0)"), "a")
    assert set(d) == {"top"}


def test_derived_from_propagated_anchor():
    # %name can reference an anchor that was inherited via !propagate (they share
    # the same final list). aacute inherits `top` from a; a local rule derives
    # `mark` from it.
    d = _d(_placed("a = top (box.center 500)\n"
                   "aacute += mark (%top 20)\n"
                   "!propagate = composites"), "aacute")
    assert "top" in d and d["mark"][0] == d["top"][0]
