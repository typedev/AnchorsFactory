"""Query API for interactive editors (issue #3, Parts 2/3): selector↔glyph
matching, per-glyph rule lookup, the accumulation trace, and explain_document."""

import pytest

from anchorsfactory import (
    accumulate, explain_glyph, explain_document, glyphs_for_selector,
    parse_dsl, parse_selectors, rules_for_glyph, selector_matches,
)
from anchorsfactory.model import GlyphName, Glob, Unicode


# --- reverse direction: a rule's selector -> the glyphs it hits ------------- #
def test_parse_selectors_bare_and_full_line_and_list():
    assert parse_selectors("A") == [GlyphName("A")]
    assert parse_selectors("*.sc = @x") == [Glob("*.sc")]
    assert parse_selectors("C, O, U+0410 += top (box.center 0)") == [
        GlyphName("C"), GlyphName("O"), Unicode(0x0410)]


def test_glyphs_for_selector_agrees_with_accumulate_membership():
    doc = parse_dsl(["{Lu} = top (box.center capHeight)"])
    glyphs = [("A", [0x41]), ("a", [0x61]), ("Ge", [0x0413])]
    sel = doc.rules[0].selector
    hit = glyphs_for_selector(sel, glyphs)
    # a selector matches a glyph iff accumulate places something on it
    for name, uni in glyphs:
        assert (name in hit) == bool(accumulate(doc, name, uni))
    assert hit == ["A", "Ge"]


# --- forward direction: a glyph -> the rules that touch it ------------------ #
def test_rules_for_glyph_in_document_order_with_source():
    doc = parse_dsl([
        "a = top (box.center 500)",
        "e = top (box.center 500)",
        "a += bottom (box.center 0)",
    ])
    rules = rules_for_glyph(doc, "a", [0x61])
    assert [(r.op.value, r.source.line) for r in rules] == [("=", 1), ("+=", 3)]


# --- accumulation trace ----------------------------------------------------- #
def test_explain_glyph_final_equals_accumulate():
    doc = parse_dsl([
        "a = top (box.center 500)",
        "a += bottom (box.center 0)",
        "a -= top",
    ])
    ex = explain_glyph(doc, "a", [0x61])
    assert [s.name for s in ex.final] == [s.name for s in accumulate(doc, "a", [0x61])]
    assert [s.name for s in ex.final] == ["bottom"]
    # one step per matching rule, each snapshotting the accumulator after it ran
    assert [(t.rule.op.value, [s.name for s in t.accumulator]) for t in ex.steps] == [
        ("=", ["top"]), ("+=", ["top", "bottom"]), ("-=", ["bottom"])]


def test_selector_matches_primitives():
    assert selector_matches(GlyphName("A"), "A", [])
    assert not selector_matches(GlyphName("A"), "B", [])
    assert selector_matches(Unicode(0x41), "anything", [0x41])
    assert selector_matches(Glob("*.sc"), "a.sc", [])


# --- explain_document: placement + provenance in one call ------------------- #
class _Anchor:
    def __init__(self, name, x, y): self.name, self.x, self.y = name, x, y


class _Glyph:
    def __init__(self, name, width, unicodes=()):
        self.name, self.width, self.unicodes = name, width, list(unicodes)
        self.bounds = (0.0, 0.0, float(width), 0.0)
        self.anchors = []


class _Font:
    def __init__(self, glyphs):
        self._g = {g.name: g for g in glyphs}
        self.glyphOrder = [g.name for g in glyphs]
        self.info = type("I", (), {"unitsPerEm": 1000, "italicAngle": 0})()

    def __iter__(self): return iter(self._g.values())
    def __contains__(self, n): return n in self._g
    def __getitem__(self, n): return self._g[n]


def test_explain_document_carries_source_and_refs():
    from anchorsfactory.model import AnchorSpec, XAbs, YAbs, AnchorRef
    doc = parse_dsl([
        "a = top (100 700)",
        "a += bottom (%top 0)",     # derived: references the `top` anchor
    ])
    font = _Font([_Glyph("a", 500, [0x61])])
    result = explain_document(font, doc)
    rows = {pa.name: pa for pa in result["a"]}
    assert rows["top"].source.line == 1 and rows["top"].source.origin is None
    assert rows["bottom"].source.line == 2
    assert rows["bottom"].derived_from == ("top",)   # %top reference recorded
    assert rows["top"].derived_from is None
