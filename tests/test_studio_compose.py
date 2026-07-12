"""The AF→GC Studio seam: build_composites assembles composites from the anchors
the rules place, on a copy of the font, and reports missing/misnamed anchors."""

import pytest

pytest.importorskip("fontParts.world")

from anchorsfactory.presets import preset_text
from anchorsfactory.studio.compose import build_composite_view as build_composites
from anchorsfactory.studio.demo import build_demo_font


def _layers():
    return [{"name": "base", "text": preset_text("default")}]


def test_build_composite_from_placed_anchors():
    r = build_composites(build_demo_font(), _layers(), "aacute = a + acute@top")
    assert r["ok"] and r["problems"] == []
    c = r["composites"]["aacute"]
    assert [comp["base"] for comp in c["components"]] == ["a", "acute"]
    # acute is offset by exactly (a.top − acute._top) — the demo anchors give (10, 0).
    assert c["components"][1]["transform"][4:] == [10.0, 0.0]
    assert c["joins"] == [{"x": 250, "y": 600, "anchor": "top"}]
    assert c["problems"] == []
    assert c["components"][0]["path"]             # base outline was produced


def test_missing_anchor_is_reported():
    r = build_composites(build_demo_font(), _layers(), "bad = a + acute@nope")
    probs = r["composites"]["bad"]["problems"]
    assert any("nope" in p for p in probs)        # the verification signal fires


def test_missing_component_does_not_crash_batch():
    # A construction referencing a glyph the font lacks must not sink the batch:
    # the bad one is flagged, the good one still builds.
    gc = "xbad = a + NoSuchMark@top\nagood = a + acute@top"
    r = build_composites(build_demo_font(), _layers(), gc)
    assert r["ok"]
    assert any("NoSuchMark" in p for p in r["composites"]["xbad"]["problems"])
    good = r["composites"]["agood"]
    assert good["problems"] == []
    assert [c["base"] for c in good["components"]] == ["a", "acute"]


def test_empty_gc_yields_no_composites():
    r = build_composites(build_demo_font(), _layers(), "   ")
    assert r["ok"] and r["problems"] == [] and r["composites"] == {}


def test_reports_uncovered_precomposed_glyphs():
    # a precomposed glyph the font has but no construction builds is "uncovered"
    r = build_composites(build_demo_font(), _layers(), "xx = a + acute@top")
    assert "aacute" in r["uncovered"]                 # U+00E1, not built as "xx"
    r2 = build_composites(build_demo_font(), _layers(), "aacute = a + acute@top")
    assert "aacute" not in r2["uncovered"]            # now built → covered


def test_shared_font_is_not_mutated():
    font = build_demo_font()
    build_composites(font, _layers(), "aacute = a + acute@top")
    assert len(font["a"].anchors) == 0            # anchors were applied to a copy
