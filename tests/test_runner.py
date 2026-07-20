"""Tests for the file-IO runner: safe save, rounding, in-place, backup.

Operate on tmp copies of a globbed test UFO; skip if none is present.
"""

import shutil
from pathlib import Path

import pytest

fontParts_world = pytest.importorskip("fontParts.world")

from anchorsfactory.runner import process_ufo

_UFOS = sorted(Path("ufo-test").glob("*.ufo"))
if not _UFOS:
    pytest.skip("no test UFO available in ufo-test/", allow_module_level=True)

from rulesets import RULES_DIR, SEARCH_PATHS

RULES = str(RULES_DIR / "default.anchors")   # a sample set, by path


@pytest.fixture
def ufo_copy(tmp_path):
    dst = tmp_path / "probe.ufo"
    shutil.copytree(_UFOS[0], dst)
    return str(dst)


def _anchor_map(ufo_path):
    font = fontParts_world.OpenFont(ufo_path)
    return {(g.name, a.name): (a.x, a.y) for g in font for a in g.anchors}


def test_rules_resolve_by_name_off_a_search_path(ufo_copy):
    # the other addressing mode: a bare set name, resolved by process_ufo itself
    out = process_ufo(ufo_copy, "default", search_paths=SEARCH_PATHS)
    assert Path(out).exists()


def test_default_save_is_safe(ufo_copy):
    """Default run never overwrites the source; output is *_anchored.ufo."""
    before = _anchor_map(ufo_copy)
    out = process_ufo(ufo_copy, RULES)
    assert out.endswith("_anchored.ufo")
    assert Path(out).is_dir()
    assert Path(out) != Path(ufo_copy)
    assert _anchor_map(ufo_copy) == before          # source untouched on disk


def _written_anchor_map(src, out):
    """Anchors the run actually placed — glyphs the rules did not select keep
    whatever anchors the source font already had (``apply`` leaves them alone),
    and those are not this module's to assert on."""
    before, after = _anchor_map(src), _anchor_map(out)
    return {k: v for k, v in after.items() if before.get(k) != v}


def test_round_coords_yield_integers(ufo_copy):
    out = process_ufo(ufo_copy, RULES, round_coords=True)
    written = _written_anchor_map(ufo_copy, out)
    assert written, "the preset placed nothing on the test font"
    for (_, _), (x, y) in written.items():
        assert x == int(x) and y == int(y)


def test_no_round_keeps_fractions(ufo_copy):
    out = process_ufo(ufo_copy, RULES, round_coords=False)
    coords = _written_anchor_map(ufo_copy, out).values()
    assert any(x != int(x) for x, _ in coords), "expected some fractional X from outline anchors"


def test_in_place_overwrites_source(ufo_copy):
    out = process_ufo(ufo_copy, RULES, in_place=True)
    assert Path(out) == Path(ufo_copy)


def test_backup_written_outside_cwd(ufo_copy, tmp_path):
    bdir = tmp_path / "backup"
    process_ufo(ufo_copy, RULES, backup_dir=str(bdir))
    backups = list(bdir.glob("*.anchors-backup.txt"))
    assert backups and backups[0].read_text().strip(), "backup should be non-empty"
