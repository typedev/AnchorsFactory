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
    ParseVariables,
    glyphCommentSuffixSplit,
    shouldCheckGlyphExists,
)

_IDENT = re.compile(r"[A-Za-z_][\w.]*")


def _ident(s: str) -> str:
    m = _IDENT.match(s.strip())
    return m.group(0) if m else s.strip()


# --------------------------------------------------------------------------
#  U+ references — an AnchorsFactory extension over the GlyphConstruction
#  surface, resolved to plain glyph names *before* the vendored engine (whose
#  own grammar accepts names only) ever sees the text.
# --------------------------------------------------------------------------

_UNICODE_REF = re.compile(r"\bU\+([0-9A-Fa-f]{4,6})(\.case)?\b")

#: Marks the AGL cannot name, under the name type designers actually use.
_LEGACY_MARK_NAMES = {
    0x031B: "horn", 0x0325: "ringbelow", 0x0331: "macronbelow",
    0x0326: "commaaccent",
}

#: Combining mark -> the spacing accent fonts conventionally encode instead.
#: Rules address a mark by its combining codepoint; many fonts only encode the
#: spacing twin (``acute`` U+00B4, not U+0301), so that is tried next.
_SPACING_TWIN = {
    0x0300: 0x0060, 0x0301: 0x00B4, 0x0302: 0x02C6, 0x0303: 0x02DC,
    0x0304: 0x00AF, 0x0306: 0x02D8, 0x0307: 0x02D9, 0x0308: 0x00A8,
    0x030A: 0x02DA, 0x030B: 0x02DD, 0x030C: 0x02C7, 0x0327: 0x00B8,
    0x0328: 0x02DB, 0x0326: 0xF6C3,
}


def _character_map(glyphset) -> dict:
    """``{codepoint: glyph name}`` for *glyphset* (first glyph to claim a
    codepoint wins), or ``{}`` if it can't be iterated."""
    cmap: dict[int, str] = {}
    try:
        for g in glyphset:
            name = getattr(g, "name", g)
            glyph = glyphset[name] if isinstance(g, str) else g
            for u in (getattr(glyph, "unicodes", None) or ()):
                cmap.setdefault(u, name)
    except Exception:
        return {}
    return cmap


def _name_for_codepoint(cp: int, cmap: dict, glyphset) -> str:
    """Resolve a codepoint to the glyph name a construction should reference.

    The font's own cmap first (it is the authority on what this font calls the
    character), then the spacing twin of a combining mark, then the AGL name,
    then ``uniXXXX``. The last two need no font: a construction's *target* glyph
    normally does not exist yet — that is the glyph being built.
    """
    if cp in cmap:
        return cmap[cp]
    twin = _SPACING_TWIN.get(cp)
    if twin is not None and twin in cmap:
        return cmap[twin]
    try:
        from fontTools.agl import UV2AGL
    except ImportError:                                   # pragma: no cover
        UV2AGL = {}
    agl = UV2AGL.get(cp)
    if agl and glyphset is not None:
        try:
            if agl in glyphset:
                return agl
        except Exception:
            pass
    return agl or f"uni{cp:04X}"


def _mark_base_name(cp: int) -> str | None:
    """The conventional (AGL) name of a mark — ``acute`` for U+0301 or U+00B4 —
    the stem the legacy spellings are built from."""
    try:
        from fontTools.agl import UV2AGL
    except ImportError:                                   # pragma: no cover
        return _LEGACY_MARK_NAMES.get(cp)
    twin = _SPACING_TWIN.get(cp)
    name = UV2AGL.get(twin) if twin else None
    if not name:
        agl = UV2AGL.get(cp)
        if agl and agl.endswith("comb"):
            name = agl[: -len("comb")]
    return name or _LEGACY_MARK_NAMES.get(cp)


def _case_name_for_codepoint(cp: int, glyphset) -> str | None:
    """The capital-height cut of a mark, if this font ships one.

    Fonts commonly carry a second accent set drawn for uppercase, and it has no
    codepoints of its own — only a name, spelled ``acute.case`` or ``Acute``
    depending on the house. Returns ``None`` when the font has no such glyph, so
    the caller falls back to the plain mark.
    """
    base = _mark_base_name(cp)
    if not base:
        return None
    candidates = [f"{base}.case", base.capitalize(), f"{base}comb.case"]
    if glyphset is None:
        return base.capitalize()          # no font to ask: the legacy spelling
    for name in candidates:
        try:
            if name in glyphset:
                return name
        except Exception:
            return None
    return None


def resolve_unicode_refs(gc_text: str, glyphset=None) -> str:
    """Rewrite every ``U+XXXX`` token in *gc_text* to a glyph name.

    AnchorsFactory rule sets address glyphs by codepoint so they stay portable
    across naming schemes; GlyphConstruction's grammar only knows names (and
    would in any case mis-split ``U+0041`` on its own ``+`` mark separator). So
    every consumer resolves first — line- and column-agnostic token substitution,
    which keeps source line numbers (and hence click-to-rule) intact. Text with
    no ``U+`` token is returned unchanged.

    A ``.case`` suffix (``U+0301.case``) asks for the capital-height cut of a
    mark, which fonts carry under a name rather than a codepoint; it falls back
    to the plain mark in fonts that have no such set.
    """
    if "U+" not in gc_text:
        return gc_text
    cmap = _character_map(glyphset) if glyphset is not None else {}
    cache: dict[tuple, str] = {}

    def sub(m):
        cp, case = int(m.group(1), 16), bool(m.group(2))
        key = (cp, case)
        if key not in cache:
            name = _case_name_for_codepoint(cp, glyphset) if case else None
            cache[key] = name or _name_for_codepoint(cp, cmap, glyphset)
        return cache[key]

    return _UNICODE_REF.sub(sub, gc_text)


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


def _emitted_line_numbers(gc_text: str) -> list[int]:
    """Source line number for each entry the vendored parser emits, index-aligned
    with :func:`ParseGlyphConstructionListFromString`.

    The parser keeps a slot (as ``""``) for **blank** lines and for ``$var``
    definitions (which :func:`ParseVariables` blanks out in place, preserving
    newlines) — it only *drops* comment lines and *leading* blanks. So we must
    mirror that exact bookkeeping, not a plain "non-comment, non-blank" filter:
    otherwise every construction after the first blank/var line gets the wrong
    line (the old bug). We don't replicate the parser's trailing-blank trim —
    those slots fall past the end of the (shorter) emitted list and are never
    indexed.
    """
    txt, _vars = ParseVariables(gc_text)                  # $var defs -> "" (newlines kept)
    kept: list[int] = []
    for i, raw in enumerate(txt.split("\n"), 1):
        line = raw.strip()
        if line:
            if line[0] == glyphCommentSuffixSplit:        # a comment: parser drops it
                continue
            if line[0] == shouldCheckGlyphExists:         # '?' — font=None here, so only strip it
                line = line[1:]
        if not line and not kept:                         # parser drops leading blank/var lines
            continue
        kept.append(i)
    return kept


def parse_constructions(gc_text: str, glyphset=None) -> list[Construction]:
    """Parse *gc_text* into constructions, each tagged with its source line.

    The vendored parser returns one entry per line it keeps — a construction
    string, or ``""`` for a blank / consumed-``$var`` slot. We pair the entries,
    in order, with the source line numbers the parser kept (see
    :func:`_emitted_line_numbers`) and drop the empty slots; a construction whose
    line can't be located keeps ``line=None``.

    ``U+XXXX`` references are resolved first (see :func:`resolve_unicode_refs`);
    pass *glyphset* so they resolve against the font's own names.
    """
    gc_text = resolve_unicode_refs(gc_text, glyphset)
    constructions = ParseGlyphConstructionListFromString(gc_text, None)
    lines = _emitted_line_numbers(gc_text)
    out: list[Construction] = []
    for idx, text in enumerate(constructions):
        if not text.strip():                              # a blank/var slot, not a construction
            continue
        parsed = parse_construction(text)
        out.append(Construction(text=text,
                                line=lines[idx] if idx < len(lines) else None,
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
    for c in parse_constructions(gc_text, glyphset):
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
