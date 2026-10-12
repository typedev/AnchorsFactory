"""Writing the anchors the rules place back into the UFOs ("write anchors").

The Studio computes every master with its own ``!if`` context, exactly as the
masters comparison does, and keeps only the glyphs whose anchors change. Each
such glyph's ``.glif`` is read from the UFO the font was opened from, its
anchors replaced (an anchor that keeps its name keeps its ``identifier`` and
``color``), and the text passed through ``ufonormalizer``. In a normalized UFO
the diff is then the anchors alone; an unnormalized file comes out normalized.

Nothing here writes into the user's folder: :func:`plan_master` returns the new
texts, and the caller (the page, through the File System Access API, or the
local server for a font opened from a path) writes them.
"""

from __future__ import annotations

import io
import os
import zipfile

from fontTools.pens.recordingPen import RecordingPointPen
from fontTools.ufoLib import UFOReader
from fontTools.ufoLib.glifLib import readGlyphFromString, writeGlyphToString

from ..apply import compute_document, validate_document
from ..conditions import RuleContext
from .render import resolve_stack

try:                                     # a Studio dependency (the [dev] extra)
    from ufonormalizer import normalizeGLIFString
except ImportError:                      # pragma: no cover - reported on use
    normalizeGLIFString = None


class _Glyph:
    """What glifLib reads a glyph into."""


def _same(current, new) -> bool:
    """Same anchors, whatever their order."""
    key = lambda a: (a[0] or "", round(float(a[1]), 3), round(float(a[2]), 3))
    return sorted(map(key, current)) == sorted(map(key, new))


def _num(v):
    f = float(v)
    return int(f) if f.is_integer() else f


def rewrite_glif(data: bytes, glyph_name: str, anchors) -> str:
    """The ``.glif`` *data* with its anchors replaced by *anchors*
    (``[(name, x, y), ...]``), normalized."""
    if normalizeGLIFString is None:
        raise RuntimeError("writing anchors needs ufonormalizer (pip install ufonormalizer)")
    glyph, pen = _Glyph(), RecordingPointPen()
    readGlyphFromString(data, glyph, pen)
    version = getattr(glyph, "formatVersion", None)
    if version is not None and getattr(version, "major", version) == 1:
        raise ValueError(f"{glyph_name}: a format-1 (UFO 2) .glif; convert the font to UFO 3 first")
    kept = {a.get("name"): a for a in getattr(glyph, "anchors", []) or []}
    out = []
    for name, x, y in anchors:
        a = {"name": name, "x": _num(x), "y": _num(y)}
        for attr in ("identifier", "color"):
            if attr in kept.get(name, {}):
                a[attr] = kept[name][attr]
        out.append(a)
    glyph.anchors = out
    text = writeGlyphToString(glyph_name, glyph, pen.replay, formatVersion=version, validate=False)
    return normalizeGLIFString(text)


def plan_master(font, layers, context: RuleContext | None = None) -> dict:
    """What writing the rules' anchors into *font* changes.

    Returns ``{"glyphs": [name, ...], "files": [{"file", "glyph", "text",
    "original", "anchors"}], "problems": [...]}`` with ``file`` relative to the
    UFO (``glyphs/H_.glif``). Rules that do not resolve raise ``ValueError``.
    """
    context = (context or RuleContext()).for_font(font)
    doc = resolve_stack(layers, context)
    problems = validate_document(doc)
    if problems:
        raise ValueError("; ".join(problems))
    placed = compute_document(font, doc)
    reader = UFOReader(font.path, validate=False)
    glyphset = reader.getGlyphSet(validateRead=False)
    files, glyphs, issues = [], [], []
    for name in sorted(placed):
        new = [(n, x, y) for n, x, y in placed[name]]
        current = [(a.name, a.x, a.y) for a in font[name].anchors]
        if _same(current, new):
            continue
        filename = glyphset.contents.get(name)
        if filename is None:
            issues.append(f"{name}: not in the font's default layer on disk")
            continue
        original = glyphset.getGLIF(name)
        try:
            text = rewrite_glif(original, name, new)
        except ValueError as exc:
            issues.append(str(exc))
            continue
        glyphs.append(name)
        files.append({"file": f"{glyphset.dirName}/{filename}", "glyph": name, "text": text,
                      "original": original.decode("utf-8"), "anchors": new})
    return {"glyphs": glyphs, "files": files, "problems": issues}


def commit_master(font, files, *, write_ufo: bool) -> None:
    """Make *font* match what was written: its glyphs get the new anchors in
    memory and, with *write_ufo*, the ``.glif`` texts go into ``font.path``
    (the session's own copy, or the UFO itself for a font opened from a path)."""
    for f in files:
        glyph = font[f["glyph"]]
        glyph.clearAnchors()
        for name, x, y in f["anchors"]:
            glyph.appendAnchor(name, (x, y))
        if write_ufo:
            path = os.path.join(font.path, *f["file"].split("/"))
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(f["text"])


def zip_files(files) -> bytes:
    """``[(path, text), ...]`` as a zip archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in files:
            z.writestr(path, text)
    return buf.getvalue()
