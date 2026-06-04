"""Tests for user-error protection: pre-flight validation and graceful fallbacks."""

from pathlib import Path

import pytest

from anchorsfactory.apply import validate_document
from anchorsfactory.dsl import parse_dsl
from anchorsfactory.geometry import resolve_y
from anchorsfactory.model import Y, VEdge

fontParts_world = pytest.importorskip("fontParts.world")


# --- pre-flight label validation ------------------------------------------- #
def test_validate_clean_document():
    doc = parse_dsl(["@a = top (box.center capHeight)", "A = @a"])
    assert validate_document(doc) == []


def test_validate_reports_undefined_label_in_rule():
    doc = parse_dsl(["A = @nope"])
    problems = validate_document(doc)
    assert problems and "@nope" in problems[0]


def test_validate_reports_undefined_label_in_label_body():
    doc = parse_dsl(["@a = @missing", "A = @a"])
    assert any("@missing" in p for p in validate_document(doc))


# --- graceful fallback for a missing reference glyph ----------------------- #
_UFOS = sorted(Path("ufo-test").glob("*.ufo"))


@pytest.mark.skipif(not _UFOS, reason="no test UFO available")
def test_missing_reference_glyph_falls_back_to_zero():
    font = fontParts_world.OpenFont(str(_UFOS[0]))
    # a height referencing a glyph that does not exist must not raise
    assert resolve_y(font, Y("NoSuchGlyph", VEdge.TOP)) == 0.0
