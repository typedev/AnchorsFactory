"""Parser for the new rule language (docs/DSL.md) -> IR (:class:`Document`).

A second front-end alongside :mod:`anchorsfactory.parser`; both produce the
same :class:`Document`, so the engine is unchanged. Surface form::

    @label = name (X Y), ...
    selector =  ...        # replace
    selector += ...        # accumulate
    !suffixes = .alt
    !shiftx   = -15
"""

from __future__ import annotations

import re

from .model import (
    Frame, HAlign, VEdge, Run, Frac,
    X, XAbs, Y, YAbs, AnchorSpec,
    GlyphName, Unicode, UnicodeRange, Glob, Category, Op, Document,
)


class DSLError(ValueError):
    """Raised on a malformed line, with line context."""


_FRAME = {"width": Frame.ADVANCE, "box": Frame.BOX, "outline": Frame.OUTLINE}
_HALIGN = {"left": HAlign.LEFT, "center": HAlign.CENTER, "right": HAlign.RIGHT}
_RUN = {"first": Run.FIRST, "last": Run.LAST}
_EDGE = {"top": VEdge.TOP, "middle": VEdge.MIDDLE, "bottom": VEdge.BOTTOM}

_ANCHOR_RE = re.compile(r"^(\S+)\s*\(\s*(\S+)\s+(\S+)\s*\)$")
_RULE_RE = re.compile(r"^(.*?)\s*(\+=|=)\s*(.*)$")


# --------------------------------------------------------------------------- #
#  X / Y tokens
# --------------------------------------------------------------------------- #
def _parse_x(tok: str):
    try:
        return XAbs(int(tok))
    except ValueError:
        pass
    base, _, edge = tok.partition("@")
    parts = base.split(".")
    if parts[0] not in _FRAME:
        raise DSLError(f"unknown X frame in {tok!r}")
    frame = _FRAME[parts[0]]
    rest = parts[1:]
    run = None
    if len(rest) == 2:
        run_tok, align_tok = rest
        if run_tok in _RUN:
            run = _RUN[run_tok]
        else:
            try:
                run = int(run_tok)
            except ValueError:
                raise DSLError(f"bad run {run_tok!r} in {tok!r}")
    elif len(rest) == 1:
        align_tok = rest[0]
    else:
        raise DSLError(f"malformed X token {tok!r}")
    if align_tok not in _HALIGN:
        raise DSLError(f"unknown X align {align_tok!r} in {tok!r}")
    at = _EDGE[edge] if edge else None
    return X(frame, _HALIGN[align_tok], run=run, at=at)


def _parse_y(tok: str):
    if not tok.startswith("$"):
        try:
            return YAbs(int(tok))
        except ValueError:
            raise DSLError(f"invalid Y position {tok!r}")
    body = tok[1:]
    if "*" in body:
        glyph, frac = body.split("*", 1)
        if "/" not in frac:
            raise DSLError(f"fraction must be d1/d2 in {tok!r}")
        d1, d2 = frac.split("/", 1)
        try:
            return Y(glyph, Frac(int(d1), int(d2)))
        except ValueError as e:
            raise DSLError(f"bad fraction in {tok!r}: {e}")
    if "." in body:
        glyph, _, suf = body.rpartition(".")
        if suf in _EDGE:
            return Y(glyph, _EDGE[suf])
    return Y(body, VEdge.TOP)


def _parse_anchor(tok: str) -> AnchorSpec:
    m = _ANCHOR_RE.match(tok)
    if not m:
        raise DSLError(f"anchor must be 'name (X Y)', got {tok!r}")
    name, xtok, ytok = m.groups()
    return AnchorSpec(name, _parse_x(xtok), _parse_y(ytok))


# --------------------------------------------------------------------------- #
#  Selectors
# --------------------------------------------------------------------------- #
def _parse_cp(s: str) -> int:
    return int(s.replace("U+", "").replace("u+", ""), 16)


def _parse_selector(tok: str):
    if tok.startswith(("U+", "u+")):
        if ".." in tok:
            a, b = tok.split("..", 1)
            return UnicodeRange(_parse_cp(a), _parse_cp(b))
        return Unicode(_parse_cp(tok))
    if tok.startswith("{") and tok.endswith("}"):
        return Category(tok[1:-1])
    if "*" in tok or "?" in tok:
        return Glob(tok)
    return GlyphName(tok)


# --------------------------------------------------------------------------- #
#  Lines
# --------------------------------------------------------------------------- #
def _split_items(rhs: str) -> list[str]:
    return [p.strip() for p in rhs.split(",") if p.strip()]


def parse_dsl(lines) -> Document:
    labels: dict[str, list[AnchorSpec]] = {}
    rules: list = []
    shift_x = 0
    suffixes = [""]

    raw_lines = []
    for n, line in enumerate(lines, 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        for stmt in line.split(";"):
            stmt = stmt.strip()
            if stmt:
                raw_lines.append((n, stmt))

    def expand(rhs: str, n: int) -> list[AnchorSpec]:
        specs: list[AnchorSpec] = []
        for item in _split_items(rhs):
            if item.startswith("@"):
                if item not in labels:
                    raise DSLError(f"line {n}: undefined label {item!r}")
                specs.extend(labels[item])
            else:
                try:
                    specs.append(_parse_anchor(item))
                except DSLError as e:
                    raise DSLError(f"line {n}: {e}")
        return specs

    for n, stmt in raw_lines:
        if stmt.startswith("!"):
            name, _, value = stmt[1:].partition("=")
            name, value = name.strip(), value.strip()
            if name == "suffixes":
                suffixes.extend((s.strip() if s.strip().startswith(".") else "." + s.strip())
                                for s in value.split(",") if s.strip())
            elif name == "shiftx":
                try:
                    shift_x = int(value)
                except ValueError:
                    raise DSLError(f"line {n}: !shiftx needs an integer, got {value!r}")
            else:
                raise DSLError(f"line {n}: unknown directive !{name}")
            continue

        m = _RULE_RE.match(stmt)
        if not m:
            raise DSLError(f"line {n}: missing '=' or '+=' in {stmt!r}")
        lhs, op_tok, rhs = m.group(1).strip(), m.group(2), m.group(3).strip()
        if not rhs:
            raise DSLError(f"line {n}: empty right-hand side")

        if lhs.startswith("@"):
            if op_tok != "=":
                raise DSLError(f"line {n}: labels only support '='")
            labels[lhs] = expand(rhs, n)
        else:
            op = Op.ADD if op_tok == "+=" else Op.REPLACE
            rules.append((_parse_selector(lhs), op, expand(rhs, n)))

    return Document(labels=labels, rules=rules, shift_x=shift_x, suffixes=suffixes)


def parse_dsl_file(path: str) -> Document:
    with open(path, encoding="utf-8") as f:
        return parse_dsl(f.readlines())
