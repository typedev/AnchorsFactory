"""Tests for the current-format parser (parser.py -> IR)."""

import pytest

from anchorsfactory.parser import parse_document, ParseError
from anchorsfactory.model import (
    Frame, HAlign, VEdge, Frac,
    X, XAbs, Y, YAbs, AnchorSpec, LabelRef, GlyphName, Unicode,
    resolve_suffixes,
)


def test_label_with_box_center_and_absolute():
    doc = parse_document(["@=top:centerpos:$H,bottom:centerpos:0"])
    assert doc.labels["@"] == [
        AnchorSpec("top", X(Frame.BOX, HAlign.CENTER), Y("H", VEdge.TOP)),
        AnchorSpec("bottom", X(Frame.BOX, HAlign.CENTER), YAbs(0)),
    ]


def test_align_vocabulary_mapping():
    doc = parse_document([
        "@a=x:center:0",        # advance
        "@b=x:left:0",          # box edge
        "@c=x:leftinter:0",     # outline
        "@d=x:topcenter:0",     # outline @top
        "@e=x:bottomcenter:0",  # outline @bottom
        "@f=x:250:0",           # absolute
    ])
    assert doc.labels["@a"][0].x == X(Frame.ADVANCE, HAlign.CENTER)
    assert doc.labels["@b"][0].x == X(Frame.BOX, HAlign.LEFT)
    assert doc.labels["@c"][0].x == X(Frame.OUTLINE, HAlign.LEFT)
    assert doc.labels["@d"][0].x == X(Frame.OUTLINE, HAlign.CENTER, at=VEdge.TOP)
    assert doc.labels["@e"][0].x == X(Frame.OUTLINE, HAlign.CENTER, at=VEdge.BOTTOM)
    assert doc.labels["@f"][0].x == XAbs(250)


def test_vertical_suffixes_and_fraction():
    doc = parse_document([
        "@bar=bar:center:$H*1/2",
        "@mid=x:center:$endash-",
        "@bot=x:center:$gravecomb_",
    ])
    assert doc.labels["@bar"][0].y == Y("H", Frac(1, 2))
    assert doc.labels["@mid"][0].y == Y("endash", VEdge.MIDDLE)
    assert doc.labels["@bot"][0].y == Y("gravecomb", VEdge.BOTTOM)


def test_glyph_rule_mixes_inline_and_label():
    doc = parse_document([
        "@bot=bottom:centerpos:0",
        "L=top:left:$H,caron:right:$H,@bot",
    ])
    rule = doc.rules[0]
    assert rule.selector == GlyphName("L")
    assert rule.items == [
        AnchorSpec("top", X(Frame.BOX, HAlign.LEFT), Y("H", VEdge.TOP)),
        AnchorSpec("caron", X(Frame.BOX, HAlign.RIGHT), Y("H", VEdge.TOP)),
        LabelRef("@bot"),                                  # kept as a ref (late-bound)
    ]


def test_unicode_selector_and_label_expansion():
    doc = parse_document([
        "@=top:centerpos:$H",
        "&0413=@,@",          # Г, label used twice
    ])
    rule = doc.rules[0]
    assert rule.selector == Unicode(0x0413)
    assert rule.items == [LabelRef("@"), LabelRef("@")]   # refs, resolved at apply


def test_directives_and_comments():
    doc = parse_document([
        "# a comment line",
        "@SFXLIST=alt,sc",
        "@SHIFTX=-15",
        "A=top:center:$H   # trailing comment",
        "",
    ])
    assert resolve_suffixes(doc.suffix_ops).items == ("", ".alt", ".sc")
    assert doc.shift_x == -15
    assert doc.rules[0].selector == GlyphName("A")


@pytest.mark.parametrize("line", [
    "A=top:center",           # too few fields
    "A=top:bogusalign:0",     # unknown align
    "A=@nosuch",              # undefined label
    "noequalshere",           # missing '='
    "A=top:center:$H*5",      # fraction without /
])
def test_parse_errors(line):
    with pytest.raises(ParseError):
        parse_document([line])
