"""Studio adapter: serialize GlyphConstruction composites to the browser's JSON.

The assembly itself lives in the library core (:mod:`anchorsfactory.composites`),
which is renderer-neutral and returns live ``ConstructionGlyph`` objects plus each
construction's source line. This adapter owns the *web* specifics: it applies the
computed anchors onto a throwaway **copy** of the font (GlyphConstruction reads
``glyph.anchors``), then draws each composite's components to SVG paths and
records the anchor-join points — the shape ``app.js`` renders.
"""

from __future__ import annotations

import contextlib
import io
import logging

from fontTools.misc.transform import Transform
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.svgPathPen import SVGPathPen

from ..apply import apply_document, validate_document
from ..composites import (_anchor_pos, build_composites as _build_composites,
                          uncovered_precomposed)
from .render import resolve_stack


@contextlib.contextmanager
def _quiet():
    """Silence the compose pass on the server terminal — it runs on every
    keystroke. GlyphConstruction print()s (e.g. "glyph missing from glyphSet")
    go via stdout; the geometry fallback warnings go via logging and are already
    surfaced by the main compute's Output panel, so drop both duplicates."""
    af_log = logging.getLogger("anchorsfactory")
    prev = af_log.level
    af_log.setLevel(logging.ERROR)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        af_log.setLevel(prev)


def _glyph_path(work, gname: str) -> str:
    if gname not in work:
        return ""
    try:
        rec = DecomposingRecordingPen(work)
        work[gname].draw(rec)
        pen = SVGPathPen(None)
        rec.replay(pen)
        return pen.getCommands()
    except Exception:                          # e.g. a dangling sub-component
        return ""


def _components_bounds(work, comps):
    """Union of each existing component's bbox, transformed by its matrix.

    Computed from the parts (not the assembled ConstructionGlyph) so a missing
    component can't blow up bounds — it is simply skipped."""
    xs, ys = [], []
    for gname, t in comps:
        if gname not in work:
            continue
        try:
            b = work[gname].bounds
        except Exception:
            b = None
        if not b:
            continue
        tr = Transform(*t)
        for px, py in ((b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])):
            x, y = tr.transformPoint((px, py))
            xs.append(x); ys.append(y)
    if not xs:
        return None
    return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]


def _serialize(composite, work) -> dict:
    """One library :class:`~anchorsfactory.composites.Composite` → the browser's
    JSON payload (components as SVG paths + transforms, anchor joins, bounds,
    problems, and the construction's source ``line`` for click-to-rule)."""
    cg = composite.glyph
    if cg is None:                                  # hard build failure — flag it
        return {"name": composite.name, "advance": 0, "bounds": None,
                "components": [], "joins": [], "problems": list(composite.problems),
                "line": composite.source_line}
    raw = list(cg.components)
    # Render only components that actually exist — missing ones are flagged in
    # problems, and drawing them would raise MissingComponentError.
    components = [{"base": g, "transform": [round(v, 3) for v in t],
                   "path": _glyph_path(work, g)}
                  for g, t in raw if g in work]
    # Join points: where each mark's _anchor snapped onto the base's anchor, in
    # composite space (base component transform applied).
    joins = []
    base_t = Transform(*raw[0][1]) if raw else Transform()
    if composite.base in work:
        for _mark, anchor in composite.marks:
            if anchor is None:
                continue
            pos = _anchor_pos(work[composite.base], anchor)
            if pos is not None:
                jx, jy = base_t.transformPoint(pos)
                joins.append({"x": round(jx, 2), "y": round(jy, 2), "anchor": anchor})
    return {
        "name": cg.name,
        "advance": float(cg.width),
        "bounds": _components_bounds(work, raw),
        "components": components,
        "joins": joins,
        "problems": list(composite.problems),
        "line": composite.source_line,
    }


def build_composite_view(font, layers, gc_text: str) -> dict:
    """Assemble the composites *gc_text* describes from the anchors *layers* place,
    serialized for the browser.

    *font* is the shared Studio font — it is **copied**, never mutated. Returns
    ``{ok, problems, composites: {name: payload}, uncovered}``; on an invalid rule
    document it returns ``ok=False`` with the document problems and no composites.
    """
    if not gc_text or not gc_text.strip():
        return {"ok": True, "problems": [], "composites": {},
                "uncovered": uncovered_precomposed(font, set())}

    doc = resolve_stack(layers)
    problems = validate_document(doc)
    if problems:
        return {"ok": False, "problems": problems, "composites": {}, "uncovered": []}

    # Apply the computed anchors onto a throwaway copy so GlyphConstruction can
    # read them; the shared font stays untouched.
    work = font.copy()
    composites: dict[str, dict] = {}
    with _quiet():
        apply_document(work, doc)
        for name, composite in _build_composites(work, gc_text).items():
            composites[name] = _serialize(composite, work)

    return {"ok": True, "problems": [], "composites": composites,
            "uncovered": uncovered_precomposed(font, set(composites))}
