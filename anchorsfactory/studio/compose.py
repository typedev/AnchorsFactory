"""Assemble composite glyphs with GlyphConstruction from AnchorsFactory anchors.

The Studio's compute is read-only — it returns anchor coordinates as JSON but
never writes them onto the font. GlyphConstruction, however, positions marks by
reading ``glyph.anchors``. So to preview a composite we: apply the computed
anchors onto a throwaway **copy** of the font (never the shared one), run
GlyphConstruction against it, and return each assembled glyph's outline plus the
anchor-join points and any problems (a missing/misnamed anchor is exactly the
signal the user is debugging).

This is the adapter layer the vendored engine's README calls for — it imports
from ``_vendor`` but never edits it.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
import unicodedata

from fontTools.misc.transform import Transform
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.svgPathPen import SVGPathPen

from ..apply import apply_document, validate_document
from .render import resolve_stack
from ._vendor.glyphConstruction import (
    GlyphConstructionBuilder,
    ParseGlyphConstructionListFromString,
)

_IDENT = re.compile(r"[A-Za-z_][\w.]*")


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


def _ident(s: str) -> str:
    m = _IDENT.match(s.strip())
    return m.group(0) if m else s.strip()


def _parse_construction(text: str):
    """Extract ``(name, base, [(mark, anchor|None), ...])`` from a construction.

    Conservative — enough for ``name = base + mark@anchor + …`` (the v1 surface);
    trailing unicode (``| …``), metric/attr (``^ …``) and note (``# …``) clauses
    are ignored. Returns ``None`` if there's no ``=``."""
    recipe = text.split("|", 1)[0].split("^", 1)[0].split("#", 1)[0]
    if "=" not in recipe:
        return None
    left, right = recipe.split("=", 1)
    name = _ident(left.strip().lstrip("?"))
    parts = [p.strip() for p in right.split("+") if p.strip()]
    if not parts:
        return name, None, []
    base = _ident(parts[0])
    marks = []
    for p in parts[1:]:
        if "@" in p:
            g, anchor = p.split("@", 1)
            marks.append((_ident(g), _ident(anchor)))
        else:
            marks.append((_ident(p), None))
    return name, base, marks


def _anchor_pos(glyph, name):
    for a in glyph.anchors:
        if a.name == name:
            return (a.x, a.y)
    return None


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


def _composite_payload(constr: str, work) -> dict | None:
    """Build one construction against *work*, or ``None`` if it has no name.

    Resilient by design: a missing component glyph (or any GC hiccup) becomes a
    recorded *problem*, never an exception — so one bad line can't sink the whole
    batch, and the valid composites still render."""
    dest = GlyphConstructionBuilder(constr, work)
    if not dest.name:
        return None

    parsed = _parse_construction(constr)
    _, base, marks = parsed if parsed else (dest.name, None, [])

    problems: list[str] = []
    if base is not None and base not in work:
        problems.append(f"base glyph {base!r} not found")
    for mark, anchor in marks:
        if mark not in work:
            problems.append(f"component {mark!r} not found")
            continue
        if anchor is not None:
            if base in work and _anchor_pos(work[base], anchor) is None:
                problems.append(f"anchor {anchor!r} not found on base {base!r}")
            if _anchor_pos(work[mark], "_" + anchor) is None:
                problems.append(f"mark anchor {'_' + anchor!r} not found on {mark!r}")

    raw = list(dest.components)
    # Render only components that actually exist — missing ones are flagged above,
    # and drawing them would raise MissingComponentError.
    components = [{"base": g, "transform": [round(v, 3) for v in t],
                   "path": _glyph_path(work, g)}
                  for g, t in raw if g in work]

    # Join points: where each mark's _anchor snapped onto the base's anchor, in
    # composite space (base component transform applied).
    joins = []
    base_t = Transform(*raw[0][1]) if raw else Transform()
    if base in work:
        for _mark, anchor in marks:
            if anchor is None:
                continue
            pos = _anchor_pos(work[base], anchor)
            if pos is not None:
                jx, jy = base_t.transformPoint(pos)
                joins.append({"x": round(jx, 2), "y": round(jy, 2), "anchor": anchor})

    return {
        "name": dest.name,
        "advance": float(dest.width),
        "bounds": _components_bounds(work, raw),
        "components": components,
        "joins": joins,
        "problems": problems,
    }


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


def _uncovered(font, built) -> list:
    """Precomposed glyphs the font *has* but that no construction builds — a
    coverage gap. A glyph counts if its codepoint has a **canonical** Unicode
    decomposition (i.e. it's a precomposed accented/composite character) and its
    name isn't among the built composites."""
    out = []
    for g in font:
        if g.name in built:
            continue
        for u in (getattr(g, "unicodes", None) or ()):
            d = unicodedata.decomposition(chr(u))
            if d and not d.startswith("<"):        # canonical (pre)composition, not <compat>
                out.append(g.name)
                break
    return out


def build_composites(font, layers, gc_text: str) -> dict:
    """Assemble the composites *gc_text* describes from the anchors *layers* place.

    *font* is the shared Studio font — it is **copied**, never mutated. Returns
    ``{ok, problems, composites: {name: payload}}``; on an invalid rule document
    it returns ``ok=False`` with the document problems and no composites."""
    if not gc_text or not gc_text.strip():
        return {"ok": True, "problems": [], "composites": {}, "uncovered": _uncovered(font, set())}

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
        # font=None → don't let GC filter out already-existing glyph names (the
        # demo ships an `aacute`); the anchored copy is fed only to the builder.
        constructions = ParseGlyphConstructionListFromString(gc_text, None)
        for constr in constructions:
            try:
                payload = _composite_payload(constr, work)
            except Exception as exc:             # never let one line sink the batch
                parsed = _parse_construction(constr)
                nm = parsed[0] if parsed else constr
                composites[nm] = {"name": nm, "advance": 0, "bounds": None,
                                  "components": [], "joins": [],
                                  "problems": [f"could not build: {exc}"]}
                continue
            if payload is not None:
                composites[payload["name"]] = payload

    return {"ok": True, "problems": [], "composites": composites,
            "uncovered": _uncovered(font, set(composites))}
