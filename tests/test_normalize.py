"""The saved UFO is passed through ufonormalizer by default (``--no-normalize``
keeps fontParts' own output)."""

import pytest

fontParts_world = pytest.importorskip("fontParts.world")
from ufonormalizer import normalizeGLIFString

from anchorsfactory.cli import main


def _font(path):
    font = fontParts_world.NewFont()
    font.info.unitsPerEm = 1000
    glyph = font.newGlyph("H")
    glyph.width = 600
    pen = glyph.getPen()
    for x in (50, 450):
        pen.moveTo((x, 0)); pen.lineTo((x + 100, 0)); pen.lineTo((x + 100, 700))
        pen.lineTo((x, 700)); pen.closePath()
    glyph.unicodes = [0x48]
    font.save(str(path))
    return path


def _run(tmp_path, *extra):
    src = _font(tmp_path / "F.ufo")
    rules = tmp_path / "r.anchors"
    rules.write_text("H = top (box.center 700)\n")
    out = tmp_path / "out.ufo"
    assert main([str(src), "--rules", str(rules), "-o", str(out), *extra]) == 0
    return out


def test_saved_ufo_is_normalized(tmp_path):
    out = _run(tmp_path)
    glif = (out / "glyphs" / "H_.glif").read_text()
    assert '<anchor name="top" x="300" y="700"/>' in glif
    assert normalizeGLIFString(glif) == glif
    assert not (out / "data" / "com.typesupply.ufoNormalizer.modTimes.txt").exists()


def test_no_normalize_keeps_the_writer_output(tmp_path):
    out = _run(tmp_path, "--no-normalize")
    glif = (out / "glyphs" / "H_.glif").read_text()
    assert normalizeGLIFString(glif) != glif       # fontParts' own layout differs
