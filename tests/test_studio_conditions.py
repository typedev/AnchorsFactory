"""Studio and conditional blocks: each loaded font stands for a master whose
location / style name the `!if` blocks see — in the rule layers and in the
constructions — with the dropped lines reported for dimming."""

import pytest

pytest.importorskip("fontParts.world")

from rulesets import rules_text
from anchorsfactory.conditions import RuleContext
from anchorsfactory.studio.compose import build_composite_view, masters_report
from anchorsfactory.studio.demo import build_demo_font
from anchorsfactory.studio.render import build_view
from anchorsfactory.studio.server import (
    Studio, _font_card, entry_context, location_text, parse_location_text,
)

UPRIGHT = RuleContext(xvalues={"ital": 0})
ITALIC = RuleContext(xvalues={"ital": 1})

RULES = """\
H = top (100 700)
!if ital.xvalue == 1
H += extra (50 0)
!endif
"""


@pytest.fixture(scope="module")
def font():
    return build_demo_font()


def _names(view, glyph="H"):
    return sorted(a["name"] for a in view["glyphs"][glyph]["anchors"])


def test_rules_inside_if_reach_the_view(font):
    # regression: resolve_stack rebuilt a plain Document and silently dropped
    # everything inside an !if block
    layers = [{"name": "default", "text": RULES}]
    assert _names(build_view(font, layers, UPRIGHT)) == ["top"]
    assert _names(build_view(font, layers, ITALIC)) == ["extra", "top"]


def test_view_reports_inactive_lines_per_layer(font):
    layers = [{"name": "base", "text": "H = top (1 2)"},
              {"name": "over", "text": RULES}]
    assert build_view(font, layers, UPRIGHT)["inactive"] == {"1": [3]}
    assert build_view(font, layers, ITALIC)["inactive"] == {}


def test_extra_line_numbers_point_into_the_layer(font):
    view = build_view(font, [{"name": "default", "text": RULES}], ITALIC)
    extra = next(a for a in view["glyphs"]["H"]["anchors"] if a["name"] == "extra")
    assert (extra["layer"], extra["line"]) == (0, 3)


def test_missing_axis_is_a_problem_with_layer_and_line(font):
    view = build_view(font, [{"name": "default", "text": RULES}], RuleContext())
    assert not view["ok"]
    assert view["problems"][0].startswith("default: line 2: no xvalue for axis 'ital'")


def test_style_name_comes_from_the_font_unless_overridden(font):
    text = '!if "Regular" in styleName\nH = top (1 2)\n!endif\n'
    layers = [{"name": "default", "text": text}]
    assert _names(build_view(font, layers)) == ["top"]           # demo fontinfo: Regular
    assert build_view(font, layers, RuleContext(style_name="Bold"))["glyphs"] == {}


GC = """\
!if ital.xvalue == 0
aacute = a + acute@top
!else
aacute = o + acute@top
!endif
"""


def test_composites_follow_the_master():
    layers = [{"name": "base", "text": rules_text("default")}]
    up = build_composite_view(build_demo_font(), layers, GC, UPRIGHT)
    it = build_composite_view(build_demo_font(), layers, GC, ITALIC)
    base = lambda r: r["composites"]["aacute"]["components"][0]["base"]
    assert base(up) == "a" and base(it) == "o"


def test_construction_condition_error_is_routed_to_the_gc_editor():
    layers = [{"name": "base", "text": rules_text("default")}]
    r = build_composite_view(build_demo_font(), layers, GC, RuleContext())
    assert not r["ok"]
    assert r["problems"][0].startswith("constructions: line 1: no xvalue")


def test_masters_report_lists_structural_differences():
    layers = [{"name": "base", "text": rules_text("default")},
              {"name": "over", "text": RULES}]
    r = masters_report([("Upright", build_demo_font(), UPRIGHT),
                        ("Italic", build_demo_font(), ITALIC)], layers, GC)
    assert r["ok"] and r["masters"] == ["Upright", "Italic"]
    text = "\n".join(r["warnings"])
    assert "H: anchor sets differ" in text
    assert "aacute: components differ" in text


def test_masters_report_keeps_going_past_a_broken_master():
    layers = [{"name": "default", "text": RULES}]
    r = masters_report([("ok", build_demo_font(), ITALIC),
                        ("bad", build_demo_font(), RuleContext())], layers, "")
    assert not r["ok"] and r["masters"] == ["ok"]
    assert r["errors"][0].startswith("bad: default: line 2")


# --------------------------------------------------------------------------- #
#  Server-side state: a font card's master location
# --------------------------------------------------------------------------- #

def test_parse_location_text():
    assert parse_location_text("ital.xvalue=1, wght.uservalue = 700;opsz.xvalue=-1.5") == (
        {"ital": 1.0, "opsz": -1.5}, {"wght": 700.0})
    assert parse_location_text("") == ({}, {})
    with pytest.raises(ValueError, match="cannot read 'ital=1'"):
        parse_location_text("ital=1")
    with pytest.raises(ValueError, match="cannot read 'junk'"):
        parse_location_text("ital.xvalue=1 junk")


def test_studio_font_context_round_trip(font):
    st = Studio(font, RULES, "Regular")
    assert st.context == RuleContext()
    st.set_context(0, "ital.xvalue=1", "Italic")
    assert st.context.axis_value("ital", "xvalue") == 1
    assert st.context.style_name == "Italic"
    card = st.state["fonts"][0]
    assert card["location"] == "ital.xvalue=1" and card["styleName"] == "Italic"
    assert card["fontStyleName"] == "Regular"
    with pytest.raises(ValueError):
        st.set_context(0, "ital=1", None)
    assert st.context.axis_value("ital", "xvalue") == 1        # unchanged on error


def test_designspace_base_context_and_overrides(font):
    base = RuleContext(style_name="Bold", xvalues={"weight": 100},
                       uservalues={"weight": 700}, axis_aliases={"wght": "weight"},
                       axes=frozenset({"wght", "weight"}))
    entry = {"base": base, "location": None, "styleName": None}
    assert entry_context(entry) is base
    card = _font_card(font, "Bold", entry)
    assert card["designspace"] and card["styleName"] == "Bold"
    assert card["location"] == location_text(base) == "weight.xvalue=100, weight.uservalue=700"
    # a typed location replaces the coordinates but keeps the axis aliases
    ctx = entry_context({**entry, "location": "wght.xvalue=0"})
    assert ctx.axis_value("weight", "xvalue") == 0 and ctx.axes == base.axes
