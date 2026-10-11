"""The Studio API facade: the one surface the local server and the web
worker both call (``Studio.dispatch``), plus the worker's own font loader."""

import base64
import os
import shutil
import zipfile

import pytest

pytest.importorskip("fontParts.world")

from anchorsfactory.studio.api import METHODS, Studio
from anchorsfactory.studio.demo import build_demo_font

RULES = "H = top (100 700)\n"


@pytest.fixture
def studio():
    return Studio(build_demo_font(), RULES, "demo")


def _layers(text=RULES):
    return {"layers": [{"name": "default", "text": text}], "gc": ""}


def test_methods_are_the_http_routes():
    assert set(METHODS) == {"state", "allglyphs", "compute", "font", "font/designspace",
                            "font/activate", "font/remove", "font/context", "masters"}


def test_state_carries_the_engine_version(studio):
    status, state = studio.dispatch("state")
    assert status == 200 and state["font"] == "demo" and state["version"]


def test_compute(studio):
    status, view = studio.dispatch("compute", _layers())
    assert status == 200 and view["ok"]
    assert [a["name"] for a in view["glyphs"]["H"]["anchors"]] == ["top"]


def test_unknown_and_malformed(studio):
    assert studio.dispatch("nope")[0] == 404
    status, out = studio.dispatch("compute", [])
    assert status == 400 and out["problems"] == ["malformed request body"]
    assert studio.dispatch("font/context", "x") == (400, {"ok": False,
                                                          "error": "malformed request body"})


def test_context_error_is_a_400_and_leaves_the_font(studio):
    status, out = studio.dispatch("font/context", {"index": 0, "location": "ital=1"})
    assert status == 400 and "cannot read" in out["error"]
    assert studio.dispatch("font/context", {"index": 0, "location": "ital.xvalue=1"})[0] == 200
    assert studio.context.axis_value("ital", "xvalue") == 1


@pytest.mark.parametrize("zipped", [False, True])
def test_open_font_tree_adds_the_active_font(studio, tmp_path, zipped):
    """The web worker writes a dropped UFO (or .ufoz) under a directory and
    opens it from there; ``warm_on_load`` fills the outline caches during the
    load."""
    root = tmp_path / "drop"
    root.mkdir()
    build_demo_font().save(str(tmp_path / "Demo.ufo"))
    if zipped:
        with zipfile.ZipFile(root / "Demo.ufoz", "w") as z:
            for f in (tmp_path / "Demo.ufo").rglob("*"):
                z.write(f, f.relative_to(tmp_path))
    else:
        shutil.copytree(tmp_path / "Demo.ufo", root / "Demo.ufo")
    studio.warm_on_load = True
    status, out = studio.open_font_tree(str(root))
    assert status == 200 and out["ok"]
    assert len(out["state"]["fonts"]) == 2 and out["state"]["active"] == 1
    entry = studio.fonts[1]
    assert entry["allglyphs"] and set(entry["paths"]) >= {"H", "a"}
    assert studio.dispatch("compute", _layers())[1]["ok"]
    # removing it hands the tree back for cleanup
    assert studio.dispatch("font/remove", {"index": 1})[0] == 200
    assert not root.exists() and len(studio.fonts) == 1


def test_open_font_tree_without_a_ufo(studio, tmp_path):
    status, out = studio.open_font_tree(str(tmp_path))
    assert status == 400 and "no .ufo found" in out["error"]
    assert len(studio.fonts) == 1


# --------------------------------------------------------------------------- #
#  Dropping a folder with designspaces
# --------------------------------------------------------------------------- #

def _save(font, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(path))


def _designspace(path, sources, axis_max=1):
    """Write a designspace with an `ital` axis; *sources* is
    ``[(ufo filename, ital xvalue, stylename or None)]``."""
    from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
    doc = DesignSpaceDocument()
    doc.addAxis(AxisDescriptor(name="Italic", tag="ital", minimum=0, default=0,
                               maximum=axis_max))
    for filename, ital, style in sources:
        doc.addSource(SourceDescriptor(filename=filename, location={"Italic": ital},
                                       styleName=style))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.write(str(path))


@pytest.fixture
def family(tmp_path):
    """A dropped project folder: two masters, two designspaces over them."""
    root = tmp_path / "drop" / "Project"
    for name, style in (("Up.ufo", "Regular"), ("It.ufo", "Italic")):
        font = build_demo_font()
        font.info.familyName, font.info.styleName = "Fam", style
        _save(font, root / "masters" / name)
    _designspace(root / "Fam.designspace",
                 [("masters/Up.ufo", 0, "Regular"), ("masters/It.ufo", 1, "Italic")])
    _designspace(root / "sub" / "Upright.designspace", [("../masters/Up.ufo", 0, None)])
    return tmp_path / "drop"


RULES_IF = """\
H = top (100 700)
!if Italic.xvalue == 1
H += slant (0 0)
!endif
"""


def _anchor_names(studio):
    view = studio.dispatch("compute", _layers(RULES_IF))[1]
    assert view["ok"], view["problems"]
    return sorted(a["name"] for a in view["glyphs"]["H"]["anchors"])


def test_one_designspace_opens_every_master_with_its_location(studio, tmp_path):
    root = tmp_path / "drop"
    for name, style in (("Up.ufo", "Regular"), ("It.ufo", "Italic")):
        _save(build_demo_font(), root / name)
    _designspace(root / "Fam.designspace", [("Up.ufo", 0, "Upright"), ("It.ufo", 1, None)])
    status, out = studio.open_font_tree(str(root))
    assert status == 200 and out["designspace"] == "Fam.designspace" and out["problems"] == []
    cards = out["state"]["fonts"][1:]
    assert [c["designspace"] for c in cards] == [True, True]
    assert [c["location"] for c in cards] == ["Italic.xvalue=0, Italic.uservalue=0",
                                              "Italic.xvalue=1, Italic.uservalue=1"]
    # the source's stylename wins; without one, the UFO's fontinfo applies
    assert [c["styleName"] for c in cards] == ["Upright", "Regular"]
    assert out["state"]["active"] == 1                       # the first master
    assert _anchor_names(studio) == ["top"]
    studio.dispatch("font/activate", {"index": 2})
    assert _anchor_names(studio) == ["slant", "top"]         # `!if` sees the italic master


def test_several_designspaces_wait_for_a_choice(studio, family):
    status, out = studio.open_font_tree(str(family))
    assert status == 200 and out["choose"] == ["Project/Fam.designspace",
                                               "Project/sub/Upright.designspace"]
    assert len(out["state"]["fonts"]) == 1                   # nothing opened yet
    bad = studio.dispatch("font/designspace", {"path": "elsewhere.designspace"})
    assert bad[0] == 400 and studio.pending                  # still waiting
    status, out = studio.dispatch("font/designspace", {"path": "Project/sub/Upright.designspace"})
    assert status == 200 and [c["name"] for c in out["state"]["fonts"]] == ["demo", "Fam Regular"]
    assert studio.pending is None
    assert studio.dispatch("font/designspace", {"path": "x"})[0] == 400   # nothing pending


def test_cancelling_the_choice_discards_the_drop(studio, family):
    studio.open_font_tree(str(family))
    assert studio.dispatch("font/designspace", {"path": None})[0] == 200
    assert not family.exists() and len(studio.fonts) == 1


def test_masters_share_the_drop_until_the_last_is_removed(studio, tmp_path):
    root = tmp_path / "drop"
    for name in ("Up.ufo", "It.ufo"):
        _save(build_demo_font(), root / name)
    _designspace(root / "Fam.designspace", [("Up.ufo", 0, None), ("It.ufo", 1, None)])
    studio.open_font_tree(str(root))
    studio.dispatch("font/remove", {"index": 1})
    assert root.exists()                                      # the other master reads from it
    studio.dispatch("font/remove", {"index": 1})
    assert not root.exists()


def test_missing_sources_are_reported_not_fatal(studio, tmp_path):
    root = tmp_path / "drop"
    _save(build_demo_font(), root / "Up.ufo")
    _designspace(root / "Fam.designspace", [("Up.ufo", 0, None), ("../It.ufo", 1, None)])
    status, out = studio.open_font_tree(str(root))
    assert status == 200 and len(out["state"]["fonts"]) == 2
    assert out["problems"] == ["../It.ufo: not found next to the designspace"]


def test_a_designspace_with_no_reachable_source_is_an_error(studio, tmp_path):
    root = tmp_path / "drop"
    root.mkdir()
    _designspace(root / "Fam.designspace", [("Up.ufo", 0, None)])
    status, out = studio.open_font_tree(str(root))
    assert status == 400 and "no master could be opened" in out["error"]
    assert not root.exists() and len(studio.fonts) == 1


def test_http_upload_of_a_designspace_folder(studio, family):
    """The local server's path: the same drop, as base64 files."""
    files = [{"path": os.path.relpath(os.path.join(d, f), family),
              "data": base64.b64encode(open(os.path.join(d, f), "rb").read()).decode()}
             for d, _, fs in os.walk(family) for f in fs]
    status, out = studio.dispatch("font", {"name": "Project", "files": files})
    assert status == 200 and len(out["choose"]) == 2
    status, out = studio.dispatch("font/designspace", {"path": "Project/Fam.designspace"})
    assert [c["name"] for c in out["state"]["fonts"]] == ["demo", "Fam Regular", "Fam Italic"]
