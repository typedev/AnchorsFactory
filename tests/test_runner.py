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

RULES = "default-anchors-list.txt"


@pytest.fixture
def ufo_copy(tmp_path):
    dst = tmp_path / "probe.ufo"
    shutil.copytree(_UFOS[0], dst)
    return str(dst)


def _anchor_map(ufo_path):
    font = fontParts_world.OpenFont(ufo_path)
    return {(g.name, a.name): (a.x, a.y) for g in font for a in g.anchors}


def test_default_save_is_safe(ufo_copy):
    """Default run never overwrites the source; output is *_anchored.ufo."""
    before = _anchor_map(ufo_copy)
    out = process_ufo(ufo_copy, RULES)
    assert out.endswith("_anchored.ufo")
    assert Path(out).is_dir()
    assert Path(out) != Path(ufo_copy)
    assert _anchor_map(ufo_copy) == before          # source untouched on disk


def test_round_coords_yield_integers(ufo_copy):
    out = process_ufo(ufo_copy, RULES, round_coords=True)
    for (_, _), (x, y) in _anchor_map(out).items():
        assert x == int(x) and y == int(y)


def test_no_round_keeps_fractions(ufo_copy):
    out = process_ufo(ufo_copy, RULES, round_coords=False)
    coords = _anchor_map(out).values()
    assert any(x != int(x) for x, _ in coords), "expected some fractional X from outline anchors"


def test_in_place_overwrites_source(ufo_copy):
    out = process_ufo(ufo_copy, RULES, in_place=True)
    assert Path(out) == Path(ufo_copy)


def test_backup_written_outside_cwd(ufo_copy, tmp_path):
    bdir = tmp_path / "backup"
    process_ufo(ufo_copy, RULES, backup_dir=str(bdir))
    backups = list(bdir.glob("*.anchors-backup.txt"))
    assert backups and backups[0].read_text().strip(), "backup should be non-empty"
