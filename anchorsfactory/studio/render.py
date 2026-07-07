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

from ..apply import Propagated, accumulate_provenance, propagate_seed, validate_document
from ..dsl import DSLError, parse_dsl
from ..geometry import explain
from ..model import Document, resolve_suffixes
from ..presets import is_preset
from ..runner import load_document


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


def _anchor_payload(font, target, spec, gname, diagnostics, shift_x, layer, line):
    """Resolve one spec on *target*, returning its JSON dict (or ``None`` on a
    hard geometry failure, which is recorded in *diagnostics*).

    *layer*/*line* are the provenance of this spec (which rule layer, and the
    1-based source line within it, or ``None`` when inherited/unknown) — the
    studio uses them to jump from an anchor to the rule that placed it."""
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
    info["layer"] = layer
    info["line"] = line
    return info


def resolve_stack(layers) -> Document:
    """Merge an ordered list of rule *layers* (bottom → top) into one Document.

    Each layer is ``{"name": str, "text": str}``; later layers override earlier
    ones (the accumulation model), so the top layer wins. Each layer is resolved
    independently (its own ``!extends`` against presets) and its source lines are
    tagged with the layer's index, so every rule's provenance is ``(layer, line)``
    — the studio maps that back to the right editor pane. A layer that fails to
    parse raises, prefixed with its name.
    """
    merged = Document()
    for i, layer in enumerate(layers):
        try:
            doc = resolve_document(layer.get("text", ""))
        except ValueError as exc:
            raise DSLError(f"{layer.get('name') or f'layer {i}'}: {exc}")
        src = list(doc.sources) + [None] * (len(doc.rules) - len(doc.sources))
        merged = Document(
            labels={**merged.labels, **doc.labels},
            variables={**merged.variables, **doc.variables},
            rules=merged.rules + doc.rules,
            sources=merged.sources + [(i, s) for s in src],
            shift_x=doc.shift_x or merged.shift_x,
            suffix_ops=merged.suffix_ops + doc.suffix_ops,
            propagate=doc.propagate if doc.propagate != "none" else merged.propagate,
        )
    return merged


def _layer(base: Document, child: Document, *, inherited: bool) -> Document:
    """Layer *child* on *base* (mirrors ``runner._merge``) while keeping source
    lines aligned with rules. ``inherited=True`` marks the child's rules as coming
    from a preset, so they carry no editor line (click-to-rule only points at the
    edited text)."""
    if inherited:
        child_src = [None] * len(child.rules)
    else:
        child_src = list(child.sources) + [None] * (len(child.rules) - len(child.sources))
    return Document(
        labels={**base.labels, **child.labels},
        variables={**base.variables, **child.variables},
        rules=base.rules + child.rules,
        sources=base.sources + child_src,
        shift_x=child.shift_x or base.shift_x,
        suffix_ops=base.suffix_ops + child.suffix_ops,
        propagate=child.propagate if child.propagate != "none" else base.propagate,
    )


def resolve_document(rules_text: str) -> Document:
    """Parse the edited rules and resolve any ``!extends <preset>`` so custom
    rules can inherit a bundled preset (e.g. ``!extends default`` then a few
    overrides). Bases are merged first, the edited rules on top.

    Only **bundled preset names** may be inherited here — the studio has no access
    to the user's file paths — so a path reference raises a clear error. Edited
    rules keep their source lines (for click-to-rule); inherited ones do not.
    """
    doc = parse_dsl(rules_text.splitlines())
    if not doc.extends:
        return doc
    base = Document()
    for ref in doc.extends:
        if not is_preset(ref):
            raise DSLError(f"!extends {ref!r}: only a bundled preset name can be "
                           f"inherited in studio (not a file path)")
        base = _layer(base, load_document(ref), inherited=True)
    return _layer(base, doc, inherited=False)


def build_view(font, rules) -> dict:
    """Compute everything the UI needs for *rules* against *font*.

    *rules* is either a rules string (a single layer) or a list of layers
    ``[{"name", "text"}, ...]`` bottom → top. Returns ``{ok, problems,
    diagnostics, glyphs, layers}`` where ``glyphs`` maps each affected (suffixed)
    glyph name to ``{name, advance, bounds, path, anchors}`` and each anchor
    carries its ``(layer, line)`` provenance. Parse/validation errors come back
    as ``problems`` (never an exception), so the editor can show them inline.
    """
    layers = [{"name": "rules", "text": rules}] if isinstance(rules, str) else list(rules)
    names = [l.get("name") for l in layers]
    try:
        doc = resolve_stack(layers)                  # merge layers, resolve each layer's !extends
    except ValueError as exc:                        # DSLError / !extends cycle subclass this
        return {"ok": False, "problems": [str(exc)], "diagnostics": [],
                "glyphs": {}, "layers": names}

    problems = validate_document(doc)
    if problems:
        # The document doesn't resolve (typo'd label, undefined/misused variable,
        # axis cycle). Surface the problems and stop — computing anyway would let
        # accumulate() raise mid-glyph and 500 the request. The editor shows these
        # inline; the user is usually mid-edit, so this fires on nearly every keystroke.
        return {"ok": False, "problems": problems, "diagnostics": [],
                "glyphs": {}, "layers": names}

    diagnostics: list[dict] = []
    glyphs: dict[str, dict] = {}

    sfx = resolve_suffixes(doc.suffix_ops)
    font_names = {g.name for g in font} if sfx.all else None
    sources = doc.sources                            # rule index -> (layer, line) or None

    order_pos: dict[str, int] = {}                   # glyph name -> position in the font's glyphOrder
    try:
        for i, gname in enumerate(font.glyphOrder):
            order_pos[gname] = i
    except Exception:                                # older fontParts / odd fonts — fall back to encounter order
        pass
    fallback = 10 ** 9                               # unordered glyphs sort after the known ones, stably
    memo: dict[str, dict] = {}                        # propagation cache (shared across glyphs)

    for glyph in font:
        seed = [(s, Propagated(src))
                for s, src in propagate_seed(font, glyph, doc, memo)]
        try:
            specs = accumulate_provenance(doc, glyph.name, list(glyph.unicodes), seed=seed)
        except ValueError as exc:                    # validate_document should have caught this
            problems.append(f"glyph {glyph.name}: {exc}")
            break                                    # same doc breaks every glyph — report once
        if not specs:
            continue
        for suffix in sfx.expand(glyph.name, font_names):
            gname = glyph.name + suffix
            if gname not in font:
                continue
            target = font[gname]
            placed: dict[str, dict] = {}             # name -> payload (last wins, like replace)
            for spec, rule in specs:
                if isinstance(rule, Propagated):     # inherited from a component
                    layer, line = None, None
                else:
                    origin = sources[rule] if rule < len(sources) else None
                    layer, line = origin if origin else (None, None)
                payload = _anchor_payload(font, target, spec, gname,
                                          diagnostics, doc.shift_x, layer, line)
                if payload is not None:
                    if isinstance(rule, Propagated):
                        payload["propagated"] = True
                        payload["from"] = rule.component
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
            "diagnostics": diagnostics, "glyphs": glyphs, "layers": names}
