"""Turn a font + rule document into the JSON payload the browser renders.

Two jobs: draw a glyph's outline to an SVG path (in raw UFO space — the client
flips Y with one transform), and walk the document the way
:func:`anchorsfactory.apply.compute_document` does but calling
:func:`anchorsfactory.geometry.explain` per spec, so each placed anchor carries
the overlay data (scanlines, stems, centroid) that explains it.
"""

from __future__ import annotations

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.svgPathPen import SVGPathPen

from ..apply import accumulate_provenance, validate_document
from ..dsl import parse_dsl
from ..geometry import explain
from ..model import resolve_suffixes


def glyph_to_svg_path(glyph) -> str:
    """The glyph outline as an SVG path ``d`` string, components decomposed.

    Coordinates stay in font units with Y pointing up (UFO convention); the
    client applies a single ``scale(1,-1)`` so glyph, anchors, and overlays share
    one coordinate space.
    """
    rec = DecomposingRecordingPen(glyph.font)
    glyph.draw(rec)
    pen = SVGPathPen(None)          # glyphSet only needed for components, already gone
    rec.replay(pen)
    return pen.getCommands()


def _anchor_payload(font, target, spec, gname, diagnostics, shift_x, rule, line):
    """Resolve one spec on *target*, returning its JSON dict (or ``None`` on a
    hard geometry failure, which is recorded in *diagnostics*).

    *rule*/*line* are the provenance of this spec (index into ``doc.rules`` and
    the 1-based source line, or ``None`` when unknown) — the studio uses them to
    jump from an anchor to the rule that placed it."""
    sink: list[str] = []
    try:
        info = explain(font, target, spec, warnings=sink)
    except Exception as exc:                        # geometry raised — skip, flag
        diagnostics.append({"glyph": gname, "anchor": spec.name,
                            "reason": str(exc), "severity": "error"})
        return None
    for reason in sink:
        diagnostics.append({"glyph": gname, "anchor": spec.name,
                            "reason": reason, "severity": "warning"})
    info["x"] = info["x"] + shift_x                  # document-level global X shift
    info["rule"] = rule
    info["line"] = line
    return info


def build_view(font, rules_text: str) -> dict:
    """Compute everything the UI needs for *rules_text* against *font*.

    Returns ``{ok, problems, diagnostics, glyphs}`` where ``glyphs`` maps each
    affected (suffixed) glyph name to ``{name, advance, bounds, path, anchors}``.
    Parse and validation errors come back as ``problems`` (never an exception),
    so the editor can show them inline.
    """
    try:
        doc = parse_dsl(rules_text.splitlines())
    except ValueError as exc:                        # DSLError/ParseError subclass this
        return {"ok": False, "problems": [str(exc)], "diagnostics": [], "glyphs": {}}

    problems = validate_document(doc)
    diagnostics: list[dict] = []
    glyphs: dict[str, dict] = {}

    sfx = resolve_suffixes(doc.suffix_ops)
    font_names = {g.name for g in font} if sfx.all else None
    sources = doc.sources                            # rule index -> source line (may be empty)

    order_pos: dict[str, int] = {}                   # glyph name -> position in the font's glyphOrder
    try:
        for i, gname in enumerate(font.glyphOrder):
            order_pos[gname] = i
    except Exception:                                # older fontParts / odd fonts — fall back to encounter order
        pass
    fallback = 10 ** 9                               # unordered glyphs sort after the known ones, stably

    for glyph in font:
        specs = accumulate_provenance(doc, glyph.name, list(glyph.unicodes))
        if not specs:
            continue
        for suffix in sfx.expand(glyph.name, font_names):
            gname = glyph.name + suffix
            if gname not in font:
                continue
            target = font[gname]
            placed: dict[str, dict] = {}             # name -> payload (last wins, like replace)
            for spec, rule in specs:
                line = sources[rule] if rule < len(sources) else None
                payload = _anchor_payload(font, target, spec, gname,
                                          diagnostics, doc.shift_x, rule, line)
                if payload is not None:
                    placed[spec.name] = payload
            if not placed:
                continue
            bounds = target.bounds
            glyphs[gname] = {
                "name": gname,
                "order": order_pos.get(gname, fallback),
                "advance": float(target.width),
                "bounds": list(bounds) if bounds is not None else None,
                "path": glyph_to_svg_path(target),
                "anchors": list(placed.values()),
            }
            fallback += 1

    return {"ok": not problems, "problems": problems,
            "diagnostics": diagnostics, "glyphs": glyphs}
