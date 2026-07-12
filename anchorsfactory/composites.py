"""Assemble composite glyphs with GlyphConstruction — the public, renderer-neutral
core.

AnchorsFactory places the anchors; GlyphConstruction reads a glyph's
``.anchors`` to snap each mark's ``_anchor`` onto the base's ``anchor``. This
module wraps the vendored engine (:mod:`anchorsfactory._vendor.glyphconstruction`)
so both the web Studio and a GTK client build composites the same way and get
the one thing neither had before: each construction's **source line**, for
mapping a composite back to its rule in an editor.

The core is deliberately renderer-agnostic: :func:`build_composites` assembles
against a **ready** glyphset (anchors already present — it does not apply an
anchor document) and returns live :class:`ConstructionGlyph` objects
(``.draw(pen)`` / ``.width`` / ``.components``) plus provenance. A consumer that
wants serialized geometry (SVG paths, join points) draws from these itself; see
``anchorsfactory/studio/compose.py`` for that adapter.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ._vendor.glyphconstruction import (       # noqa: F401  (re-exported)
    ConstructionGlyph,
    GlyphBuilderError,
    GlyphConstructionBuilder,
    ParseGlyphConstructionListFromString,
)

_IDENT = re.compile(r"[A-Za-z_][\w.]*")


def _ident(s: str) -> str:
    m = _IDENT.match(s.strip())
    return m.group(0) if m else s.strip()


def parse_construction(text: str):
    """Extract ``(name, base, marks)`` from one construction string.

    ``marks`` is a list of ``(mark, anchor|None)``. Conservative — enough for
    ``name = base + mark@anchor + …`` (the v1 surface); trailing unicode
    (``| …``), metric/attribute (``^ …``) and note (``# …``) clauses are ignored.
    Returns ``None`` when there is no ``=``.
    """
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


@dataclass
class Construction:
    """One parsed construction with its 1-based source *line* in the GC text.

    ``text`` is the raw construction string (as the engine sees it); ``name`` is
    its parsed target glyph name (``None`` if the line has no assignment).
    """
    text: str
    line: int | None
    name: str | None


def parse_constructions(gc_text: str) -> list[Construction]:
    """Parse *gc_text* into constructions, each tagged with its source line.

    The vendored parser drops comment/blank lines and returns one entry per
    remaining *significant* line — a construction string, or ``""`` where a
    ``$var`` definition was consumed. We pair the entries, in order, with those
    significant line numbers and drop the empty (variable) slots; a construction
    whose line can't be located keeps ``line=None``.
    """
    constructions = ParseGlyphConstructionListFromString(gc_text, None)
    significant = [i for i, raw in enumerate(gc_text.splitlines(), 1)
                   if raw.split("#", 1)[0].strip()]        # non-comment, non-blank
    out: list[Construction] = []
    for idx, text in enumerate(constructions):
        if not text.strip():                              # a consumed $var slot, not a construction
            continue
        parsed = parse_construction(text)
        out.append(Construction(text=text,
                                line=significant[idx] if idx < len(significant) else None,
                                name=parsed[0] if parsed else None))
    return out


def _anchor_pos(glyph, name):
    for a in glyph.anchors:
        if a.name == name:
            return (a.x, a.y)
    return None


def _construction_problems(base, marks, glyphset) -> list[str]:
    """Human-readable issues with a construction against *glyphset* — a missing
    base/mark glyph, or a base/mark anchor the join needs but that isn't there
    (exactly what a user debugging a composite wants surfaced)."""
    problems: list[str] = []
    if base is not None and base not in glyphset:
        problems.append(f"base glyph {base!r} not found")
    for mark, anchor in marks:
        if mark not in glyphset:
            problems.append(f"component {mark!r} not found")
            continue
        if anchor is not None:
            if base in glyphset and _anchor_pos(glyphset[base], anchor) is None:
                problems.append(f"anchor {anchor!r} not found on base {base!r}")
            if _anchor_pos(glyphset[mark], "_" + anchor) is None:
                problems.append(f"mark anchor {'_' + anchor!r} not found on {mark!r}")
    return problems


@dataclass
class Composite:
    """One assembled composite plus its provenance.

    ``glyph`` is the live :class:`ConstructionGlyph` (``.draw(pen)``/``.width``/
    ``.components``/``.unicodes``), or ``None`` if the build hard-failed;
    ``source_line`` is the construction's 1-based line in the GC text (for
    editor click-to-rule); ``base``/``marks`` are the parsed recipe; ``problems``
    lists any missing-glyph/anchor issues.
    """
    name: str
    glyph: object | None
    source_line: int | None
    base: str | None = None
    marks: tuple = ()
    problems: tuple = ()


def build_composites(glyphset, gc_text: str) -> dict:
    """Assemble every construction in *gc_text* against *glyphset*.

    *glyphset* is any font/glyphset the vendored builder can read — ``name in
    glyphset``, ``glyphset[name]`` with ``.anchors``/``.width``/``.bounds``/
    ``.draw`` per glyph and ``.info`` on the object. Anchors must already be
    present (this core does **not** apply an anchor document — a Studio-style
    caller applies them to a font copy first; a virtual-glyphset caller carries
    them live).

    Returns ``{name: Composite}`` (last construction of a name wins). Resilient:
    a construction that raises becomes a ``Composite`` with ``glyph=None`` and a
    recorded problem, never an exception, so one bad line can't sink the batch.
    Each surviving :class:`ConstructionGlyph` gets ``.font = glyphset`` (some
    consumers read ``glyph.font`` when drawing).
    """
    out: dict[str, Composite] = {}
    for c in parse_constructions(gc_text):
        parsed = parse_construction(c.text)
        base, marks = (parsed[1], parsed[2]) if parsed else (None, [])
        try:
            cg = GlyphConstructionBuilder(c.text, glyphset)
        except Exception as exc:                    # never let one line sink the batch
            if c.name:
                out[c.name] = Composite(c.name, None, c.line, base, tuple(marks),
                                        (f"could not build: {exc}",))
            continue
        if not cg.name:
            continue
        try:
            cg.font = glyphset                      # some renderers read glyph.font
        except Exception:
            pass
        problems = _construction_problems(base, marks, glyphset)
        out[cg.name] = Composite(cg.name, cg, c.line, base, tuple(marks), tuple(problems))
    return out


def composites_in_glyph_order(font, names) -> list:
    """Order composite *names* by *font*'s ``glyphOrder`` (unknown names last, in
    their given order)."""
    try:
        order = {n: i for i, n in enumerate(font.glyphOrder)}
    except Exception:
        order = {}
    fallback = len(order)
    return sorted(names, key=lambda n: order.get(n, fallback))


def uncovered_precomposed(font, built) -> list:
    """Precomposed glyphs *font* has that no construction in *built* builds — a
    coverage gap. A glyph counts if a codepoint of it has a **canonical** Unicode
    decomposition (a precomposed accented character) and its name isn't in
    *built*."""
    built = set(built)
    out = []
    for g in font:
        if g.name in built:
            continue
        for u in (getattr(g, "unicodes", None) or ()):
            d = unicodedata.decomposition(chr(u))
            if d and not d.startswith("<"):         # canonical, not <compat>
                out.append(g.name)
                break
    return out
