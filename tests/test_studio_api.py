"""The Studio API facade: the one surface the local server and the web
worker both call (``Studio.dispatch``), plus the worker's own font loader."""

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
    assert set(METHODS) == {"state", "allglyphs", "compute", "font", "font/activate",
                            "font/remove", "font/context", "masters"}


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
    opens it from there; *warm* fills the outline caches during the load."""
    root = tmp_path / "drop"
    root.mkdir()
    build_demo_font().save(str(tmp_path / "Demo.ufo"))
    if zipped:
        with zipfile.ZipFile(root / "Demo.ufoz", "w") as z:
            for f in (tmp_path / "Demo.ufo").rglob("*"):
                z.write(f, f.relative_to(tmp_path))
    else:
        shutil.copytree(tmp_path / "Demo.ufo", root / "Demo.ufo")
    status, out = studio.open_font_tree(str(root), warm=True)
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
