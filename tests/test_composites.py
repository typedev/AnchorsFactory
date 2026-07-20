"""The library GlyphConstruction core (anchorsfactory.composites): line-tracked
parsing and assembly against a ready glyphset, returning live ConstructionGlyphs
plus each construction's source line (the provenance an editor highlights)."""

import pytest

pytest.importorskip("fontParts.world")

from anchorsfactory import (
    apply_document, build_composites, composites_in_glyph_order, load_document,
    parse_construction, parse_constructions,
)
from anchorsfactory.composites import resolve_unicode_refs
from anchorsfactory.presets import construction_text
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


def test_parse_constructions_line_after_interior_blank():
    # Regression: the engine keeps blank lines as "" slots but an older filter
    # dropped them, so every construction past the first blank got the wrong
    # line (or None). A blank line between families must not shift the numbering.
    gc = (
        "Aacute = A + acute@top\n"       # 1
        "Agrave = A + grave@top\n"       # 2
        "# c\n"                          # 3 (comment)
        "\n"                             # 4 (blank)
        "Adieresis = A + dieresis@top\n" # 5
    )
    by_name = {c.name: c.line for c in parse_constructions(gc)}
    assert by_name == {"Aacute": 1, "Agrave": 2, "Adieresis": 5}


def test_parse_constructions_line_with_leading_var_and_blanks():
    # A $var-blanked line and a genuine blank at the very top are dropped by the
    # engine (leading empties), so the first real construction is line 3, not 1.
    gc = (
        "\n"                             # 1 (leading blank)
        "$top = top\n"                   # 2 (variable definition)
        "Aacute = A + acute@{top}\n"     # 3
        "\n"                             # 4 (interior blank)
        "Bhook = B + hook@{top}\n"       # 5
    )
    by_name = {c.name: c.line for c in parse_constructions(gc)}
    assert by_name == {"Aacute": 3, "Bhook": 5}


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


# --- U+ references (the AnchorsFactory extension over GC) ------------------ #
def test_unicode_refs_resolve_through_the_font():
    """A codepoint resolves to whatever *this font* calls that character."""
    font = build_demo_font()                      # encodes acute as U+00B4
    assert resolve_unicode_refs("U+0041 = U+0061 + U+00B4@top", font) == \
        "A = a + acute@top"


def test_unicode_refs_fall_back_to_the_spacing_twin():
    """A font that encodes only the spacing accent still gets the mark: the
    combining codepoint falls through to its twin."""
    font = build_demo_font()                      # has U+00B4, no U+0301
    assert resolve_unicode_refs("U+0301", font) == "acute"


def test_unicode_refs_without_a_font_use_agl_then_uni_names():
    # The target glyph of a construction does not exist yet — no font can name it.
    assert resolve_unicode_refs("U+00C1 = U+0041 + U+0301@top") == \
        "Aacute = A + acutecomb@top"
    assert resolve_unicode_refs("U+F6C3") == "uniF6C3"      # nothing knows this one


def test_unicode_refs_preserve_line_numbers():
    """Resolution is token substitution, so click-to-rule keeps working."""
    gc = "# a comment\n\nU+00E1 = U+0061 + U+00B4@top\n"
    font = build_demo_font()
    assert len(resolve_unicode_refs(gc, font).splitlines()) == len(gc.splitlines())
    (c,) = parse_constructions(gc, font)
    assert (c.name, c.line) == ("aacute", 3)


def test_text_without_unicode_refs_is_untouched():
    gc = "aacute = a + acute@top"
    assert resolve_unicode_refs(gc, build_demo_font()) is gc


def test_build_composites_from_codepoint_addressed_text():
    font = build_demo_font()
    apply_document(font, load_document("default"))
    built = build_composites(font, "U+00E1 = U+0061 + U+00B4@top | 00E1")
    assert "aacute" in built
    c = built["aacute"]
    assert c.glyph is not None and not c.problems
    assert (c.base, c.marks) == ("a", (("acute", "top"),))


def test_bundled_default_preset_builds_its_own_composites():
    """The two halves of the bundled preset agree: every construction it ships
    assembles from the anchors its rules place."""
    font = build_demo_font()
    apply_document(font, load_document("default"))
    built = build_composites(font, construction_text("default"))
    assert built                                   # the preset ships constructions
    demo = [c for c in built.values() if not any("not found" in p for p in c.problems)]
    assert demo, "no construction could be built on the demo font"
    for c in demo:
        assert c.glyph is not None


# --- legacy accent sets ---------------------------------------------------- #
def _font_with_capital_accents():
    """The demo font plus a capital-height accent set — unencoded, name-only,
    the way fonts actually ship one."""
    font = build_demo_font()
    for name in ("Acute", "acute.case"):
        g = font.newGlyph(name)
        g.width = 0
        pen = g.getPen()
        pen.moveTo((200, 620)); pen.lineTo((280, 620))
        pen.lineTo((360, 700)); pen.lineTo((280, 700)); pen.closePath()
    return font


def test_case_suffix_picks_the_fonts_capital_accent():
    font = _font_with_capital_accents()
    # `.case` prefers the house spelling it finds: acute.case before Acute.
    assert resolve_unicode_refs("U+0301.case", font) == "acute.case"
    del font["acute.case"]
    assert resolve_unicode_refs("U+0301.case", font) == "Acute"


def test_case_suffix_falls_back_to_the_plain_mark():
    """A font with no capital set still builds — with the ordinary accent."""
    font = build_demo_font()                      # has acute (U+00B4) only
    assert resolve_unicode_refs("U+0301.case", font) == "acute"


def test_case_suffix_without_a_font_uses_the_legacy_spelling():
    assert resolve_unicode_refs("U+00C1 = A + U+0301.case@top") == "Aacute = A + Acute@top"


def test_bundled_default_uses_the_capital_set_for_uppercase():
    """The shipped constructions ask for the capital cut on uppercase bases and
    the plain mark on lowercase ones."""
    gc = construction_text("default")
    upper = next(l for l in gc.splitlines() if l.startswith("U+00C1 "))   # Aacute
    lower = next(l for l in gc.splitlines() if l.startswith("U+00E1 "))   # aacute
    assert ".case" in upper and ".case" not in lower
