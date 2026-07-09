"""Studio (the visual debugger) — the pure functions behind the server.

Self-contained: everything runs against the built-in synthetic demo font, so
no shipped fixture and no socket is needed. Exercises glyph→SVG rendering, the
``geometry.explain`` overlay contract, and the ``build_view`` compute payload
(including that it agrees with the engine's own ``compute_document``).
"""

import base64
import os

import pytest

pytest.importorskip("fontParts.world")

from anchorsfactory.apply import compute_document
from anchorsfactory.dsl import parse_dsl
from anchorsfactory.geometry import explain, resolve
from anchorsfactory.model import (
    AnchorSpec, Frame, HAlign, VEdge, Pos, Axis,
)
from anchorsfactory.presets import preset_text
from anchorsfactory.studio.demo import build_demo_font, font_metrics
from anchorsfactory.studio.render import all_glyph_geometry, build_view, glyph_to_svg_path
from anchorsfactory.studio.upload import load_uploaded_font


@pytest.fixture(scope="module")
def font():
    return build_demo_font()


def test_edge_offset_shifts_sample_line(font):
    # @top-40 samples 40 units below the bbox top; on the slanted A that also
    # moves the centre x — bare @top is unchanged.
    from anchorsfactory.dsl import parse_dsl
    top = explain(font, font["A"], parse_dsl(["@x = A (outline.center@top 0)"]).labels["@x"][0])
    off = explain(font, font["A"], parse_dsl(["@x = A (outline.center@top-40 0)"]).labels["@x"][0])
    assert off["x_sample"]["height"] == top["x_sample"]["height"] - 40
    assert off["x"] != top["x"]


def test_all_glyph_geometry_covers_every_glyph(font):
    geo = all_glyph_geometry(font)
    assert {g["name"] for g in geo} == {g.name for g in font}
    for g in geo:
        assert set(g) == {"name", "order", "advance", "bounds", "path"}
        assert "anchors" not in g                       # rule-independent
    # a glyph no bundled rule matches (a mark) is still present, with an outline
    acute = next(g for g in geo if g["name"] == "acute")
    assert acute["path"] and acute["bounds"] is not None


# --------------------------------------------------------------------------- #
#  demo font
# --------------------------------------------------------------------------- #
def test_demo_font_has_drawable_glyphs(font):
    names = {g.name for g in font}
    assert {"H", "O", "a", "o", "acute", "dieresis"} <= names
    assert font["H"].bounds is not None
    assert font_metrics(font)["capHeight"] == 700


# --------------------------------------------------------------------------- #
#  render: glyph -> svg path
# --------------------------------------------------------------------------- #
def test_glyph_to_svg_path_nonempty(font):
    d = glyph_to_svg_path(font["H"])
    assert d and d.startswith("M")          # a real move-to leads the path
    # O has a counter → the decomposed outline yields more than one subpath.
    assert glyph_to_svg_path(font["O"]).count("M") >= 2


def test_empty_glyph_path_is_blank(font):
    g = font.newGlyph("space")
    g.width = 250
    assert glyph_to_svg_path(g) == ""


# --------------------------------------------------------------------------- #
#  geometry.explain
# --------------------------------------------------------------------------- #
def test_explain_point_matches_resolve(font):
    g = font["H"]
    spec = AnchorSpec("top", Pos(Frame.BOX, HAlign.CENTER),
                      Pos(Frame.BOX, VEdge.TOP, axis=Axis.Y))
    info = explain(font, g, spec)
    assert (info["x"], info["y"]) == resolve(font, g, spec)
    assert info["x_kind"] == "box" and info["y_kind"] == "box"
    assert info["bounds"] == list(g.bounds)


def test_explain_exposes_scanline_and_stems(font):
    # An OUTLINE X on H at y=0 samples a horizontal scanline crossing both stems.
    g = font["H"]
    spec = AnchorSpec("hook",
                      Pos(Frame.OUTLINE, HAlign.RIGHT),
                      Pos(Frame.BOX, VEdge.BOTTOM, axis=Axis.Y))
    info = explain(font, g, spec)
    assert "x_sample" in info
    assert info["x_sample"]["height"] == 0
    # two vertical stems → two paired ink spans on the baseline scanline
    assert len(info["x_sample"]["stems"]) == 2
    assert info["x"] == pytest.approx(600)   # right edge of the right stem


# --------------------------------------------------------------------------- #
#  build_view compute payload
# --------------------------------------------------------------------------- #
def test_build_view_agrees_with_compute_document(font):
    rules = preset_text("default")
    view = build_view(font, rules)
    assert view["ok"]
    assert view["glyphs"], "default rules should touch demo glyphs"

    doc = parse_dsl(rules.splitlines())
    expected = compute_document(font, doc, round_coords=False)

    # same set of affected glyphs
    assert set(view["glyphs"]) == set(expected)
    # same anchors + coordinates per glyph (studio keeps float precision)
    for gname, spec_anchors in expected.items():
        got = {a["name"]: (a["x"], a["y"]) for a in view["glyphs"][gname]["anchors"]}
        want = {name: (x, y) for name, x, y in spec_anchors}
        assert got.keys() == want.keys()
        for name in want:
            assert got[name] == pytest.approx(want[name])


def test_build_view_resolves_extends_preset(font):
    # custom rules inheriting the bundled default, then overriding H
    rules = "!extends default\nH = zz (box.left ascender)\n"
    view = build_view(font, rules)
    assert view["ok"]
    # inherited: O still gets its default anchors (O is not in the edited text)
    assert "O" in view["glyphs"]
    assert view["glyphs"]["O"]["anchors"][0]["line"] is None      # inherited → no editor line
    # override wins: H replaced by the edited rule, which keeps its source line
    h = {a["name"]: a for a in view["glyphs"]["H"]["anchors"]}
    assert set(h) == {"zz"}
    assert h["zz"]["line"] == 2


def test_build_view_layers_merge_and_provenance(font):
    layers = [
        {"name": "base", "text": "H = top (box.center capHeight), bottom (box.center 0)"},
        {"name": "custom", "text": "H += hook (outline.right 0)\nH = zz (box.left ascender)"},
    ]
    view = build_view(font, layers)
    assert view["layers"] == ["base", "custom"]
    # custom's `H = zz` (layer 1, line 2) replaces everything the base placed
    h = {a["name"]: (a["layer"], a["line"]) for a in view["glyphs"]["H"]["anchors"]}
    assert h == {"zz": (1, 2)}


def test_build_view_layers_base_stays_visible(font):
    layers = [
        {"name": "base", "text": preset_text("default")},
        {"name": "custom", "text": "H = zz (box.left ascender)"},
    ]
    view = build_view(font, layers)
    # base (layer 0) still places O; custom (layer 1) overrides only H
    assert view["glyphs"]["O"]["anchors"][0]["layer"] == 0
    assert {a["name"]: a["layer"] for a in view["glyphs"]["H"]["anchors"]} == {"zz": 1}


def test_build_view_layers_report_error_with_layer_name(font):
    view = build_view(font, [{"name": "base", "text": ""},
                             {"name": "custom", "text": "H = ("}])
    assert view["ok"] is False
    assert view["problems"] and view["problems"][0].startswith("custom:")


def test_resolve_document_rejects_path_extends():
    from anchorsfactory.studio.render import resolve_document
    with pytest.raises(ValueError):
        resolve_document("!extends ./local/base.af\nH = top (box.center capHeight)")


def test_build_view_reports_parse_error_without_raising(font):
    view = build_view(font, "H = top (this is not valid dsl")
    assert view["ok"] is False
    assert view["problems"]
    assert view["glyphs"] == {}


def test_build_view_reports_undefined_label_without_raising(font):
    # Parses cleanly but references a label that is never defined — this used to
    # slip past into the per-glyph accumulate() and raise ValueError, 500-ing the
    # request. It must come back as a problem, not an exception.
    view = build_view(font, "H = @missing")
    assert view["ok"] is False
    assert any("undefined label" in p for p in view["problems"])
    assert view["glyphs"] == {}


def test_build_view_attaches_rule_provenance(font):
    # Three lines; H's anchors come from the box rule, then hook adds one, and
    # the last line replaces top. Each anchor should report the line it came from.
    rules = (
        "H = top (box.center capHeight), bottom (box.center 0)\n"   # line 1
        "H += hook (outline.right 0)\n"                             # line 2
        "H = top (box.center ascender)\n"                          # line 3 (replaces all)
    )
    view = build_view(font, rules)
    lines = {a["name"]: a["line"] for a in view["glyphs"]["H"]["anchors"]}
    # line 3 REPLACES, so only 'top' survives, sourced at line 3
    assert lines == {"top": 3}


def test_build_view_provenance_across_add(font):
    rules = "H = top (box.center capHeight)\nH += hook (outline.right 0)\n"
    view = build_view(font, rules)
    lines = {a["name"]: a["line"] for a in view["glyphs"]["H"]["anchors"]}
    assert lines == {"top": 1, "hook": 2}


def test_accumulate_provenance_indices(font):
    from anchorsfactory.apply import accumulate_provenance
    doc = parse_dsl(["a = top (box.center capHeight)", "a += tail (box.left 0)"])
    prov = accumulate_provenance(doc, "a", [0x61])
    assert [(s.name, idx) for s, idx in prov] == [("top", 0), ("tail", 1)]


def test_build_view_orders_glyphs_by_font_glyphorder(font):
    view = build_view(font, preset_text("default"))
    by_order = sorted(view["glyphs"].values(), key=lambda g: g["order"])
    names = [g["name"] for g in by_order]
    expected = [n for n in font.glyphOrder if n in view["glyphs"]]
    assert names == expected
    # the demo font's order is its creation order, which is NOT alphabetical
    assert names != sorted(names)


def test_build_view_anchor_carries_overlay(font):
    # Round lowercase 'o' → outline.center sampling; its anchors expose x_sample.
    view = build_view(font, "o = top (outline.center@xHeight 500), bottom (outline.center 0)")
    anchors = view["glyphs"]["o"]["anchors"]
    assert any("x_sample" in a for a in anchors)


# --------------------------------------------------------------------------- #
#  upload: reconstruct a dropped UFO
# --------------------------------------------------------------------------- #
def _as_upload(ufo_dir):
    """Mimic what the browser sends: every file under the .ufo with its relative
    path (rooted at the .ufo folder name) and base64 contents."""
    root = os.path.dirname(ufo_dir)
    files = []
    for dirpath, _dirs, names in os.walk(ufo_dir):
        for n in names:
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, root)
            with open(full, "rb") as fh:
                files.append({"path": rel, "data": base64.b64encode(fh.read()).decode()})
    return files


def test_load_uploaded_font_roundtrip(tmp_path):
    ufo = str(tmp_path / "Demo.ufo")
    build_demo_font().save(ufo)

    loaded, name, tmpdir = load_uploaded_font(_as_upload(ufo), "Demo.ufo")
    try:
        assert {"H", "O", "o", "acute"} <= {g.name for g in loaded}
        assert loaded["H"].bounds is not None
        # the reconstructed font drives the engine like any other
        view = build_view(loaded, "H = top (box.center capHeight)")
        assert view["glyphs"]["H"]["anchors"][0]["name"] == "top"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def _zip_ufo(ufo_dir, zip_path, arc_root):
    import zipfile
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, _d, ns in os.walk(ufo_dir):
            for n in ns:
                full = os.path.join(dp, n)
                z.write(full, os.path.join(arc_root, os.path.relpath(full, ufo_dir)))


def _dropped_file(path):
    """One dropped archive file, as the browser would send it."""
    with open(path, "rb") as fh:
        return [{"path": os.path.basename(path), "data": base64.b64encode(fh.read()).decode()}]


@pytest.mark.parametrize("ext,arc_root", [
    (".ufoz", "Demo.ufo"),      # zipped UFO, .ufoz extension
    (".zip", "Demo.ufo"),       # plain zip containing the .ufo folder
    (".zip", ""),               # flat zip: UFO contents at the archive root
])
def test_load_uploaded_font_from_archive(tmp_path, ext, arc_root):
    ufo = str(tmp_path / "Demo.ufo")
    build_demo_font().save(ufo)
    archive = str(tmp_path / ("Bundle" + ext))
    _zip_ufo(ufo, archive, arc_root)

    loaded, name, tmpdir = load_uploaded_font(_dropped_file(archive), os.path.basename(archive))
    try:
        assert {"H", "O", "o", "acute"} <= {g.name for g in loaded}
        assert loaded["H"].bounds == (100, 0, 600, 700)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_load_uploaded_font_rejects_junk():
    with pytest.raises(ValueError):
        load_uploaded_font([{"path": "notes.txt", "data": ""}], "junk")


def test_load_uploaded_font_blocks_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        load_uploaded_font([{"path": "../escape.txt", "data": ""}], "evil")


def test_studio_holds_multiple_fonts():
    """add/activate/remove keep the font list + active pointer (and the `font`
    property) in sync, and never drop the last font."""
    from anchorsfactory.presets import preset_text
    from anchorsfactory.studio.server import Studio

    f1, f2 = build_demo_font(), build_demo_font()
    st = Studio(f1, preset_text("default"), "Regular")
    assert [c["name"] for c in st.state["fonts"]] == ["Regular"]
    assert st.font is f1 and st.state["active"] == 0

    st.add_font(f2, "Italic")                       # append → becomes active
    assert [c["name"] for c in st.state["fonts"]] == ["Regular", "Italic"]
    assert st.state["active"] == 1 and st.font is f2 and st.state["font"] == "Italic"

    st.activate(0)                                  # switch back
    assert st.state["active"] == 0 and st.font is f1 and st.state["font"] == "Regular"

    st.remove_font(1)
    assert [c["name"] for c in st.state["fonts"]] == ["Regular"] and st.font is f1
    assert st.remove_font(0) is None                # never drop the last font
    assert len(st.fonts) == 1
