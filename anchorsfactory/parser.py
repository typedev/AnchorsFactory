"""Parser for the current ``.txt`` rule format -> IR (:class:`Document`).

This is an *adapter*: it maps the existing surface syntax onto the IR so the
new engine can run against today's rule files (and the golden regression can
compare old vs new output). A future, redesigned DSL becomes a second
front-end producing the same :class:`Document` — the engine never changes.

Current vocabulary mapping::

    align (X):  center->ADVANCE.CENTER   centerpos->BOX.CENTER
                left/right->BOX.LEFT/RIGHT
                leftinter/rightinter->OUTLINE.LEFT/RIGHT
                topcenter/bottomcenter->OUTLINE.CENTER@top/@bottom
                <int>->absolute
    vert  (Y):  <int>->absolute   $G->top   $G_->bottom   $G- ->middle
                $G*d1/d2->fraction
"""

from __future__ import annotations

from .model import (
    Frame, HAlign, VEdge, Frac,
    X, XAbs, Y, YAbs, AnchorSpec,
    GlyphName, Unicode, Op, Document,
)


class ParseError(ValueError):
    """Raised on a malformed rule line, with line context."""


_ALIGN = {
    "center": X(Frame.ADVANCE, HAlign.CENTER),
    "centerpos": X(Frame.BOX, HAlign.CENTER),
    "left": X(Frame.BOX, HAlign.LEFT),
    "right": X(Frame.BOX, HAlign.RIGHT),
    "leftinter": X(Frame.OUTLINE, HAlign.LEFT),
    "rightinter": X(Frame.OUTLINE, HAlign.RIGHT),
    "topcenter": X(Frame.OUTLINE, HAlign.CENTER, at=VEdge.TOP),
    "bottomcenter": X(Frame.OUTLINE, HAlign.CENTER, at=VEdge.BOTTOM),
}


def _parse_align(tok: str):
    if tok in _ALIGN:
        return _ALIGN[tok]
    try:
        return XAbs(int(tok))
    except ValueError:
        raise ParseError(f"unknown horizontal align {tok!r}")


def _parse_vert(tok: str):
    if not tok.startswith("$"):
        try:
            return YAbs(int(tok))
        except ValueError:
            raise ParseError(f"invalid vertical position {tok!r}")
    body = tok[1:]
    if "*" in body:
        glyph, frac = body.split("*", 1)
        if "/" not in frac:
            raise ParseError(f"fraction must be d1/d2 in {tok!r}")
        d1, d2 = frac.split("/", 1)
        try:
            return Y(glyph, Frac(int(d1), int(d2)))
        except ValueError as e:
            raise ParseError(f"bad fraction in {tok!r}: {e}")
    if body.endswith("_"):
        return Y(body[:-1], VEdge.BOTTOM)
    if body.endswith("-"):
        return Y(body[:-1], VEdge.MIDDLE)
    return Y(body, VEdge.TOP)


def _parse_spec(tok: str) -> AnchorSpec:
    parts = tok.split(":")
    if len(parts) != 3:
        raise ParseError(f"anchor code must be name:align:vert, got {tok!r}")
    name, align, vert = parts
    if not name:
        raise ParseError(f"empty anchor name in {tok!r}")
    return AnchorSpec(name, _parse_align(align), _parse_vert(vert))


def _clean(line: str) -> str:
    # Match the historical behaviour: drop all spaces, then strip a trailing comment.
    return line.replace(" ", "").split("#", 1)[0].strip()


def parse_document(lines) -> Document:
    """Parse rule-file lines into a :class:`Document` (font-independent).

    Label references are expanded into concrete :class:`AnchorSpec` lists, so
    the engine consumes only resolved specs. ``&hex`` selectors stay abstract
    (:class:`Unicode`) and are resolved against the font's cmap at apply time.
    """
    labels: dict[str, list[AnchorSpec]] = {}
    rules: list = []
    shift_x = 0
    suffixes = [""]

    # Phase 1: collect labels/directives and raw (selector, item-tokens) rows.
    raw_rows: list[tuple[object, list[str], int]] = []
    for n, line in enumerate(lines, 1):
        line = _clean(line)
        if not line:
            continue
        if "=" not in line:
            raise ParseError(f"line {n}: missing '=' in {line!r}")
        head, content = line.split("=", 1)

        if head.startswith("@"):
            if head == "@SFXLIST":
                suffixes.extend("." + s for s in content.split(",") if s)
                continue
            if head == "@SHIFTX":
                try:
                    shift_x = int(content)
                except ValueError:
                    raise ParseError(f"line {n}: @SHIFTX needs an integer, got {content!r}")
                continue
            try:
                labels[head] = [_parse_spec(t) for t in content.split(",")]
            except ParseError as e:
                raise ParseError(f"line {n}: {e}")
            continue

        if head.startswith("&"):
            try:
                selector = Unicode(int(head[1:], 16))
            except ValueError:
                raise ParseError(f"line {n}: bad unicode {head!r}")
        else:
            selector = GlyphName(head)
        raw_rows.append((selector, content.split(","), n))

    # Phase 2: expand label references into concrete specs.
    for selector, items, n in raw_rows:
        specs: list[AnchorSpec] = []
        for item in items:
            if item.startswith("@"):
                if item not in labels:
                    raise ParseError(f"line {n}: undefined label {item!r}")
                specs.extend(labels[item])
            else:
                try:
                    specs.append(_parse_spec(item))
                except ParseError as e:
                    raise ParseError(f"line {n}: {e}")
        rules.append((selector, Op.REPLACE, specs))

    return Document(labels=labels, rules=rules, shift_x=shift_x, suffixes=suffixes)


def parse_file(path: str) -> Document:
    with open(path, encoding="utf-8") as f:
        return parse_document(f.readlines())
