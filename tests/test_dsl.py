"""Tests for the new-syntax parser (dsl.py) and the accumulation model."""

import pytest

from anchorsfactory.dsl import parse_dsl, DSLError
from anchorsfactory.apply import accumulate
from anchorsfactory.model import (
    Frame, Axis, HAlign, VEdge, Run, Frac,
    X, Pos, Centroid, Abs, XAbs, Y, YAbs, FontMetric, Sum, YSum, Neg, AnchorSpec, LabelRef, VarRef,
    GlyphName, Unicode, UnicodeRange, Glob, Category, Op,
    resolve_suffixes, SuffixSpec,
)


def _one(doc, label="@x"):
    return doc.labels[label][0]


def test_anchor_paren_form():
    doc = parse_dsl(["@x = top (box.center $H)"])
    assert _one(doc) == AnchorSpec("top", X(Frame.BOX, HAlign.CENTER), Y("H", VEdge.TOP))


def test_derived_anchor_ref_parses():
    from anchorsfactory.model import AnchorRef
    assert _one(parse_dsl(["@x = a (%top 0)"])).x == AnchorRef("top")       # X slot
    assert _one(parse_dsl(["@x = a (0 %top)"])).y == AnchorRef("top")       # Y slot (polymorphic)
    spec = _one(parse_dsl(["@x = a (%top-25 0)"]))                          # %ref in a sum
    assert spec.x == Sum((AnchorRef("top"), Neg(Abs(25))))
    # inside an @ sample line (a height that is another anchor's y)
    assert _one(parse_dsl(["@x = a (outline.center@%top 0)"])).x == \
        X(Frame.OUTLINE, HAlign.CENTER, at=AnchorRef("top"))


@pytest.mark.parametrize("bad", ["@x = a (%bad!name 0)", "@x = a (% 0)"])
def test_bad_anchor_ref_rejected(bad):
    with pytest.raises(DSLError):
        parse_dsl([bad])


@pytest.mark.parametrize("tok, x", [
    ("comp1.box.right", X(Frame.BOX, HAlign.RIGHT, component=1)),
    ("comp2.outline.center@top", X(Frame.OUTLINE, HAlign.CENTER, at=VEdge.TOP, component=2)),
    ("complast.outline.left", X(Frame.OUTLINE, HAlign.LEFT, component=-1)),
])
def test_component_frame_parses(tok, x):
    spec = _one(parse_dsl([f"@x = a ({tok} 0)"]))
    assert spec.x == x
    assert str(spec.x) == tok                          # round-trips


def test_component_centroid_parses():
    assert _one(parse_dsl(["@x = a (comp2.outline.centroid 0)"])).x == Centroid(component=2)


@pytest.mark.parametrize("bad", ["@x = a (comp1.width.center 0)", "@x = a (comp0.box.left 0)"])
def test_bad_component_frame_rejected(bad):
    with pytest.raises(DSLError):
        parse_dsl([bad])


def test_edge_offset_at_parses():
    from anchorsfactory.model import EdgeOffset
    assert _one(parse_dsl(["@x = a (outline.center@top-10 0)"])).x == \
        X(Frame.OUTLINE, HAlign.CENTER, at=EdgeOffset(VEdge.TOP, -10))
    assert _one(parse_dsl(["@x = a (outline.center@bottom+8 0)"])).x == \
        X(Frame.OUTLINE, HAlign.CENTER, at=EdgeOffset(VEdge.BOTTOM, 8))
    # Y axis: an @ column edge ± offset
    assert _one(parse_dsl(["@x = a (0 outline.middle@right+5)"])).y == \
        Pos(Frame.OUTLINE, VEdge.MIDDLE, at=EdgeOffset(HAlign.RIGHT, 5), axis=Axis.Y)
    # bare @top is unchanged (exact edge, not an EdgeOffset)
    assert _one(parse_dsl(["@x = a (outline.center@top 0)"])).x.at is VEdge.TOP


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


# --- unified axes / fractions / centroid (new surface forms) --------------- #
@pytest.mark.parametrize("xtok, ytok, x, y", [
    # Y-side frame positions: box.top subsumes the old "$self" need
    ("box.center", "box.top", X(Frame.BOX, HAlign.CENTER),
     Pos(Frame.BOX, VEdge.TOP, axis=Axis.Y)),
    ("box.center", "box.middle", X(Frame.BOX, HAlign.CENTER),
     Pos(Frame.BOX, VEdge.MIDDLE, axis=Axis.Y)),
    ("box.center", "outline.first.middle", X(Frame.BOX, HAlign.CENTER),
     Pos(Frame.OUTLINE, VEdge.MIDDLE, run=Run.FIRST, axis=Axis.Y)),
    # fractional positions on either axis (the '*' fraction, unified with cap*2/3)
    ("width*1/3", "capHeight", Pos(Frame.ADVANCE, Frac(1, 3)), FontMetric("capHeight")),
    ("box*2/3", "box*1/4", Pos(Frame.BOX, Frac(2, 3)),
     Pos(Frame.BOX, Frac(1, 4), axis=Axis.Y)),
    # centroid is polymorphic — legal in both slots
    ("outline.centroid", "outline.centroid", Centroid(), Centroid()),
    # @ on Y is a column: an own-side edge or a fixed X value
    ("box.center", "outline.middle@right", X(Frame.BOX, HAlign.CENTER),
     Pos(Frame.OUTLINE, VEdge.MIDDLE, at=HAlign.RIGHT, axis=Axis.Y)),
    ("box.center", "outline.middle@40", X(Frame.BOX, HAlign.CENTER),
     Pos(Frame.OUTLINE, VEdge.MIDDLE, at=XAbs(40), axis=Axis.Y)),
])
def test_unified_tokens(xtok, ytok, x, y):
    spec = _one(parse_dsl([f"@x = a ({xtok} {ytok})"]))
    assert spec.x == x and spec.y == y
    # the IR doubles as the serializer → tokens round-trip
    assert str(spec.x) == xtok and str(spec.y) == ytok


@pytest.mark.parametrize("line", [
    "@x = a (outline.centroid@top 0)",        # centroid takes no @
    "@x = a (box.center capHeight@right)",     # @ only on outline
    "@x = a (box.top 0)",                      # Y-edge align in the X slot
    "@x = a (box.center box.center)",          # X-align in the Y slot
])
def test_unified_token_errors(line):
    with pytest.raises(DSLError):
        parse_dsl([line])


# --- arithmetic (Sum): base position + bias, subtraction via Neg ------------ #
@pytest.mark.parametrize("xtok, x", [
    ("outline.centroid-25", Sum((Centroid(), Neg(Abs(25))))),   # acute: nudge left
    ("outline.centroid+25", Sum((Centroid(), Abs(25)))),        # grave: nudge right
    ("box.center+20", Sum((Pos(Frame.BOX, HAlign.CENTER), Abs(20)))),
    ("outline.centroid+&shift", Sum((Centroid(), VarRef("&shift")))),
    # any term may be subtracted (a position too): box width at this height
    ("box.right-box.left", Sum((Pos(Frame.BOX, HAlign.RIGHT),
                                Neg(Pos(Frame.BOX, HAlign.LEFT))))),
])
def test_x_sum_tokens(xtok, x):
    spec = _one(parse_dsl([f"@x = a ({xtok} capHeight)"]))
    assert spec.x == x
    assert str(spec.x) == xtok          # subtracted term renders with '-', round-trips


def test_y_subtraction_is_allowed():
    # 2b: '-' now works on Y too (a metric minus a metric / a constant)
    spec = _one(parse_dsl(["@x = a (box.center ascender-descender)"]))
    assert spec.y == Sum((FontMetric("ascender"), Neg(FontMetric("descender"))))
    assert str(spec.y) == "ascender-descender"
    assert _one(parse_dsl(["@x = a (box.center capHeight-100)"])).y == \
        Sum((FontMetric("capHeight"), Neg(Abs(100))))


def test_y_sum_allows_frame_term():
    # the same Sum works on Y (a frame height plus an offset)
    spec = _one(parse_dsl(["@x = a (box.center box.top+50)"]))
    assert spec.y == Sum((Pos(Frame.BOX, VEdge.TOP, axis=Axis.Y), Abs(50)))
    assert str(spec.y) == "box.top+50"


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


# --- !suffixes operators / all / deny / none ------------------------------- #
def _sfx(*lines):
    return resolve_suffixes(parse_dsl(list(lines)).suffix_ops)


def test_suffixes_replace_then_add_then_remove():
    assert _sfx("!suffixes = .sc, .alt").items == ("", ".sc", ".alt")
    # += builds on the prior list; bare names get a leading dot
    assert _sfx("!suffixes = .sc", "!suffixes += alt").items == ("", ".sc", ".alt")
    # -= drops a suffix; "" is never removable
    assert _sfx("!suffixes = .sc, .alt", "!suffixes -= .sc").items == ("", ".alt")


def test_suffixes_replace_resets_prior():
    # a later `=` discards whatever came before (within one document)
    assert _sfx("!suffixes += .sc", "!suffixes = .alt").items == ("", ".alt")


def test_suffixes_all_and_deny():
    s = _sfx("!suffixes = all")
    assert s == SuffixSpec(all=True, items=("",), deny=())
    s = _sfx("!suffixes = all except .numr, dnom")
    assert s.all and s.deny == (".numr", ".dnom")
    # in all-mode, -= extends deny and += re-includes (shrinks deny)
    assert _sfx("!suffixes = all", "!suffixes -= .numr").deny == (".numr",)
    assert _sfx("!suffixes = all except .numr, .dnom",
                "!suffixes += .numr").deny == (".dnom",)


def test_suffixes_none_resets_to_base_only():
    assert _sfx("!suffixes = .sc", "!suffixes = none").items == ("",)


@pytest.mark.parametrize("line", [
    "!suffixes += all",                  # all needs '='
    "!suffixes = all foo .x",            # malformed all-clause
    "!suffixes -= none",                 # none needs '='
    "!suffixes =",                       # empty list
])
def test_suffixes_errors(line):
    with pytest.raises(DSLError):
        parse_dsl([line])


def test_labels_mix_and_directives():
    doc = parse_dsl([
        "@bot = bottom (box.center 0)",
        "!suffixes = .alt, sc",
        "!shiftx = -15",
        "L = @bot, top (box.left $H)",
    ])
    assert resolve_suffixes(doc.suffix_ops).items == ("", ".alt", ".sc")
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
