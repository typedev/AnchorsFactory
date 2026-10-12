"""Writing the rules' anchors back into the fonts (``anchors/plan`` →
the page writes → ``anchors/commit``), with ufonormalizer-normalized glifs."""

import base64
import io
import zipfile

import pytest

pytest.importorskip("fontParts.world")
ufonormalizer = pytest.importorskip("ufonormalizer")

from anchorsfactory.studio.api import Studio
from anchorsfactory.studio.demo import build_demo_font
from anchorsfactory.studio.save import rewrite_glif


def _layers(text):
    return {"layers": [{"name": "default", "text": text}]}


def _studio_with_drop(tmp_path, *, anchors_on_h=()):
    """A Studio with a dropped ``Drop/Demo.ufo`` (the session's copy)."""
    font = build_demo_font()
    for name, x, y in anchors_on_h:
        font["H"].appendAnchor(name, (x, y))
    root = tmp_path / "drop"
    (root / "Drop").mkdir(parents=True)
    font.save(str(root / "Drop" / "Demo.ufo"))
    studio = Studio(build_demo_font(), "", "demo")
    assert studio.open_font_tree(str(root))[0] == 200
    return studio, root / "Drop" / "Demo.ufo"


def test_plan_lists_changed_glyphs_with_normalized_glifs(tmp_path):
    studio, ufo = _studio_with_drop(tmp_path)
    status, plan = studio.dispatch("anchors/plan", _layers("H = top (100 700), bottom (100 0)\n"))
    assert status == 200 and plan["ok"]
    (master,) = plan["masters"]                     # the placeholder demo has no files
    assert master["glyphs"] == ["H"] and master["ufo"] == "Drop/Demo.ufo"
    (f,) = plan["files"]
    assert f["path"] == "Drop/Demo.ufo/glyphs/H_.glif"
    assert f["original"] == (ufo / "glyphs" / "H_.glif").read_text()
    assert '<anchor name="top" x="100" y="700"/>' in f["text"]
    assert ufonormalizer.normalizeGLIFString(f["text"]) == f["text"]     # already normalized


def test_commit_applies_in_memory_and_to_the_session_copy(tmp_path):
    studio, ufo = _studio_with_drop(tmp_path)
    rules = _layers("H = top (100 700)\n")
    plan = studio.dispatch("anchors/plan", rules)[1]
    assert studio.dispatch("anchors/commit")[1] == {"ok": True, "written": 1}
    assert [(a.name, a.x, a.y) for a in studio.fonts[1]["font"]["H"].anchors] == [("top", 100, 700)]
    assert (ufo / "glyphs" / "H_.glif").read_text() == plan["files"][0]["text"]
    assert studio.dispatch("anchors/commit")[0] == 400         # the plan is used up
    assert studio.dispatch("anchors/plan", rules)[1]["files"] == []   # nothing left to write


def test_unchanged_anchors_are_not_rewritten(tmp_path):
    studio, _ = _studio_with_drop(tmp_path, anchors_on_h=[("bottom", 100, 0), ("top", 100, 700)])
    plan = studio.dispatch("anchors/plan", _layers("H = top (100 700), bottom (100 0)\n"))[1]
    assert plan["masters"][0]["glyphs"] == [] and plan["total"] == 0


def test_a_kept_anchor_keeps_its_identifier_and_color():
    glif = b"""<?xml version="1.0" encoding="UTF-8"?>
<glyph name="H" format="2">
  <advance width="700"/>
  <anchor name="top" x="0" y="0" identifier="abc" color="1,0,0,1"/>
  <anchor name="gone" x="5" y="5"/>
</glyph>
"""
    text = rewrite_glif(glif, "H", [("top", 100, 700), ("new", 1.5, 2)])
    assert '<anchor name="top" x="100" y="700" color="1,0,0,1" identifier="abc"/>' in text
    assert 'name="new" x="1.5" y="2"' in text and "gone" not in text


def test_each_master_gets_its_own_if_blocks(tmp_path):
    from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
    root = tmp_path / "drop" / "P"
    root.mkdir(parents=True)
    for name in ("Up", "It"):
        build_demo_font().save(str(root / f"{name}.ufo"))
    doc = DesignSpaceDocument()
    doc.addAxis(AxisDescriptor(name="Italic", tag="ital", minimum=0, default=0, maximum=1))
    doc.addSource(SourceDescriptor(filename="Up.ufo", location={"Italic": 0}))
    doc.addSource(SourceDescriptor(filename="It.ufo", location={"Italic": 1}))
    doc.write(str(root / "P.designspace"))
    studio = Studio(build_demo_font(), "", "demo")
    studio.open_font_tree(str(tmp_path / "drop"))
    rules = "H = top (100 700)\n!if Italic.xvalue == 1\nH += slant (0 0)\n!endif\n"
    plan = studio.dispatch("anchors/plan", _layers(rules))[1]
    texts = {f["path"]: f["text"] for f in plan["files"]}
    assert "slant" not in texts["P/Up.ufo/glyphs/H_.glif"]
    assert "slant" in texts["P/It.ufo/glyphs/H_.glif"]


def test_zip_of_the_planned_files(tmp_path):
    studio, _ = _studio_with_drop(tmp_path)
    studio.dispatch("anchors/plan", _layers("H = top (100 700)\n"))
    data = base64.b64decode(studio.dispatch("anchors/zip")[1]["data"])
    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == ["Drop/Demo.ufo/glyphs/H_.glif"]


def test_a_font_opened_from_a_path_is_written_by_python(tmp_path):
    from fontParts.world import OpenFont
    build_demo_font().save(str(tmp_path / "Demo.ufo"))
    studio = Studio(OpenFont(str(tmp_path / "Demo.ufo")), "", "Demo")
    plan = studio.dispatch("anchors/plan", _layers("H = top (100 700)\n"))[1]
    assert plan["files"] == [] and plan["python"] == 1 and plan["masters"][0]["mode"] == "python"
    studio.dispatch("anchors/commit")
    assert 'name="top"' in (tmp_path / "Demo.ufo" / "glyphs" / "H_.glif").read_text()


def test_rules_that_do_not_resolve_are_reported_per_master(tmp_path):
    studio, _ = _studio_with_drop(tmp_path)
    plan = studio.dispatch("anchors/plan", _layers("H = top (&nope 0)\n"))[1]
    assert not plan["ok"] and plan["masters"][0]["problems"]
