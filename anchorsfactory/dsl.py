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
    Frame, Axis, HAlign, VEdge, Run, Frac, FONT_METRICS,
    Pos, Centroid, Abs, Y, FontMetric, Sum, Neg, EdgeOffset, AnchorSpec, AnchorRef, LabelRef, VarRef,
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
#  Position tokens — one `frame.[run.]align[@at]` grammar for both axes
# --------------------------------------------------------------------------- #
_COMP_RE = re.compile(r"^comp(\d+|last)\.(.+)$")


def _strip_component(tok: str):
    """Split an optional ``compN.``/``complast.`` prefix off a frame token,
    returning ``(component, rest)`` — component is 1-based (``-1`` = last), or
    ``None`` when absent. Index validity (≥1 / not on ``width``) is enforced by
    :class:`~anchorsfactory.model.Pos`."""
    m = _COMP_RE.match(tok)
    if not m:
        return None, tok
    return (-1 if m.group(1) == "last" else int(m.group(1))), m.group(2)


def _is_frame_token(tok: str) -> bool:
    """Whether *tok* opens a frame position (``box.…`` / ``box*n/m`` /
    ``outline.…@…``), optionally with a ``compN.`` component qualifier."""
    _, rest = _strip_component(tok)
    head = rest.split("@", 1)[0].split("*", 1)[0].split(".", 1)[0]
    return head in _FRAME


def _make_pos(*args, **kwargs):
    """Construct a :class:`Pos`, surfacing IR validation as a :class:`DSLError`."""
    try:
        return Pos(*args, **kwargs)
    except ValueError as e:
        raise DSLError(str(e))


def _parse_align(tok: str, axis: Axis, whole: str):
    table = _HALIGN if axis is Axis.X else _EDGE
    if tok not in table:
        kind = "X" if axis is Axis.X else "Y"
        raise DSLError(f"unknown {kind} align {tok!r} in {whole!r}")
    return table[tok]


_EDGEOFF_RE = re.compile(r"^(top|bottom|left|right)([+-]\d+)$")


def _parse_at(tok: str, axis: Axis):
    """The ``@`` sample line — a bare own-edge sentinel, an own-edge plus a signed
    offset (``top-10``), else a position on the *other* axis (X.at is a height;
    Y.at is a column)."""
    m = _EDGEOFF_RE.match(tok)
    if axis is Axis.X:                       # a height
        if tok in ("top", "bottom"):
            return _EDGE[tok]                # the glyph's own extreme
        if m and m.group(1) in ("top", "bottom"):
            return EdgeOffset(_EDGE[m.group(1)], int(m.group(2)))
        return _parse_slot(tok, Axis.Y)
    if tok in ("left", "right"):             # axis Y → a column; own side
        return _HALIGN[tok]
    if m and m.group(1) in ("left", "right"):
        return EdgeOffset(_HALIGN[m.group(1)], int(m.group(2)))
    return _parse_slot(tok, Axis.X)


def _parse_pos(tok: str, axis: Axis):
    """``[compN.]frame.[run.]align[@at]`` | ``frame*n/m`` | ``outline.centroid``
    → :class:`Pos` / :class:`Centroid` for *axis*."""
    component, tok = _strip_component(tok)
    base, sep, at_tok = tok.partition("@")
    if "*" in base:                           # a fractional position: frame*n/m
        framepart, _, fractok = base.partition("*")
        if framepart not in _FRAME:
            raise DSLError(f"unknown frame in {tok!r}")
        if sep:
            raise DSLError(f"a fractional position takes no '@', got {tok!r}")
        if "/" not in fractok:
            raise DSLError(f"fraction must be n/m in {tok!r}")
        a, b = fractok.split("/", 1)
        try:
            frac = Frac(int(a), int(b))
        except ValueError as e:
            raise DSLError(f"bad fraction {fractok!r} in {tok!r}: {e}")
        return _make_pos(_FRAME[framepart], frac, axis=axis, component=component)
    parts = base.split(".")
    frame = _FRAME[parts[0]]                  # caller guarantees parts[0] is a frame
    rest = parts[1:]
    if rest == ["centroid"]:                  # the one global, axis-free position
        if frame is not Frame.OUTLINE:
            raise DSLError(f"centroid only applies to outline, got {tok!r}")
        if sep:
            raise DSLError(f"outline.centroid takes no '@', got {tok!r}")
        return Centroid(component=component)
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
        raise DSLError(f"malformed position token {tok!r}")
    at = _parse_at(at_tok, axis) if sep else None
    return _make_pos(frame, _parse_align(align_tok, axis, tok), run=run, at=at,
                     axis=axis, component=component)


def _split_signed(expr: str):
    """Split a sum into ``(sign, term)`` pairs on top-level ``+``/``-``.

    On Y a ``-`` adjacent to a ``$glyph`` reference is read as a *subtraction*
    (the glyph name ends at the operator); a glyph literally named with ``-``
    can't be referenced inline — the missing-glyph fallback flags it at apply."""
    out, sign, buf = [], 1, ""
    for ch in expr:
        if ch in "+-":
            if buf == "":                    # a sign prefix, e.g. a leading '-'
                if ch == "-":
                    sign = -sign
                continue
            out.append((sign, buf))
            buf, sign = "", (-1 if ch == "-" else 1)
        else:
            buf += ch
    if buf:
        out.append((sign, buf))
    return out


def _parse_sum(tok: str, axis: Axis):
    terms = []
    for sign, term in _split_signed(tok):
        node = _parse_slot(term, axis)
        terms.append(Neg(node) if sign < 0 else node)
    return Sum(tuple(terms)) if len(terms) > 1 else terms[0]


def _has_sum_op(tok: str) -> bool:
    """A top-level ``+``/``-`` operator (not inside an ``@`` tail, not a leading
    sign or a negative literal)."""
    return "@" not in tok and ("+" in tok or "-" in tok[1:])


def _parse_slot(tok: str, axis: Axis):
    """Parse one axis slot of an anchor (or a variable value). Shared grammar:
    ``&var`` | number | sum | ``frame.position`` | (Y only) metric / ``$glyph``."""
    if _has_sum_op(tok):                      # base position + bias / summed heights
        return _parse_sum(tok, axis)
    if tok.startswith("&"):                  # a &variable standing in for the slot
        return VarRef(tok)
    if tok.startswith("%"):                  # %anchor — another anchor's position
        name = tok[1:]
        if not _NAME_RE.match(name):
            raise DSLError(f"bad anchor reference {tok!r}")
        return AnchorRef(name)
    try:                                     # bare number — polymorphic absolute
        return Abs(int(tok))
    except ValueError:
        pass
    if _is_frame_token(tok):                 # frame.position (both axes) incl centroid
        return _parse_pos(tok, axis)
    if axis is Axis.Y:                       # Y-only: metric / $glyph
        return _parse_y_term(tok)
    raise DSLError(f"unknown X position {tok!r}")


def _parse_x(tok: str):
    return _parse_slot(tok, Axis.X)


def _parse_y(tok: str):
    return _parse_slot(tok, Axis.Y)


def _parse_y_term(tok: str):
    if tok.startswith("&"):                 # a &variable as a (Y) term
        return VarRef(tok)
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
            return Abs(int(tok))
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


def _parse_var_def(tok: str):
    """Parse the value of a `&name = …` definition into an axis strategy.

    Axis-agnostic: the same grammar as an anchor's X or Y slot, but which axis a
    variable *is* falls out of what it parses to (a frame token / centroid → X;
    a metric / `$glyph` → Y; a bare number or centroid stays polymorphic; a sum
    is typed by its terms; a lone `&other` aliases another variable). The slot it
    is later used in decides compatibility — checked at apply time, not here.
    """
    if " " in tok:
        raise DSLError(f"variable value must be a single X or Y expression, got {tok!r}")
    if tok.startswith("&"):                 # alias to another variable
        return VarRef(tok)
    try:
        return Abs(int(tok))               # bare number — usable on either axis
    except ValueError:
        pass
    try:
        return _parse_x(tok)               # frame / centroid / X-sum → X
    except DSLError:
        return _parse_y(tok)               # else metric / $glyph / Y-sum → Y (may raise)


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
    variables: dict[str, object] = {}
    rules: list = []
    sources: list[int] = []                    # source line per rule (parallel to rules)
    shift_x = 0
    suffix_ops: list = []
    extends: list[str] = []
    propagate = "none"

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
            elif name == "propagate":
                if op_tok != "=":
                    raise DSLError(f"line {n}: !propagate only supports '='")
                if value not in ("none", "composites", "all"):
                    raise DSLError(f"line {n}: !propagate takes none|composites|all, "
                                   f"got {value!r}")
                propagate = value
            else:
                raise DSLError(f"line {n}: unknown directive !{name}")
            continue

        m = _RULE_RE.match(stmt)
        if not m:
            raise DSLError(f"line {n}: missing '=' or '+=' in {stmt!r}")
        lhs, op_tok, rhs = m.group(1).strip(), m.group(2), m.group(3).strip()
        if not rhs:
            raise DSLError(f"line {n}: empty right-hand side")

        if lhs.startswith("&"):
            if op_tok != "=":
                raise DSLError(f"line {n}: variables only support '='")
            if not _NAME_RE.match(lhs[1:]):
                raise DSLError(f"line {n}: bad variable name {lhs!r}")
            try:
                variables[lhs] = _parse_var_def(rhs)   # last definition wins
            except DSLError as e:
                raise DSLError(f"line {n}: {e}")
        elif lhs.startswith("@"):
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
                sources.append(n)              # every selector on this line shares line n

    return Document(labels=labels, variables=variables, rules=rules,
                    sources=sources, shift_x=shift_x, suffix_ops=suffix_ops,
                    extends=extends, propagate=propagate)


def parse_dsl_file(path: str) -> Document:
    with open(path, encoding="utf-8") as f:
        return parse_dsl(f.readlines())
