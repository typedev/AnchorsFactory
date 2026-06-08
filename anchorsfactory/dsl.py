"""Parser for the new rule language (docs/anchor-rules.md) -> IR (:class:`Document`).

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
    Frame, HAlign, VEdge, Run, Frac, FONT_METRICS,
    X, XAbs, Y, YAbs, FontMetric, YSum, AnchorSpec, LabelRef,
    GlyphName, Unicode, UnicodeRange, Glob, Category, Op, Document,
)


class DSLError(ValueError):
    """Raised on a malformed line, with line context."""


_FRAME = {"width": Frame.ADVANCE, "box": Frame.BOX, "outline": Frame.OUTLINE}
_HALIGN = {"left": HAlign.LEFT, "center": HAlign.CENTER, "right": HAlign.RIGHT}
_RUN = {"first": Run.FIRST, "last": Run.LAST}
_EDGE = {"top": VEdge.TOP, "middle": VEdge.MIDDLE, "bottom": VEdge.BOTTOM}

_ANCHOR_RE = re.compile(r"^(\S+)\s*\(\s*(\S+)\s+(\S+)\s*\)$")
_RULE_RE = re.compile(r"^(.*?)\s*(\+=|-=|=)\s*(.*)$")
_NAME_RE = re.compile(r"^[\w.]+$")
_OPS = {"=": Op.REPLACE, "+=": Op.ADD, "-=": Op.REMOVE}


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
    at = None
    if edge:
        # @top/@bottom = the glyph's own extreme; otherwise a fixed sample height
        at = _EDGE[edge] if edge in _EDGE else _parse_y(edge)
    return X(frame, _HALIGN[align_tok], run=run, at=at)


def _parse_y(tok: str):
    if "+" in tok:                          # a sum of terms: a+b+c
        return YSum(tuple(_parse_y_term(t) for t in tok.split("+") if t))
    return _parse_y_term(tok)


def _parse_y_term(tok: str):
    if not tok.startswith("$"):
        base, star, frac = tok.partition("*")
        if base in FONT_METRICS:                 # font metric, optionally *d1/d2
            if not star:
                return FontMetric(base)
            if "/" not in frac:
                raise DSLError(f"fraction must be d1/d2 in {tok!r}")
            d1, d2 = frac.split("/", 1)
            try:
                return FontMetric(base, Frac(int(d1), int(d2)))
            except ValueError as e:
                raise DSLError(f"bad fraction in {tok!r}: {e}")
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


def _norm_sfx(tok: str) -> str:
    tok = tok.strip()
    return tok if tok.startswith(".") else "." + tok


def _parse_suffix_op(op_tok: str, value: str, n: int):
    """Parse one `!suffixes` directive into a `(Op, kind, payload)` tuple.

    `= all [except .a, .b]` / `= none` reset to dynamic / empty (replace only);
    `= / += / -= .a, .b` set / add / remove explicit suffixes.
    """
    op = _OPS[op_tok]
    v = value.strip()
    low = v.lower()
    if low == "all" or low.startswith("all "):
        if op is not Op.REPLACE:
            raise DSLError(f"line {n}: '!suffixes {op_tok} all' is invalid — 'all' needs '='")
        rest = v[3:].strip()
        deny = ()
        if rest:
            if not rest.lower().startswith("except"):
                raise DSLError(f"line {n}: expected 'all except <suffixes>', got {v!r}")
            deny = tuple(_norm_sfx(s) for s in rest[6:].split(",") if s.strip())
        return (Op.REPLACE, "all", deny)
    if low == "none":
        if op is not Op.REPLACE:
            raise DSLError(f"line {n}: '!suffixes {op_tok} none' is invalid — 'none' needs '='")
        return (Op.REPLACE, "list", ())
    items = tuple(_norm_sfx(s) for s in v.split(",") if s.strip())
    if not items:
        raise DSLError(f"line {n}: !suffixes {op_tok} needs at least one suffix")
    return (op, "list", items)


def parse_dsl(lines) -> Document:
    labels: dict[str, list[AnchorSpec]] = {}
    rules: list = []
    shift_x = 0
    suffix_ops: list = []
    extends: list[str] = []

    raw_lines = []
    for n, line in enumerate(lines, 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        for stmt in line.split(";"):
            stmt = stmt.strip()
            if stmt:
                raw_lines.append((n, stmt))

    def parse_items(rhs: str, n: int) -> list:
        # anchors and label refs, unresolved (labels are bound late, at apply)
        items = []
        for item in _split_items(rhs):
            if item.startswith("@"):
                items.append(LabelRef(item))
            else:
                try:
                    items.append(_parse_anchor(item))
                except DSLError as e:
                    raise DSLError(f"line {n}: {e}")
        return items

    def parse_remove(rhs: str, n: int) -> list:
        # '-=' takes anchor names (bare) or @labels to strip
        targets = []
        for item in _split_items(rhs):
            if item.startswith("@"):
                targets.append(LabelRef(item))
            elif _NAME_RE.match(item):
                targets.append(item)
            else:
                raise DSLError(f"line {n}: '-=' takes anchor names or @labels, got {item!r}")
        return targets

    for n, stmt in raw_lines:
        if stmt.startswith("!"):
            body = stmt[1:].strip()
            m = _RULE_RE.match(body)
            if m:                                  # "!name OP value" (=, +=, -=)
                name, op_tok, value = m.group(1).strip(), m.group(2), m.group(3).strip()
            else:                                  # e.g. "!extends default"
                head, _, rest = body.partition(" ")
                name, op_tok, value = head.strip(), "=", rest.strip()
            if name == "suffixes":
                suffix_ops.append(_parse_suffix_op(op_tok, value, n))
            elif name == "shiftx":
                if op_tok != "=":
                    raise DSLError(f"line {n}: !shiftx only supports '='")
                try:
                    shift_x = int(value)
                except ValueError:
                    raise DSLError(f"line {n}: !shiftx needs an integer, got {value!r}")
            elif name == "extends":
                if op_tok != "=" or not value:
                    raise DSLError(f"line {n}: !extends needs a base name or path")
                extends.append(value)
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
            labels[lhs] = parse_items(rhs, n)
        else:
            op = _OPS[op_tok]
            items = parse_remove(rhs, n) if op is Op.REMOVE else parse_items(rhs, n)
            selectors = _split_items(lhs)        # `C, O, S` → one rule per selector
            if not selectors:
                raise DSLError(f"line {n}: empty left-hand side")
            for sel_tok in selectors:
                rules.append((_parse_selector(sel_tok), op, items))

    return Document(labels=labels, rules=rules, shift_x=shift_x,
                    suffix_ops=suffix_ops, extends=extends)


def parse_dsl_file(path: str) -> Document:
    with open(path, encoding="utf-8") as f:
        return parse_dsl(f.readlines())
