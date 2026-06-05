"""``compute_document`` is the functional core; ``apply_document`` writes it.

The contract is parity: whatever ``compute_document`` returns is exactly what
``apply_document(..., clear=True)`` writes, glyph-for-glyph. The first test
proves that on a tiny in-memory font (no ``ufo-test/`` fixture needed) while
exercising the orchestration ``compute_document`` owns — suffix expansion (with
per-target sampling), ``shift_x``, rounding, and the within-document same-name
dedup. The second re-checks parity on a real font with the bundled ``default``
preset, and skips when no font is present.
"""

from pathlib import Path

import pytest

from anchorsfactory.apply import apply_document, compute_document
from anchorsfactory.model import (
    AnchorSpec, XAbs, YAbs, X, Frame, HAlign,
    GlyphName, Glob, Op, Document,
)


# --- in-memory font double ------------------------------------------------- #
class _Anchor:
    def __init__(self, name, x, y):
        self.name, self.x, self.y = name, x, y


class _Glyph:
    def __init__(self, name, width=0, unicodes=()):
        self.name = name
        self.width = width
        self.unicodes = list(unicodes)
        self.bounds = (0.0, 0.0, float(width), 0.0)
        self.anchors = []

    def appendAnchor(self, name, pos):
        self.anchors.append(_Anchor(name, pos[0], pos[1]))

    def removeAnchor(self, anchor):
        self.anchors.remove(anchor)


class _Info:
    italicAngle = 0


class _Font:
    def __init__(self, glyphs):
        self._glyphs = {g.name: g for g in glyphs}
        self.info = _Info()

    def __iter__(self):
        return iter(self._glyphs.values())

    def __contains__(self, name):
        return name in self._glyphs

    def __getitem__(self, name):
        return self._glyphs[name]


def _make_font():
    return _Font([
        _Glyph("a", width=600, unicodes=[0x61]),
        _Glyph("a.sc", width=400),     # suffix target, narrower → proves per-target sampling
        _Glyph("b", width=500, unicodes=[0x62]),
        _Glyph("z", width=500),        # unmatched → never appears in output
    ])


def _written(font):
    return {
        g.name: [(a.name, a.x, a.y) for a in g.anchors]
        for g in font if g.anchors
    }


def _doc():
    # `a`: two `top` specs in one REPLACE (last wins), then a `+= top` overriding
    # again, plus a distinct `bottom`. `b*`: a single centred top.
    a_rule = (GlyphName("a"), Op.REPLACE, [
        AnchorSpec("top", XAbs(100.4), YAbs(700)),
        AnchorSpec("top", XAbs(200.6), YAbs(710)),     # same name → dedup target
        AnchorSpec("bottom", XAbs(100), YAbs(0)),
    ])
    a_add = (GlyphName("a"), Op.ADD, [
        AnchorSpec("top", X(Frame.ADVANCE, HAlign.CENTER), YAbs(720)),  # width-dependent X
    ])
    b_rule = (Glob("b*"), Op.REPLACE, [
        AnchorSpec("center", X(Frame.ADVANCE, HAlign.CENTER), YAbs(250)),
    ])
    return Document(rules=[a_rule, a_add, b_rule], shift_x=10, suffixes=["", ".sc"])


def test_compute_matches_apply_parity():
    doc = _doc()
    computed = compute_document(_make_font(), doc)

    target = _make_font()
    apply_document(target, doc, clear=True)

    assert computed == _written(target)


def test_compute_does_not_mutate_font():
    font = _make_font()
    compute_document(font, _doc())
    assert all(not g.anchors for g in font)


def test_within_rule_replace_last_wins_and_shift_and_round():
    computed = compute_document(_make_font(), _doc())
    # `a`: dedup keeps the last `top` (the ADD's ADVANCE-centre on the 600u
    # glyph = 300, +10 shift), at the ADD's Y; `bottom` survives untouched.
    assert computed["a"] == [("bottom", 110, 0), ("top", 310, 720)]
    # `a.sc` samples the *suffix target* (width 400) → 200 + 10 shift.
    assert computed["a.sc"] == [("bottom", 110, 0), ("top", 210, 720)]


def test_replace_false_keeps_duplicate_names():
    computed = compute_document(_make_font(), _doc(), replace=False)
    names = [n for n, _, _ in computed["a"]]
    assert names.count("top") == 3          # no dedup → all three `top` specs kept


def test_unmatched_glyph_absent():
    computed = compute_document(_make_font(), _doc())
    assert "z" not in computed


# --- real-font parity (skips without a fixture) ---------------------------- #
_UFOS = sorted(Path("ufo-test").glob("*.ufo"))


@pytest.mark.skipif(not _UFOS, reason="no test UFO available in ufo-test/")
@pytest.mark.parametrize("round_coords", [True, False])
def test_real_font_parity_default_preset(round_coords):
    fontParts_world = pytest.importorskip("fontParts.world")
    from anchorsfactory.runner import load_document

    doc = load_document("default")
    font = fontParts_world.OpenFont(str(_UFOS[0]))

    computed = compute_document(font, doc, round_coords=round_coords)
    apply_document(font, doc, clear=True, round_coords=round_coords)
    written = {
        g.name: [(a.name, a.x, a.y) for a in g.anchors]
        for g in font if g.anchors
    }
    assert computed == written
