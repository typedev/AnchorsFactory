"""Conditional blocks (`!if`/`!elif`/`!else`/`!endif`), evaluated per master —
in rule files and in GlyphConstruction text."""

import os
import textwrap

import pytest

from anchorsfactory import (
    ConditionError, DSLError, RuleContext, active_lines, blank_inactive,
    build_composites, compute_document, contexts_from_designspace,
    inactive_lines, load_document, parse_constructions, parse_dsl,
    parse_location, structure_diff, validate_document,
)
from anchorsfactory import vocabulary as V
from anchorsfactory.conditions import parse_condition


def doc_of(text):
    return parse_dsl(textwrap.dedent(text).strip("\n").splitlines())


def anchors(doc, name="L"):
    """{anchor: (x, y)} of the abs-coordinate anchors a flat doc gives *name*."""
    from anchorsfactory import accumulate
    return {s.name: (str(s.x), str(s.y)) for s in accumulate(doc, name, [])}


UPRIGHT = RuleContext(xvalues={"ital": 0})
ITALIC = RuleContext(xvalues={"ital": 1})

RULES = """\
L = dot (100 200)
!if ital.xvalue == 1
L += dot (80 200)
!endif
"""


# --------------------------------------------------------------------------- #
#  Parsing
# --------------------------------------------------------------------------- #

def test_unresolved_document_holds_only_unconditional_lines():
    doc = doc_of(RULES)
    assert doc.has_conditionals
    assert [r.source.line for r in doc.rules] == [1]


def test_resolve_picks_the_branch_and_keeps_order():
    doc = doc_of(RULES)
    assert anchors(doc.resolve(UPRIGHT)) == {"dot": ("100", "200")}
    # the branch comes after the base rule, so its `+=` wins the dedup later;
    # here both specs survive accumulation, the active one last
    flat = doc.resolve(ITALIC)
    assert [r.source.line for r in flat.rules] == [1, 3]
    assert not flat.has_conditionals


def test_elif_else_and_nesting():
    doc = doc_of("""
        !if wght.xvalue >= 600
          !if ital.xvalue == 1
            A = a (1 0)
          !else
            A = a (2 0)
          !endif
        !elif wght.xvalue > 300
        A = a (3 0)
        !else
        A = a (4 0)
        !endif
    """)
    def x(**loc):
        return anchors(doc.resolve(RuleContext(xvalues=loc)), "A")["a"][0]
    assert x(wght=700, ital=1) == "1"
    assert x(wght=700, ital=0) == "2"
    assert x(wght=400, ital=0) == "3"
    assert x(wght=100, ital=0) == "4"


def test_short_circuit_elif_after_taken_branch_is_not_evaluated():
    doc = doc_of("""
        !if ital.xvalue == 1
        A = a (1 0)
        !elif wght.xvalue > 1
        A = a (2 0)
        !endif
    """)
    # wght is missing, but the !elif is never reached
    assert anchors(doc.resolve(ITALIC), "A") == {"a": ("1", "0")}
    with pytest.raises(ConditionError, match=r"line 3: no xvalue for axis 'wght'"):
        doc.resolve(UPRIGHT)


def test_variables_labels_and_directives_in_blocks():
    doc = doc_of("""
        &x = 100
        @tops = top (&x 500)
        !if ital.xvalue == 1
        &x = 80
        !shiftx = -5
        !endif
        A = @tops
    """)
    up, it = doc.resolve(UPRIGHT), doc.resolve(ITALIC)
    assert str(up.variables["&x"]) == "100" and up.shift_x == 0
    assert str(it.variables["&x"]) == "80" and it.shift_x == -5


def test_rule_lines_are_the_original_file_lines():
    doc = doc_of("""
        A = a (1 0)
        !if ital.xvalue == 1
        # a comment

        B = b (1 0)
        !else
        C = c (1 0)
        !endif
        D = d (1 0)
    """)
    assert [r.source.line for r in doc.resolve(ITALIC).rules] == [1, 5, 9]
    assert [r.source.line for r in doc.resolve(UPRIGHT).rules] == [1, 7, 9]


@pytest.mark.parametrize("text, msg", [
    ("!if ital.xvalue == 1\nA = a (1 0)\n", r"line 1: !if without !endif"),
    ("A = a (1 0)\n!endif\n", r"line 2: !endif without !if"),
    ("!elif ital.xvalue == 1\n", r"line 1: !elif without !if"),
    ("!if ital.xvalue == 1\n!else\n!else\n!endif\n", r"line 3: !else after !else"),
    ("!if ital.xvalue == 1\n!else\n!elif wght.xvalue > 1\n!endif\n", r"line 3: !elif after !else"),
    ("!if\n!endif\n", r"line 1: !if needs a condition"),
    ("!if ital.xvalue == 1\n!else wght\n!endif\n", r"line 2: !else takes no condition"),
    ("!if ital.xvalue == 1; A = a (1 0)\n!endif\n", r"line 1: !if must be alone"),
    ("A = a (1 0); !if ital.xvalue == 1\n!endif\n", r"line 1: !if must be alone"),
    ("!if ital.xvalue == 1\n!extends base\n!endif\n", r"line 2: !extends cannot be conditional"),
    ("!if ital.foo == 1\n!endif\n", r"line 1: .*\.xvalue or \.uservalue"),
    ("!if ital.xvalue\n!endif\n", r"line 1: .*not a condition"),
    ("!if styleName > \"A\"\n!endif\n", r"line 1: '>' compares numbers"),
    ("!if ital.xvalue == \"1\"\n!endif\n", r"line 1: cannot compare number"),
    ("!if ital.xvalue in 1\n!endif\n", r"line 1: 'in' tests a substring"),
    ("!if (ital.xvalue == 1\n!endif\n", r"line 1: missing '\)'"),
    ("!if styleName == \"Bold\n!endif\n", r"line 1: unterminated string"),
    ("!if Bold in styleName\n!endif\n", r"line 1: unknown name 'Bold'"),
])
def test_block_and_condition_errors(text, msg):
    with pytest.raises(DSLError, match=msg):
        parse_dsl(text.splitlines())


def test_error_in_an_inactive_branch_is_still_reported_at_parse_time():
    with pytest.raises(DSLError, match=r"line 3: "):
        doc_of("""
            !if ital.xvalue == 1
            A = a (1 0)
            B = b (box.nowhere 0)
            !endif
        """)


def test_unconditional_document_is_unchanged():
    doc = doc_of("A = a (1 0)")
    assert not doc.has_conditionals and doc.conditional is None
    assert doc.resolve(ITALIC) is doc


# --------------------------------------------------------------------------- #
#  Conditions and contexts
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("cond, expected", [
    ("ital.xvalue == 1", True),
    ("ital.xvalue != 1", False),
    ("wght.uservalue >= 500 and wght.uservalue < 701", True),
    ("not ital.xvalue == 1 or wght.xvalue > 50", True),
    ("not (ital.xvalue == 1 or wght.xvalue > 50)", False),
    ('"Bold" in styleName', True),
    ('"Bold" not in styleName', False),
    ('styleName == "Bold Italic"', True),
    ('styleName != "Bold"', True),
    ("ital.xvalue == 1.0 and -1 < 0", True),
])
def test_condition_semantics(cond, expected):
    from anchorsfactory.conditions import evaluate
    ctx = RuleContext(style_name="Bold Italic", xvalues={"ital": 1, "wght": 75},
                      uservalues={"wght": 700})
    assert evaluate(parse_condition(cond), ctx) is expected


def test_and_binds_tighter_than_or():
    from anchorsfactory.conditions import evaluate
    ctx = RuleContext(xvalues={"a": 1, "b": 0, "c": 0})
    # a or (b and c) -> True; (a or b) and c would be False
    assert evaluate(parse_condition("a.xvalue == 1 or b.xvalue == 1 and c.xvalue == 1"), ctx)


def test_missing_style_name_is_empty_not_an_error():
    doc = doc_of('!if "Bold" in styleName\nA = a (1 0)\n!endif\n')
    assert doc.resolve(RuleContext()).rules == []


def test_axis_tag_and_name_are_interchangeable():
    ctx = RuleContext(xvalues={"weight": 700}, axis_aliases={"wght": "weight"})
    for cond in ("wght.xvalue == 700", "weight.xvalue == 700"):
        doc = parse_dsl([f"!if {cond}", "A = a (1 0)", "!endif"])
        assert len(doc.resolve(ctx).rules) == 1


def test_unknown_axis_is_an_error_even_in_an_unreached_branch():
    ctx = RuleContext(xvalues={"weight": 0}, axis_aliases={"wght": "weight"},
                      axes=frozenset({"wght", "weight"}))
    doc = doc_of("""
        !if wght.xvalue == 0
        A = a (1 0)
        !elif wdht.xvalue == 1
        A = a (2 0)
        !endif
    """)
    with pytest.raises(ConditionError, match=r"line 3: unknown axis 'wdht'"):
        doc.resolve(ctx)


def test_parse_location():
    assert parse_location(["ital.xvalue=1", "wght.uservalue = 700"]) == (
        {"ital": 1.0}, {"wght": 700.0})
    with pytest.raises(ValueError):
        parse_location(["ital=1"])


DESIGNSPACE = """\
<?xml version='1.0' encoding='UTF-8'?>
<designspace format="5.0">
  <axes>
    <axis tag="wght" name="weight" minimum="300" maximum="700" default="300">
      <map input="300" output="0"/>
      <map input="700" output="100"/>
    </axis>
    <axis tag="ital" name="italic" minimum="0" maximum="1" default="0"/>
  </axes>
  <sources>
    <source filename="Light.ufo" stylename="Light">
      <location><dimension name="weight" xvalue="0"/></location>
    </source>
    <source filename="BoldItalic.ufo" stylename="Bold">
      <location><dimension name="weight" xvalue="100"/><dimension name="italic" xvalue="1"/></location>
    </source>
    <source filename="Light.ufo" layer="sparse">
      <location><dimension name="weight" xvalue="50"/></location>
    </source>
  </sources>
</designspace>
"""


def test_contexts_from_designspace_maps_design_to_user(tmp_path):
    path = tmp_path / "fam.designspace"
    path.write_text(DESIGNSPACE)
    ctxs = contexts_from_designspace(str(path))
    assert set(ctxs) == {str(tmp_path / "Light.ufo"), str(tmp_path / "BoldItalic.ufo")}
    bold = ctxs[str(tmp_path / "BoldItalic.ufo")]
    # the source stylename, as the designspace spells it (not "Bold Italic")
    assert bold.style_name == "Bold"
    assert bold.axis_value("wght", "xvalue") == 100
    assert bold.axis_value("weight", "uservalue") == 700
    light = ctxs[str(tmp_path / "Light.ufo")]
    assert light.axis_value("ital", "xvalue") == 0        # default filled in

    doc = doc_of("""
        !if wght.xvalue == 100
        A = a (1 0)
        !endif
        !if weight.uservalue == 700
        B = b (1 0)
        !endif
        !if wght.uservalue == 100
        C = c (1 0)
        !endif
    """)
    names = [str(r.selector) for r in doc.resolve(bold).rules]
    assert names == ["A", "B"]          # 100 is a design value, 700 the user one
    assert doc.resolve(light).rules == []


# --------------------------------------------------------------------------- #
#  Editor helpers
# --------------------------------------------------------------------------- #

EDITOR_TEXT = """\
A = a (1 0)
!if ital.xvalue == 1
B = b (1 0)
  !if wght.xvalue > 5
  C = c (1 0)
  !endif
!else
D = d (1 0)
!endif
"""


def test_active_and_inactive_lines():
    ctx = RuleContext(xvalues={"ital": 0, "wght": 0})
    assert inactive_lines(EDITOR_TEXT, ctx) == {3, 4, 5, 6}
    assert active_lines(EDITOR_TEXT, ctx) == {1, 8, 10}       # 10: trailing ""
    ctx = RuleContext(xvalues={"ital": 1, "wght": 0})
    assert inactive_lines(EDITOR_TEXT, ctx) == {5, 8}
    assert active_lines(EDITOR_TEXT, ctx) == {1, 3, 10}


def test_active_lines_from_a_document():
    doc = parse_dsl(EDITOR_TEXT)
    ctx = RuleContext(xvalues={"ital": 0})
    assert inactive_lines(doc, ctx) == {3, 4, 5, 6}


def test_blank_inactive_keeps_line_count():
    out = blank_inactive(EDITOR_TEXT, RuleContext(xvalues={"ital": 0}))
    assert out.count("\n") == EDITOR_TEXT.count("\n")
    assert out.split("\n")[7] == "D = d (1 0)"
    assert "!if" not in out and "B = b" not in out


def test_vocabulary_lists_the_condition_words():
    assert V.CONDITIONAL_DIRECTIVES == ("!if", "!elif", "!else", "!endif")
    assert {"and", "or", "not", "in"} == set(V.CONDITION_KEYWORDS)
    assert V.AXIS_VALUE_KINDS == ("xvalue", "uservalue")
    assert "styleName" in V.CONDITION_FIELDS
    d = V.as_dict()
    assert d["conditionalDirectives"] == list(V.CONDITIONAL_DIRECTIVES)
    assert "not in" in d["conditionOperators"]


def test_validate_without_context_sees_every_branch():
    doc = doc_of("""
        !if ital.xvalue == 1
        @dot = dot (1 0)
        !else
        @dot = dot (2 0)
        !endif
        L = @dot
    """)
    assert validate_document(doc) == []
    assert validate_document(doc, ITALIC) == []
    broken = doc_of("""
        !if ital.xvalue == 1
        @dot = dot (1 0)
        !endif
        L = @dot
    """)
    assert validate_document(broken) == []
    assert any("undefined label @dot" in p for p in validate_document(broken, UPRIGHT))


# --------------------------------------------------------------------------- #
#  !extends: conditions in a base file
# --------------------------------------------------------------------------- #

def test_conditions_in_an_extended_base(tmp_path):
    (tmp_path / "base.anchors").write_text(
        "A = a (1 0)\n!if ital.xvalue == 1\nA += a (2 0)\n!endif\n")
    (tmp_path / "top.anchors").write_text(
        "!extends base\n!if ital.xvalue == 0\nB = b (1 0)\n!endif\n")
    doc = load_document(str(tmp_path / "top.anchors"))
    assert doc.has_conditionals
    it = doc.resolve(ITALIC)
    rows = [(str(r.selector), r.source.line, r.source.inherited,
             os.path.basename(r.source.origin)) for r in it.rules]
    assert rows == [("A", 1, True, "base.anchors"), ("A", 3, True, "base.anchors")]
    up = doc.resolve(UPRIGHT)
    rows = [(str(r.selector), r.source.line, r.source.inherited,
             os.path.basename(r.source.origin)) for r in up.rules]
    assert rows == [("A", 1, True, "base.anchors"), ("B", 3, False, "top.anchors")]


# --------------------------------------------------------------------------- #
#  Against a font, and GlyphConstruction
# --------------------------------------------------------------------------- #

fontParts = pytest.importorskip("fontParts.world")


def _font(style="Regular"):
    font = fontParts.NewFont()
    font.info.styleName = style
    font.info.unitsPerEm = 1000
    font.info.capHeight = 700
    for name, uni in (("L", 0x4C), ("g", 0x67), ("g.ss01", None), ("brevecomb", 0x306)):
        g = font.newGlyph(name)
        g.width = 500
        if uni:
            g.unicodes = [uni]
        pen = g.getPen()
        pen.moveTo((50, 0)); pen.lineTo((450, 0)); pen.lineTo((450, 700))
        pen.lineTo((50, 700)); pen.closePath()
    for base in ("g", "g.ss01"):
        font[base].appendAnchor("top", (250, 700))
    font["brevecomb"].appendAnchor("_top", (250, 700))
    return font


def test_compute_document_resolves_with_context_or_fontinfo():
    doc = doc_of("""
        L = dot (width*4/7 capHeight*1/2)
        !if ital.xvalue == 1
        L = dot (width*1/2 capHeight*1/2)
        !endif
        !if "Bold" in styleName
        L += bold (0 0)
        !endif
    """)
    font = _font("Bold")
    up = compute_document(font, doc, context=UPRIGHT)
    it = compute_document(font, doc, context=ITALIC)
    assert dict((n, x) for n, x, _ in up["L"])["dot"] == pytest.approx(286, abs=1)
    assert dict((n, x) for n, x, _ in it["L"])["dot"] == 250
    assert {n for n, *_ in up["L"]} == {"dot", "bold"}      # styleName from fontinfo
    # the context's style name wins over fontinfo (a designspace source name)
    plain = compute_document(font, doc, context=RuleContext(style_name="Regular",
                                                           xvalues={"ital": 0}))
    assert {n for n, *_ in plain["L"]} == {"dot"}
    with pytest.raises(ConditionError, match="no xvalue for axis 'ital'"):
        compute_document(font, doc)


GC = """\
# breve composites
!if ital.xvalue == 0
gbreve = g.ss01 + brevecomb@top
!else
gbreve = g + brevecomb@top   # the plain g in italic
!endif
$x = top
Lbreve = L + brevecomb@{x}
"""


def test_gc_conditionals_keep_source_lines():
    up = {c.name: (c.line, c.text) for c in parse_constructions(GC, context=UPRIGHT)}
    it = {c.name: (c.line, c.text) for c in parse_constructions(GC, context=ITALIC)}
    assert up["gbreve"][0] == 3 and up["gbreve"][1].startswith("gbreve = g.ss01")
    assert it["gbreve"][0] == 5 and it["gbreve"][1].startswith("gbreve = g +")
    assert up["Lbreve"][0] == it["Lbreve"][0] == 8


def test_gc_mark_colour_bang_is_not_a_directive():
    gc = "aacute = a + acute@top ! 1,0,0,1\n"
    assert parse_constructions(gc, context=UPRIGHT)[0].line == 1


def test_build_composites_per_master_and_structure_diff():
    font = _font()
    up = build_composites(font, GC, context=UPRIGHT)
    it = build_composites(font, GC, context=ITALIC)
    assert up["gbreve"].base == "g.ss01" and up["gbreve"].source_line == 3
    assert it["gbreve"].base == "g" and it["gbreve"].source_line == 5
    diff = structure_diff(composites={"Upright": up, "Italic": it})
    assert set(diff.composites) == {"gbreve"}
    assert diff.composites["gbreve"] == {"Upright": ("g.ss01", "brevecomb"),
                                         "Italic": ("g", "brevecomb")}
    assert "gbreve: components differ" in diff.warnings()[0]


def test_structure_diff_on_anchor_results():
    doc = doc_of("""
        L = dot (100 200)
        !if ital.xvalue == 1
        L += extra (0 0)
        !endif
    """)
    font = _font()
    res = {"Upright": compute_document(font, doc, context=UPRIGHT),
           "Italic": compute_document(font, doc, context=ITALIC)}
    diff = structure_diff(anchors=res)
    assert diff.anchors == {"L": {"Upright": frozenset({"dot"}),
                                  "Italic": frozenset({"dot", "extra"})}}
    assert not structure_diff(anchors={"a": res["Upright"], "b": res["Upright"]})


def test_cli_designspace_and_location(tmp_path, caplog):
    from anchorsfactory.cli import main
    _font("Light").save(str(tmp_path / "Light.ufo"))
    _font("Bold Italic").save(str(tmp_path / "BoldItalic.ufo"))
    (tmp_path / "fam.designspace").write_text(DESIGNSPACE)
    (tmp_path / "r.anchors").write_text(
        "L = dot (100 200)\n!if ital.xvalue == 1\nL += extra (0 0)\n!endif\n")
    assert main([str(tmp_path / "Light.ufo"), str(tmp_path / "BoldItalic.ufo"),
                 "-r", str(tmp_path / "r.anchors"),
                 "--designspace", str(tmp_path / "fam.designspace")]) == 0
    light = fontParts.OpenFont(str(tmp_path / "Light_anchored.ufo"))
    bold = fontParts.OpenFont(str(tmp_path / "BoldItalic_anchored.ufo"))
    assert {a.name for a in light["L"].anchors} == {"dot"}
    assert {a.name for a in bold["L"].anchors} == {"dot", "extra"}
    assert any("masters differ" in r.message for r in caplog.records)

    # a single UFO with an explicit location, no designspace
    assert main([str(tmp_path / "Light.ufo"), "-r", str(tmp_path / "r.anchors"),
                 "-o", str(tmp_path / "out.ufo"), "--location", "ital.xvalue=1"]) == 0
    out = fontParts.OpenFont(str(tmp_path / "out.ufo"))
    assert {a.name for a in out["L"].anchors} == {"dot", "extra"}
    # ...and without one, the axis condition is a per-font error
    assert main([str(tmp_path / "Light.ufo"), "-r", str(tmp_path / "r.anchors"),
                 "-o", str(tmp_path / "out2.ufo")]) == 1
