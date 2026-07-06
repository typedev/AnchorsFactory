"""Bundled script presets (``devanagari``, ``hebrew``, ``thai``).

Each preset must be discoverable by bare name, parse, and pass the pre-flight
``validate_document`` check (labels/variables resolve, axes are consistent, no
outline axis cycles) — all font-independent.

The accuracy smoke tests are optional: they run only when the open script
fonts used during rule research are present (point ``AF_SCRIPT_FONTS`` at a
directory containing the Anek / Noto Thai checkouts), and assert that more
than half of the same-named designer anchors are reproduced within 1% of UPM.
No confidential fixture is involved — both fonts are OFL, fetched separately.
"""

import math
import os
from pathlib import Path

import pytest

from anchorsfactory import presets
from anchorsfactory.apply import compute_document, validate_document
from anchorsfactory.dsl import parse_dsl
from anchorsfactory.runner import load_document

SCRIPT_PRESETS = ["devanagari", "hebrew", "thai"]


# --- discovery & loading ---------------------------------------------------- #
@pytest.mark.parametrize("name", SCRIPT_PRESETS)
def test_script_preset_is_bundled(name):
    assert name in presets.list_presets()
    assert presets.is_preset(name)


@pytest.mark.parametrize("name", SCRIPT_PRESETS)
def test_script_preset_parses(name):
    doc = parse_dsl(presets.preset_text(name).splitlines())
    assert doc.rules and doc.labels and doc.variables


@pytest.mark.parametrize("name", SCRIPT_PRESETS)
def test_script_preset_loads_and_validates(name):
    doc = load_document(name)          # by bare preset name, like the CLI
    assert doc.rules
    assert validate_document(doc) == []


@pytest.mark.parametrize("name", SCRIPT_PRESETS)
def test_script_preset_extendable(name, tmp_path):
    # a user file retunes a &variable on top of the preset — must still validate
    f = tmp_path / "mine.af"
    f.write_text(f"!extends {name}\n&aboveDrop = 30\n&headDrop = 0\n")
    doc = load_document(str(f))
    assert validate_document(doc) == []


# --- optional accuracy smoke (skips without the research fonts) ------------- #
_FONTS = Path(os.environ.get(
    "AF_SCRIPT_FONTS",
    "/tmp/claude-1000/-home-alexander-WORK-AnchorsFactory/"
    "7c8b2510-5753-4bbd-8385-39423e9183c4/scratchpad/fonts",
))

_ACCURACY_CASES = [
    ("devanagari",
     "Anek/sources/AnekDevanagari/Masters/AnekDevanagari-Medium.ufo"),
    ("thai",
     "thai/sources/NotoSansThai-Regular.ufo"),
]


@pytest.mark.parametrize("preset,rel", _ACCURACY_CASES,
                         ids=[c[0] for c in _ACCURACY_CASES])
def test_script_preset_accuracy_smoke(preset, rel):
    ufo = _FONTS / rel
    if not ufo.is_dir():
        pytest.skip(f"research font not available: {ufo}")
    fontparts_world = pytest.importorskip("fontParts.world")

    font = fontparts_world.OpenFont(str(ufo))
    doc = load_document(preset)
    computed = compute_document(font, doc, on_error="collect")

    upm = font.info.unitsPerEm or 1000
    tol = upm / 100.0                  # 1% of UPM
    total = hits = 0
    for glyph in font:
        produced = {n: (x, y) for n, x, y in computed.get(glyph.name, [])}
        for a in glyph.anchors:        # designer anchors sharing a produced name
            if a.name in produced:
                total += 1
                px, py = produced[a.name]
                if math.hypot(a.x - px, a.y - py) <= tol:
                    hits += 1
    assert total >= 20, f"too few comparable anchors ({total}) — selector mismatch?"
    assert hits / total > 0.5, f"{preset}: {hits}/{total} within {tol:g} units"
