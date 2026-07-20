"""The surface vocabulary must stay in lockstep with what the parser accepts.

The point of :mod:`anchorsfactory.vocabulary` is to be the one place editors
read their completion tables from. These tests are the guard that makes that
promise real: every word the module offers is fed to the parser, and anything
it rejects fails here — which is exactly the drift that put a non-existent
``advance`` frame in the Studio's completion list.
"""

import pytest

from anchorsfactory import vocabulary as V
from anchorsfactory.dsl import DSLError, parse_dsl
from anchorsfactory.model import Axis, Frame, HAlign, Run, VEdge


# --------------------------------------------------------------------------- #
#  The tables themselves
# --------------------------------------------------------------------------- #

def test_tables_come_from_the_ir_enums():
    assert set(V.FRAMES) == {f.value for f in Frame}
    assert set(V.X_ALIGNS) == {a.value for a in HAlign}
    assert set(V.Y_EDGES) == {e.value for e in VEdge}
    assert set(V.RUNS) == {r.value for r in Run}


def test_frame_words_are_surface_not_ir():
    """``Frame.ADVANCE`` is an IR name; the word the user types is ``width``."""
    assert "width" in V.FRAMES
    assert "advance" not in V.FRAMES


def test_y_edges_read_bottom_up():
    assert V.Y_EDGES == ("bottom", "middle", "top")


def test_vocabulary_dict_is_json_serialisable():
    import json
    assert json.loads(json.dumps(V.as_dict()))["frames"] == list(V.FRAMES)


def test_package_attribute_is_the_module_not_a_function():
    """``from anchorsfactory import vocabulary`` must give this module — an
    exported function of the same name would shadow it."""
    import anchorsfactory
    assert anchorsfactory.vocabulary is V


# --------------------------------------------------------------------------- #
#  completions_after_dot
# --------------------------------------------------------------------------- #

def test_completions_are_axis_specific():
    assert V.completions_after_dot("box", axis="x") == V.X_ALIGNS
    assert V.completions_after_dot("box", axis="y") == V.Y_EDGES
    # slot unknown -> both sets, the union the Studio used to offer unconditionally
    assert set(V.completions_after_dot("box")) == set(V.X_ALIGNS) | set(V.Y_EDGES)


def test_outline_offers_runs_and_centroid():
    out = V.completions_after_dot("outline", axis="y")
    assert set(V.RUNS) <= set(out) and V.CENTROID in out and "top" in out


def test_width_has_no_vertical_form():
    """``ADVANCE`` is X-only in the IR, so it must not be offered on Y."""
    assert V.completions_after_dot("width", axis="y") == ()
    assert V.completions_after_dot("width") == V.X_ALIGNS
    assert V.completions_after_dot("width", axis="x") == V.X_ALIGNS


def test_component_and_glyph_heads():
    assert V.completions_after_dot("comp2") == V.FRAMES
    assert V.completions_after_dot("complast") == V.FRAMES
    assert V.completions_after_dot("compfoo") == ()
    assert V.completions_after_dot("$Adieresis") == V.Y_EDGES


def test_metrics_open_a_y_slot_only():
    """A font metric is a height term; the X grammar has no place for one."""
    assert set(V.METRICS) <= set(V.completions_for_slot("y"))
    assert not set(V.METRICS) & set(V.completions_for_slot("x"))
    assert set(V.METRICS) <= set(V.completions_for_slot())     # slot unknown → offered
    with pytest.raises(DSLError):
        _parse_slot("capHeight", "x")


def test_slot_completions_carry_the_frames_and_aligns():
    x = V.completions_for_slot("x")
    assert set(V.FRAMES) <= set(x) and set(V.X_ALIGNS) <= set(x)
    assert not (set(V.Y_EDGES) - set(V.X_ALIGNS)) & set(x)   # no Y-only edges on X


def test_unknown_head_offers_nothing():
    assert V.completions_after_dot("advance") == ()
    assert V.completions_after_dot("nonsense", axis="x") == ()


def test_axis_argument_accepts_the_enum_and_rejects_junk():
    assert V.completions_after_dot("box", axis=Axis.Y) == V.Y_EDGES
    with pytest.raises(ValueError):
        V.aligns_for("z")


# --------------------------------------------------------------------------- #
#  Anti-drift: everything offered must parse
# --------------------------------------------------------------------------- #

def _token(frame: str, word: str, axis: str) -> str:
    """Build a complete position token out of one completion word."""
    if word == V.CENTROID:
        return f"{frame}.{word}"
    if word in V.RUNS:                       # a run needs an alignment after it
        align = V.X_ALIGNS[0] if axis == "x" else V.Y_EDGES[0]
        return f"{frame}.{word}.{align}"
    return f"{frame}.{word}"


def _parse_slot(token: str, axis: str):
    """Parse a one-anchor document with *token* in the given slot."""
    other = "0"
    x, y = (token, other) if axis == "x" else (other, token)
    return parse_dsl([f"A = top ({x} {y})"])


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("frame", V.FRAMES)
def test_every_offered_word_parses(frame, axis):
    words = V.completions_after_dot(frame, axis=axis)
    for word in words:
        _parse_slot(_token(frame, word, axis), axis)     # must not raise


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("frame", V.FRAMES)
def test_words_withheld_on_an_axis_are_really_rejected(frame, axis):
    """The complement of the offer: a word the module holds back must be one the
    parser actually refuses — otherwise we are under-offering."""
    offered = set(V.completions_after_dot(frame, axis=axis))
    for word in set(V.X_ALIGNS) | set(V.Y_EDGES):
        if word in offered:
            continue
        with pytest.raises(DSLError):
            _parse_slot(_token(frame, word, axis), axis)


def test_component_qualifier_parses():
    doc = parse_dsl(["A = top (comp2.box.center comp2.box.top)"])
    assert doc.rules


def test_every_metric_parses_in_a_y_slot():
    for metric in V.METRICS:
        parse_dsl([f"A = top (0 {metric})"])


def test_fractional_frames_take_a_fraction():
    for frame in V.FRACTIONAL_FRAMES:
        parse_dsl([f"A = top ({frame}*1/3 0)"])
    with pytest.raises(DSLError):                        # outline is not one
        parse_dsl(["A = top (outline*1/3 0)"])


def test_at_sample_lines_parse_on_their_axis():
    for edge in V.AT_X_EDGES:                            # @ on X is a height
        parse_dsl([f"A = top (outline.left@{edge} 0)"])
        parse_dsl([f"A = top (outline.left@{edge}-10 0)"])
    for side in V.AT_Y_SIDES:                            # @ on Y is a column
        parse_dsl([f"A = top (0 outline.top@{side})"])
        parse_dsl([f"A = top (0 outline.top@{side}+10)"])


def test_every_directive_is_known_to_the_parser():
    values = {
        "!extends": "somebase",
        "!suffixes": "= .alt",
        "!shiftx": "= -15",
        "!propagate": "= composites",
    }
    assert set(values) == set(V.DIRECTIVES), "a directive lost its test payload"
    for directive, payload in values.items():
        parse_dsl([f"{directive} {payload}"])            # must not raise


def test_unknown_directive_names_the_known_ones():
    with pytest.raises(DSLError) as e:
        parse_dsl(["!nosuch = 1"])
    assert "!propagate" in str(e.value)


def test_every_propagate_value_parses():
    for value in V.PROPAGATE_VALUES:
        assert parse_dsl([f"!propagate = {value}"]).propagate == value


def test_suffix_keywords_parse():
    kw_all, kw_except, kw_none = V.SUFFIX_KEYWORDS
    parse_dsl([f"!suffixes = {kw_all}"])
    parse_dsl([f"!suffixes = {kw_all} {kw_except} .alt, .sc"])
    parse_dsl([f"!suffixes = {kw_none}"])


def test_every_operator_parses():
    for op in V.OPERATORS:
        parse_dsl([f"A {op} top (0 0)" if op != "-=" else "A -= top"])
