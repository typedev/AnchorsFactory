"""Tests for bundled presets and !extends inheritance (load_document)."""

from pathlib import Path

import pytest

from anchorsfactory import presets
from anchorsfactory.runner import load_document, _merge
from anchorsfactory.apply import accumulate
from anchorsfactory.dsl import parse_dsl


# --- presets are bundled and readable as package data ---------------------- #
def test_presets_available():
    names = presets.list_presets()
    assert "default" in names and "default-italics" in names


def test_is_preset_vs_path():
    assert presets.is_preset("default")
    assert not presets.is_preset("default.af")     # has extension -> a path
    assert not presets.is_preset("a/b")            # has separator -> a path


def test_preset_text_parses():
    doc = parse_dsl(presets.preset_text("default").splitlines())
    assert doc.rules and doc.labels


# --- !extends resolution & merge ------------------------------------------- #
def test_extends_preset_then_override(tmp_path):
    f = tmp_path / "my.af"
    f.write_text(
        "!extends default\n"
        "U+0413 += extra (box.center 0)\n"     # Г: defaults + an extra anchor
    )
    doc = load_document(str(f))
    names = [s.name for s in accumulate(doc, "Ge", [0x0413])]
    assert "extra" in names
    assert "top" in names                       # inherited from the default @


def test_extends_relative_path(tmp_path):
    (tmp_path / "base.af").write_text("@ = top (box.center $H)\nU+0041 = @\n")
    child = tmp_path / "child.af"
    child.write_text("!extends base.af\nU+0041 += hook (outline.right 0)\n")
    doc = load_document(str(child))
    assert [s.name for s in accumulate(doc, "A", [0x0041])] == ["top", "hook"]


def test_extends_cycle_detected(tmp_path):
    (tmp_path / "a.af").write_text("!extends b.af\nU+0041 = top (box.center $H)\n")
    (tmp_path / "b.af").write_text("!extends a.af\nU+0042 = top (box.center $H)\n")
    with pytest.raises(ValueError):
        load_document(str(tmp_path / "a.af"))


def test_merge_child_label_wins():
    base = parse_dsl(["@ = top (box.center $H)", "U+0041 = @"])
    child = parse_dsl(["@ = bottom (box.center 0)"])     # redefine the label
    merged = _merge(base, child)
    # late binding: the inherited A rule now resolves @ to the child's definition
    assert [s.name for s in accumulate(merged, "A", [0x0041])] == ["bottom"]
