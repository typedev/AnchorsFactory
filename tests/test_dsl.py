"""Tests for the new-syntax parser (dsl.py) and the accumulation model."""

import pytest

from anchorsfactory.dsl import parse_dsl, DSLError
from anchorsfactory.apply import accumulate
from anchorsfactory.model import (
    Frame, HAlign, VEdge, Run, Frac,
    X, XAbs, Y, YAbs, FontMetric, YSum, AnchorSpec, LabelRef,
    GlyphName, Unicode, UnicodeRange, Glob, Category, Op,
)


def _one(doc, label="@x"):
    return doc.labels[label][0]


def test_anchor_paren_form():
    doc = parse_dsl(["@x = top (box.center $H)"])
    assert _one(doc) == AnchorSpec("top", X(Frame.BOX, HAlign.CENTER), Y("H", VEdge.TOP))


@pytest.mark.parametrize("tok, x", [
    ("width.center", X(Frame.ADVANCE, HAlign.CENTER)),
    ("box.left", X(Frame.BOX, HAlign.LEFT)),
    ("outline.right", X(Frame.OUTLINE, HAlign.RIGHT)),
    ("outline.first.center", X(Frame.OUTLINE, HAlign.CENTER, run=Run.FIRST)),
    ("outline.last.center", X(Frame.OUTLINE, HAlign.CENTER, run=Run.LAST)),
    ("outline.2.center", X(Frame.OUTLINE, HAlign.CENTER, run=2)),
    ("outline.center@top", X(Frame.OUTLINE, HAlign.CENTER, at=VEdge.TOP)),
    ("250", XAbs(250)),
])
def test_x_tokens(tok, x):
    assert _one(parse_dsl([f"@x = a ({tok} 0)"])).x == x


@pytest.mark.parametrize("tok, x", [
    ("outline.center@xHeight", X(Frame.OUTLINE, HAlign.CENTER, at=FontMetric("xHeight"))),
    ("outline.center@baseline", X(Frame.OUTLINE, HAlign.CENTER, at=FontMetric("baseline"))),
    ("outline.center@120", X(Frame.OUTLINE, HAlign.CENTER, at=YAbs(120))),
])
def test_x_sample_at_height(tok, x):
    spec = _one(parse_dsl([f"@x = a ({tok} 0)"]))
    assert spec.x == x
    assert str(spec.x) == tok          # round-trips


def test_y_sum():
    spec = _one(parse_dsl(["@x = a (box.center capHeight*1/2+xHeight*1/2)"]))
    assert spec.y == YSum((FontMetric("capHeight", Frac(1, 2)), FontMetric("xHeight", Frac(1, 2))))
    assert str(spec.y) == "capHeight*1/2+xHeight*1/2"


@pytest.mark.parametrize("tok, y", [
    ("$H", Y("H", VEdge.TOP)),
    ("$H.bottom", Y("H", VEdge.BOTTOM)),
    ("$H.middle", Y("H", VEdge.MIDDLE)),
    ("$H*5/6", Y("H", Frac(5, 6))),
    ("$bar.alt", Y("bar.alt", VEdge.TOP)),   # dotted glyph name, not an edge
    ("575", YAbs(575)),
    ("xHeight", FontMetric("xHeight")),
    ("descender", FontMetric("descender")),
    ("capHeight*2/3", FontMetric("capHeight", Frac(2, 3))),
    ("baseline", FontMetric("baseline")),
])
def test_y_tokens(tok, y):
    assert _one(parse_dsl([f"@x = a (box.center {tok})"])).y == y


@pytest.mark.parametrize("tok, sel", [
    ("A", GlyphName("A")),
    ("U+0413", Unicode(0x0413)),
    ("U+0410..U+044F", UnicodeRange(0x0410, 0x044F)),
    ("*.sc", Glob("*.sc")),
    ("{Lu}", Category("Lu")),
])
def test_selectors(tok, sel):
    doc = parse_dsl(["@a = x (box.center 0)", f"{tok} = @a"])
    assert doc.rules[0][0] == sel


# --- comma-separated selector list (one rule per selector) ----------------- #
def test_selector_list_expands_to_one_rule_each():
    doc = parse_dsl(["C, O, S += top (box.center $H), bottom (box.center 0)"])
    sels = [r[0] for r in doc.rules]
    assert sels == [GlyphName("C"), GlyphName("O"), GlyphName("S")]
    # every listed glyph gets the same op and items
    for _, op, items in doc.rules:
        assert op is Op.ADD
        assert [s.name for s in items] == ["top", "bottom"]
    # and each resolves to those anchors
    for g in ("C", "O", "S"):
        assert [s.name for s in accumulate(doc, g, [])] == ["top", "bottom"]


def test_selector_list_mixes_selector_kinds():
    doc = parse_dsl(["@a = x (box.center 0)", "A, U+0421, *.sc = @a"])
    assert [r[0] for r in doc.rules] == [GlyphName("A"), Unicode(0x0421), Glob("*.sc")]


def test_selector_list_ignores_blank_and_trailing_commas():
    doc = parse_dsl(["@a = x (box.center 0)", "C , , O, = @a"])
    assert [r[0] for r in doc.rules] == [GlyphName("C"), GlyphName("O")]


def test_empty_left_hand_side_errors():
    with pytest.raises(DSLError):
        parse_dsl([" , = x (box.center 0)"])


def test_labels_mix_and_directives():
    doc = parse_dsl([
        "@bot = bottom (box.center 0)",
        "!suffixes = .alt, sc",
        "!shiftx = -15",
        "L = @bot, top (box.left $H)",
    ])
    assert doc.suffixes == ["", ".alt", ".sc"]
    assert doc.shift_x == -15
    sel, op, items = doc.rules[0]
    assert sel == GlyphName("L") and op is Op.REPLACE
    assert items == [LabelRef("@bot"), AnchorSpec("top", X(Frame.BOX, HAlign.LEFT), Y("H"))]
    assert [s.name for s in accumulate(doc, "L", [])] == ["bottom", "top"]   # resolved


def test_label_override_is_late_bound():
    """Redefining a label changes rules written before the redefinition too."""
    doc = parse_dsl([
        "@ = top (box.center $H)",
        "A = @",
        "@ = bottom (box.center 0)",          # override after use
    ])
    assert [s.name for s in accumulate(doc, "A", [])] == ["bottom"]


def test_undefined_label_errors_at_apply():
    doc = parse_dsl(["A = @nope"])            # not validated at parse (late binding)
    with pytest.raises(ValueError):
        accumulate(doc, "A", [])


def test_remove_operator():
    doc = parse_dsl([
        "@ = top (box.center $H), bottom (box.center 0)",
        "A = @, ogonek (outline.right 0)",
        "A -= ogonek",
    ])
    assert [s.name for s in accumulate(doc, "A", [])] == ["top", "bottom"]


def test_remove_via_label():
    doc = parse_dsl([
        "@x = a (box.center 0), b (box.center 0)",
        "G = @x, c (box.center 0)",
        "G -= @x",                            # drop everything @x contributed
    ])
    assert [s.name for s in accumulate(doc, "G", [])] == ["c"]


def test_canonical_roundtrip():
    """Rendering a parsed anchor reproduces its canonical DSL token."""
    spec = _one(parse_dsl(["@x = bar (outline.first.center $h*5/6)"]))
    assert str(spec) == "bar (outline.first.center $h*5/6)"


# --- accumulation model: = replaces, += accumulates ------------------------ #
def _names(specs):
    return [s.name for s in specs]


def test_range_default_then_add_override():
    doc = parse_dsl([
        "@ = top (box.center $H)",
        "@desc = desc (outline.right 0)",
        "U+0410..U+044F = @",
        "U+0413 += @desc",
    ])
    assert _names(accumulate(doc, "ge", [0x0413])) == ["top", "desc"]   # Г: default + add
    assert _names(accumulate(doc, "a", [0x0410])) == ["top"]            # plain range member
    assert accumulate(doc, "x", [0x0041]) == []                        # outside range


def test_replace_is_a_hard_reset():
    doc = parse_dsl([
        "@ = top (box.center $H)",
        "U+0410..U+044F = @",
        "U+0413 = bar (width.center 0)",     # hard reset wipes the @ default
    ])
    assert _names(accumulate(doc, "ge", [0x0413])) == ["bar"]


@pytest.mark.parametrize("line", [
    "A = top box.center $H",       # missing parens
    "A = top (box.bogus $H)",      # bad align
    "A = top (box.center 0",       # unbalanced paren
    "noequals",                    # missing operator
    "!unknown = 1",                # unknown directive
])
def test_errors(line):
    with pytest.raises(DSLError):
        parse_dsl([line])
