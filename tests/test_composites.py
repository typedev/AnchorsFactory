"""The library GlyphConstruction core (anchorsfactory.composites): line-tracked
parsing and assembly against a ready glyphset, returning live ConstructionGlyphs
plus each construction's source line (the provenance an editor highlights)."""

import pytest

pytest.importorskip("fontParts.world")

from anchorsfactory import (
    apply_document, build_composites, composites_in_glyph_order, load_document,
    parse_construction, parse_constructions,
)
from anchorsfactory.studio.demo import build_demo_font


def test_parse_construction_recipe():
    assert parse_construction("aacute = a + acute@top") == ("aacute", "a", [("acute", "top")])
    assert parse_construction("# just a comment") is None


def test_parse_constructions_tracks_source_line():
    gc = (
        "# a comment\n"
        "\n"
        "aacute = a + acute@top\n"
        "$x = 5\n"                          # a variable definition, not a construction
        "odieresis = o + dieresis@top\n"
    )
    cons = parse_constructions(gc)
    by_name = {c.name: c.line for c in cons}
    # lines are 1-based; the comment/blank/variable lines are skipped
    assert by_name["aacute"] == 3
    assert by_name["odieresis"] == 5


def _anchored_font():
    font = build_demo_font()
    apply_document(font, load_document("default"))     # composites read glyph.anchors
    return font


def test_build_composites_assembles_and_carries_line():
    font = _anchored_font()
    gc = "aacute = a + acute@top\nodieresis = o + dieresis@top"
    comps = build_composites(font, gc)
    assert set(comps) == {"aacute", "odieresis"}
    a = comps["aacute"]
    assert a.source_line == 1 and a.base == "a" and a.marks == (("acute", "top"),)
    assert a.problems == ()
    # the live ConstructionGlyph is usable (name/width/components)
    assert a.glyph.name == "aacute"
    assert [g for g, _t in a.glyph.components] == ["a", "acute"]
    assert comps["odieresis"].source_line == 2


def test_build_composites_flags_missing_and_survives_batch():
    font = _anchored_font()
    comps = build_composites(font, "xbad = a + NoSuchMark@top\nagood = a + acute@top")
    assert any("NoSuchMark" in p for p in comps["xbad"].problems)
    assert comps["agood"].problems == ()           # the good one still built


def test_composites_in_glyph_order():
    font = _anchored_font()
    order = composites_in_glyph_order(font, ["odieresis", "aacute", "zzz_unknown"])
    # known names follow the font glyphOrder; unknown sorts last
    assert order.index("aacute") < order.index("odieresis") or \
           order.index("odieresis") < order.index("aacute")
    assert order[-1] == "zzz_unknown"
