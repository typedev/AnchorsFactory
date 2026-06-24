"""Tests for &variables: named axis expressions, resolved late like labels."""

import pytest

from anchorsfactory.dsl import parse_dsl, DSLError
from anchorsfactory.apply import accumulate, validate_document
from anchorsfactory.model import (
    Frame, HAlign, VEdge, Frac,
    X, XAbs, Y, YAbs, FontMetric, YSum, AnchorSpec, VarRef, Document,
)
from anchorsfactory.runner import _merge


def _spec(lines, glyph="A"):
    """Accumulate the single anchor a one-rule document places on *glyph*."""
    doc = parse_dsl(lines)
    specs = accumulate(doc, glyph, [])
    assert len(specs) == 1
    return specs[0]


# --- definition parsing ----------------------------------------------------- #
def test_variable_parsed_into_table():
    doc = parse_dsl(["&mid = capHeight*1/2+xHeight*1/2"])
    assert doc.variables["&mid"] == YSum(
        (FontMetric("capHeight", Frac(1, 2)), FontMetric("xHeight", Frac(1, 2)))
    )


def test_x_variable_parsed_as_x():
    doc = parse_dsl(["&inkc = outline.center@xHeight"])
    assert doc.variables["&inkc"] == X(Frame.OUTLINE, HAlign.CENTER, at=FontMetric("xHeight"))


def test_alias_to_another_variable():
    doc = parse_dsl(["&a = capHeight", "&b = &a"])
    assert doc.variables["&b"] == VarRef("&a")


def test_bad_variable_name_rejected():
    with pytest.raises(DSLError):
        parse_dsl(["&bad name = capHeight"])


def test_variable_only_supports_replace():
    with pytest.raises(DSLError):
        parse_dsl(["&m += capHeight"])


# --- substitution (Y / X / number) ----------------------------------------- #
def test_y_variable_substituted_in_anchor():
    spec = _spec(["&mid = capHeight*1/2+xHeight*1/2", "A = bar (width.center &mid)"])
    assert spec == AnchorSpec(
        "bar", X(Frame.ADVANCE, HAlign.CENTER),
        YSum((FontMetric("capHeight", Frac(1, 2)), FontMetric("xHeight", Frac(1, 2)))),
    )


def test_x_variable_substituted_in_anchor():
    spec = _spec(["&inkc = outline.center@xHeight", "A = top (&inkc capHeight)"])
    assert spec.x == X(Frame.OUTLINE, HAlign.CENTER, at=FontMetric("xHeight"))
    assert spec.y == FontMetric("capHeight")


def test_bare_number_is_axis_polymorphic():
    spec = _spec(["&n = 50", "A = dot (&n &n)"])
    assert spec.x == XAbs(50) and spec.y == YAbs(50)


# --- composition (inside a sum / inside @) ---------------------------------- #
def test_variable_as_sum_term():
    spec = _spec(["&base = capHeight", "A = top (box.center &base+xHeight*1/12)"])
    assert spec.y == YSum((FontMetric("capHeight"), FontMetric("xHeight", Frac(1, 12))))


def test_variable_as_sample_height():
    spec = _spec(["&mid = xHeight", "A = top (outline.center@&mid capHeight)"])
    assert spec.x == X(Frame.OUTLINE, HAlign.CENTER, at=FontMetric("xHeight"))


def test_alias_chain_resolves():
    spec = _spec(["&a = capHeight", "&b = &a", "A = x (width.center &b)"])
    assert spec.y == FontMetric("capHeight")


# --- late binding: last definition wins, even across !extends --------------- #
def test_redefinition_in_file_last_wins():
    spec = _spec(["&m = capHeight", "A = x (width.center &m)", "&m = xHeight"])
    assert spec.y == FontMetric("xHeight")


def test_extends_child_overrides_variable():
    base = parse_dsl(["&m = capHeight", "A = top (box.center &m)"])
    child = parse_dsl(["&m = xHeight"])
    merged = _merge(base, child)
    spec = accumulate(merged, "A", [])[0]
    assert spec.y == FontMetric("xHeight")   # base rule sees the merged table


# --- validation: axis / undefined / cycle ----------------------------------- #
def test_validate_x_variable_in_y_slot():
    doc = parse_dsl(["&x = box.center", "A = top (width.center &x)"])
    problems = validate_document(doc)
    assert problems and "X expression" in problems[0]


def test_validate_y_variable_in_x_slot():
    doc = parse_dsl(["&y = capHeight", "A = top (&y capHeight)"])
    problems = validate_document(doc)
    assert problems and "Y expression" in problems[0]


def test_validate_undefined_variable():
    doc = parse_dsl(["A = top (width.center &nope)"])
    assert any("undefined variable &nope" in p for p in validate_document(doc))


def test_validate_direct_cycle():
    doc = parse_dsl(["&a = &b", "&b = &a"])
    assert any("cyclic" in p and "&a" in p for p in validate_document(doc))


def test_validate_self_cycle():
    doc = parse_dsl(["&a = &a"])
    assert any("cyclic" in p for p in validate_document(doc))


def test_validate_clean_variable_document():
    doc = parse_dsl([
        "&mid = capHeight*1/2+xHeight*1/2",
        "&inkc = outline.center@xHeight",
        "A = top (&inkc &mid)",
    ])
    assert validate_document(doc) == []
