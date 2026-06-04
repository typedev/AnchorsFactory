"""Round-trip: legacy text -> IR -> new DSL text -> IR must be equivalent."""

from pathlib import Path

import pytest

from anchorsfactory.parser import parse_document
from anchorsfactory.dsl import parse_dsl
from anchorsfactory.convert import render_document, verify_conversion


LEGACY = [
    "@=top:centerpos:$H,bottom:centerpos:0",
    "@desc=desc:rightinter:0",
    "@bar=bar:center:$H*1/2",
    "@_=_top:bottomcenter:$H",
    "A=@,@desc",
    "L=top:left:$H,caron:right:$H,@bar",
    "&0413=@,@desc",
    "acute=@_",
    "hyphen=_bar:center:$endash-",
]


def test_legacy_to_dsl_preserves_rules():
    legacy_doc = parse_document(LEGACY)
    new_text = render_document(legacy_doc)
    new_doc = parse_dsl(new_text.splitlines())
    # rules carry flat specs after label expansion; they must match exactly
    assert new_doc.rules == legacy_doc.rules


def test_dsl_text_is_parseable_and_uses_new_syntax():
    new_text = render_document(parse_document(LEGACY))
    assert "box.center" in new_text
    assert "outline.right" in new_text
    assert "U+0413" in new_text
    assert "$endash.middle" in new_text          # legacy $endash- -> .middle
    assert ":" not in new_text.replace("# ", "")  # no legacy colon triples remain


@pytest.mark.parametrize("legacy", sorted(str(p) for p in Path(".").glob("*-anchors-list*.txt"))
                         + sorted(str(p) for p in Path(".").glob("anchors-list*.txt")))
def test_real_legacy_files_convert_losslessly(legacy):
    """Every legacy rule file in the repo round-trips with no loss."""
    assert verify_conversion(legacy) == []
