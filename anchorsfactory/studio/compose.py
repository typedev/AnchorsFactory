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
from ..conditions import RuleContext, inactive_lines, structure_diff
from .render import resolve_stack

#: How construction-text problems are prefixed, so the client can route a
#: "constructions: line N: …" problem to the constructions editor.
GC_LABEL = "constructions"


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


def gc_inactive_lines(gc_text: str, context) -> list:
    """Lines of *gc_text* its ``!if`` blocks drop for *context* (for dimming);
    empty when they cannot be evaluated (that error is reported on compute)."""
    try:
        return sorted(inactive_lines(gc_text or "", context))
    except ValueError:
        return []


def build_composite_view(font, layers, gc_text: str, context=None) -> dict:
    """Assemble the composites *gc_text* describes from the anchors *layers* place,
    serialized for the browser.

    *font* is the shared Studio font — it is **copied**, never mutated. Returns
    ``{ok, problems, composites: {name: payload}, uncovered}``; on an invalid rule
    document it returns ``ok=False`` with the document problems and no composites.

    *context* is the master that ``!if`` blocks — in the rules and in
    *gc_text* — resolve for (its missing style name is filled from *font*).
    """
    if not gc_text or not gc_text.strip():
        return {"ok": True, "problems": [], "composites": {},
                "uncovered": uncovered_precomposed(font, set())}

    context = (context or RuleContext()).for_font(font)
    doc = resolve_stack(layers, context)
    problems = validate_document(doc)
    if problems:
        return {"ok": False, "problems": problems, "composites": {}, "uncovered": []}

    # Apply the computed anchors onto a throwaway copy so GlyphConstruction can
    # read them; the shared font stays untouched.
    work = font.copy()
    composites: dict[str, dict] = {}
    with _quiet():
        apply_document(work, doc)
        try:
            built = _build_composites(work, gc_text, context)
        except ValueError as exc:                   # a !if that cannot be evaluated
            return {"ok": False, "problems": [f"{GC_LABEL}: {exc}"],
                    "composites": {}, "uncovered": []}
        for name, composite in built.items():
            composites[name] = _serialize(composite, work)

    return {"ok": True, "problems": [], "composites": composites,
            "uncovered": uncovered_precomposed(font, set(composites))}


def masters_report(entries, layers, gc_text: str) -> dict:
    """Compare what the rules (and constructions) give each loaded master.

    *entries* is ``[(label, font, RuleContext), ...]``. Each master is computed
    with its own context; :func:`~anchorsfactory.conditions.structure_diff`
    then lists glyphs whose anchor names or composite components differ — a
    **warning**, since a designer may build composites and strip anchors before
    interpolating. A master whose rules fail is reported in ``errors`` and left
    out of the comparison. Returns ``{ok, warnings, errors, masters}``.
    """
    anchors, composites, errors = {}, {}, []
    for label, font, context in entries:
        context = (context or RuleContext()).for_font(font)
        try:
            doc = resolve_stack(layers, context)
            problems = validate_document(doc)
            if problems:
                raise ValueError("; ".join(problems))
            with _quiet():
                work = font.copy()
                anchors[label] = apply_document(work, doc)
                if gc_text and gc_text.strip():
                    composites[label] = _build_composites(work, gc_text, context)
        except Exception as exc:                    # one bad master must not sink the report
            errors.append(f"{label}: {exc}")
    diff = structure_diff(anchors=anchors if len(anchors) > 1 else None,
                          composites=composites if len(composites) > 1 else None)
    return {"ok": not errors, "warnings": diff.warnings(), "errors": errors,
            "masters": list(anchors)}
