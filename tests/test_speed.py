"""The speed work behind the web Studio: fontParts' O(1) lookup opt-in, a
non-mutating anchored view for composites, and names-filtered computes — all
of which must give exactly the results of the slow paths."""

import pytest

pytest.importorskip("fontParts.world")

from rulesets import gc_text, rules_doc
from anchorsfactory import (apply_document, build_composites, compute_document,
                            parse_dsl, speedups)
from anchorsfactory.composites import AnchoredGlyphSet, construction_glyph_names
from anchorsfactory.studio.demo import build_demo_font


def _sig(built):
    return {n: (c.base, c.marks, c.problems,
                tuple(c.glyph.components) if c.glyph else None) for n, c in built.items()}


def test_speedups_enable_is_idempotent_and_keeps_semantics():
    font = build_demo_font()
    before = ("a" in font, "nope" in font, font["a"].name)
    assert speedups.enable() is True
    assert speedups.enable() is True                      # idempotent
    assert ("a" in font, "nope" in font, font["a"].name) == before
    with pytest.raises(KeyError):
        font["nope"]
    layer = font.defaultLayer
    assert "a" in layer and "nope" not in layer


def test_anchored_glyph_set_matches_apply_on_a_copy():
    font, doc, gc = build_demo_font(), rules_doc("default"), gc_text("default")
    work = font.copy()
    apply_document(work, doc)
    view = AnchoredGlyphSet(font, compute_document(font, doc))
    assert _sig(build_composites(view, gc)) == _sig(build_composites(work, gc))
    # the font itself is untouched
    assert [a.name for a in font["a"].anchors] == [a.name for a in build_demo_font()["a"].anchors]


def test_anchored_glyph_set_clear_false_keeps_other_existing_anchors():
    font = build_demo_font()
    font["a"].appendAnchor("old", (1, 2))
    font["a"].appendAnchor("top", (0, 0))
    placed = {"a": [("top", 10.0, 20.0)]}
    names = lambda gs: sorted((x.name, x.x, x.y) for x in gs["a"].anchors)
    assert names(AnchoredGlyphSet(font, placed)) == [("top", 10.0, 20.0)]
    kept = names(AnchoredGlyphSet(font, placed, clear=False))
    assert ("old", 1, 2) in kept and ("top", 10.0, 20.0) in kept and ("top", 0, 0) not in kept


def test_anchored_glyph_set_delegates_and_raises():
    font = build_demo_font()
    view = AnchoredGlyphSet(font, {})
    assert "a" in view and "nope" not in view and len(view) == len(font)
    assert view["a"].width == font["a"].width
    assert view.info.styleName == font.info.styleName        # font attributes pass through
    with pytest.raises(KeyError):
        view["nope"]


def test_names_filtered_compute_matches_the_full_one():
    font = build_demo_font()
    doc = parse_dsl("!propagate = composites\n{Lu} = top (box.center capHeight)\n"
                    "{Ll} = top (box.center xHeight)\n")
    full = compute_document(font, doc)
    some = sorted(full)[:2]
    part = compute_document(font, doc, names=some)
    assert dict(part) == {n: full[n] for n in some}


def test_construction_glyph_names():
    gc = "aacute = a + acute@top\n# x\n!if ital.xvalue == 1\nobar = o + bar\n!endif\n"
    from anchorsfactory import RuleContext
    assert construction_glyph_names(gc, context=RuleContext(xvalues={"ital": 0})) == {"a", "acute"}
    assert construction_glyph_names(gc, context=RuleContext(xvalues={"ital": 1})) == {
        "a", "acute", "o", "bar"}


def test_studio_path_cache_is_filled_and_reused():
    from anchorsfactory.studio.render import build_view
    font, paths = build_demo_font(), {}
    layers = [{"name": "d", "text": "{Lu} = top (box.center capHeight)"}]
    v1 = build_view(font, layers, None, paths)
    assert set(paths) == set(v1["glyphs"])
    paths["H"] = "SENTINEL"                           # served from the cache, not redrawn
    assert build_view(font, layers, None, paths)["glyphs"]["H"]["path"] == "SENTINEL"
