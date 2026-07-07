"""`!propagate` — component anchor inheritance.

A composite seeds its accumulator with anchors inherited from its components'
*computed-this-run* anchors (falling back to pre-existing font anchors), pushed
through the component transform. Built on synthetic fontParts composites so the
public suite needs no fixture font.
"""

from __future__ import annotations

import pytest

fpw = pytest.importorskip("fontParts.world")

from anchorsfactory.apply import apply_document, compute_document, propagate_seed
from anchorsfactory.dsl import DSLError, parse_dsl
from anchorsfactory.runner import _merge


def _rect(glyph, x0, y0, x1, y1):
    pen = glyph.getPen()
    pen.moveTo((x0, y0)); pen.lineTo((x1, y0)); pen.lineTo((x1, y1)); pen.lineTo((x0, y1))
    pen.closePath()


def _font():
    """base `a` (rect 0..400 × 0..500), a `acutecomb` mark, and composites
    assembled from them."""
    f = fpw.RFont()
    f.info.unitsPerEm = 1000
    f.info.ascender, f.info.descender = 800, -200
    f.info.capHeight, f.info.xHeight = 700, 500

    a = f.newGlyph("a"); a.width = 400; _rect(a, 0, 0, 400, 500)
    m = f.newGlyph("acutecomb"); m.width = 0; _rect(m, 0, 500, 100, 600)

    aacute = f.newGlyph("aacute"); aacute.width = 400          # pure composite
    p = aacute.getPen()
    p.addComponent("a", (1, 0, 0, 1, 0, 0))
    p.addComponent("acutecomb", (1, 0, 0, 1, 150, 100))
    return f


def _rules(text):
    return parse_dsl(text.splitlines())


# --------------------------------------------------------------------------- #

def test_composite_inherits_component_anchors():
    f = _font()
    doc = _rules("a = top (box.center 500), bottom (box.center 0)\n!propagate = composites")
    placed = compute_document(f, doc)
    assert dict((n, (x, y)) for n, x, y in placed["a"]) == {"top": (200, 500), "bottom": (200, 0)}
    # aacute has no rule of its own — it inherits a's anchors (identity component).
    assert dict((n, (x, y)) for n, x, y in placed["aacute"]) == {"top": (200, 500), "bottom": (200, 0)}


def test_component_transform_applied():
    f = _font()
    # move a's component and check the inherited anchor is offset with it.
    a2 = f["aacute"]
    for c in list(a2.components):
        a2.removeComponent(c)
    p = a2.getPen(); p.addComponent("a", (1, 0, 0, 1, 25, 60))
    doc = _rules("a = top (box.center 500)\n!propagate = composites")
    placed = compute_document(f, doc)
    assert dict((n, (x, y)) for n, x, y in placed["aacute"]) == {"top": (225, 560)}


def test_mark_anchors_not_propagated():
    f = _font()
    doc = _rules("a = top (box.center 500)\n"
                 "acutecomb = _top (box.center 500), top (box.center 600)\n"
                 "!propagate = composites")
    placed = compute_document(f, doc)
    names = {n for n, _, _ in placed["aacute"]}
    assert "_top" not in names                      # mark-side anchor never inherited
    assert "top" in names


def test_later_component_overrides_by_name():
    f = _font()
    # acutecomb also carries a `top`; being the later component, its (offset) top wins.
    doc = _rules("a = top (box.center 500)\n"
                 "acutecomb = top (box.center 550)\n"
                 "!propagate = composites")
    placed = compute_document(f, doc)
    top = dict((n, (x, y)) for n, x, y in placed["aacute"])["top"]
    # acutecomb top: box.center of 0..100 = 50, y=550; component offset (150,100)
    assert top == (200, 650)


def test_replace_rule_wipes_seed():
    f = _font()
    doc = _rules("a = top (box.center 500), bottom (box.center 0)\n"
                 "aacute = middle (box.center 250)\n"
                 "!propagate = composites")
    placed = compute_document(f, doc)
    assert {n for n, _, _ in placed["aacute"]} == {"middle"}   # `=` dropped the inherited anchors


def test_add_extends_seed():
    f = _font()
    doc = _rules("a = top (box.center 500)\n"
                 "aacute += extra (box.center 250)\n"
                 "!propagate = composites")
    placed = compute_document(f, doc)
    assert {n for n, _, _ in placed["aacute"]} == {"top", "extra"}


def test_remove_drops_inherited():
    f = _font()
    doc = _rules("a = top (box.center 500), bottom (box.center 0)\n"
                 "aacute -= top\n"
                 "!propagate = composites")
    placed = compute_document(f, doc)
    assert {n for n, _, _ in placed["aacute"]} == {"bottom"}


def test_composites_mode_skips_mixed_glyph():
    f = _font()
    # give aacute an own contour → it's no longer a *pure* composite.
    _rect(f["aacute"], 400, 0, 420, 500)
    doc = _rules("a = top (box.center 500)\n!propagate = composites")
    assert "aacute" not in compute_document(f, doc)     # not covered by `composites`
    doc_all = _rules("a = top (box.center 500)\n!propagate = all")
    assert "top" in {n for n, _, _ in compute_document(f, doc_all)["aacute"]}


def test_fallback_to_existing_font_anchors():
    f = _font()
    f["a"].appendAnchor("top", (111, 222))          # pre-existing, no rule places it
    doc = _rules("!propagate = composites")          # nothing computed for `a`
    placed = compute_document(f, doc)
    assert dict((n, (x, y)) for n, x, y in placed["aacute"]) == {"top": (111, 222)}


def test_computed_anchors_win_over_existing():
    f = _font()
    f["a"].appendAnchor("top", (111, 222))          # stale existing anchor
    doc = _rules("a = top (box.center 500)\n!propagate = composites")
    placed = compute_document(f, doc)
    assert dict((n, (x, y)) for n, x, y in placed["aacute"]) == {"top": (200, 500)}


def test_default_is_no_propagation():
    f = _font()
    doc = _rules("a = top (box.center 500)")          # no !propagate
    placed = compute_document(f, doc)
    assert "aacute" not in placed
    assert propagate_seed(f, f["aacute"], doc, {}) == []


def test_component_cycle_guard():
    # A true on-disk component cycle can't be constructed via defcon (it recurses
    # at build time), so exercise the guard directly: resolving a glyph already on
    # the resolution stack returns {} instead of recursing forever.
    from anchorsfactory.apply import _effective_anchors
    f = _font()
    doc = _rules("a = top (box.center 500)")
    assert _effective_anchors(f, "a", doc, {}, ("a",), round_coords=True) == {}


def test_apply_document_writes_inherited_anchors():
    f = _font()
    doc = _rules("a = top (box.center 500)\n!propagate = composites")
    apply_document(f, doc)
    got = {a.name: (a.x, a.y) for a in f["aacute"].anchors}
    assert got == {"top": (200, 500)}


def test_directive_parses():
    assert _rules("!propagate = all").propagate == "all"
    assert _rules("!propagate = composites").propagate == "composites"
    assert _rules("a = top (box.center 0)").propagate == "none"       # default


@pytest.mark.parametrize("bad", [
    "!propagate = sometimes",        # unknown value
    "!propagate += all",             # only '=' supported
])
def test_directive_rejects_bad(bad):
    with pytest.raises(DSLError):
        _rules(bad)


def test_propagate_composes_through_extends():
    base = _rules("a = top (box.center 500)\n!propagate = composites")
    child = _rules("a += bottom (box.center 0)")       # no !propagate of its own
    merged = _merge(base, child)
    assert merged.propagate == "composites"            # inherited from base
    # child overriding back to none:
    child_off = _rules("!propagate = none")
    assert _merge(base, child_off).propagate == "composites"   # none = default, base wins
