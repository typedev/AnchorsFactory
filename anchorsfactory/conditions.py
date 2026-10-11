"""Conditional blocks — ``!if`` / ``!elif`` / ``!else`` / ``!endif`` — evaluated
per master.

One rule file (``.anchors``) or construction file (``.glyphsConstruction``) can
serve every master of a family: a block's branches are chosen against a
:class:`RuleContext` (the master's style name and its axis location), the
inactive lines are dropped, and the active ones are kept **in source order**,
so the usual semantics (last definition wins, ``=``/``+=``/``-=``) apply to the
result unchanged::

    L += dot (width*4/7 capHeight*1/2)
    !if ital.xvalue == 1
    L += dot (width*1/2 capHeight*1/2)
    !elif "Bold" in styleName
    &dotY = capHeight*5/9
    !else
    &dotY = capHeight*1/2
    !endif

Directives sit alone on their line (a trailing ``# comment`` is allowed) and
nest. A condition is a small expression language — **no** ``eval()``:

- ``styleName`` (a string), ``<axis>.xvalue`` (design coordinate) and
  ``<axis>.uservalue`` (user coordinate), with ``<axis>`` an axis tag or name;
- ``"double-quoted"`` strings and numbers;
- ``== != < <= > >=``, ``in`` / ``not in`` (substring), ``not``, ``and``,
  ``or``, parentheses.

Types are checked when the file is parsed, so ``styleName > 3`` is an error in
every branch, active or not. Evaluation short-circuits (an ``!elif`` after a
taken branch is not evaluated), and reaching an axis the context has no value
for is an error with the line number — never a silent false.

Resolving **blanks** inactive lines (and the directive lines themselves) rather
than deleting them, so line numbers — :class:`~anchorsfactory.model.RuleSource`
and the construction-line mapping in :mod:`anchorsfactory.composites` — stay
those of the file the user is editing.
"""

from __future__ import annotations

import os
import plistlib
import re
from dataclasses import dataclass, field, replace
from typing import Mapping, Optional, Union

from .model import Document, merge_documents, restamp


class ConditionError(ValueError):
    """A malformed or unevaluable conditional block, with its line number.

    At parse time a rule file reports these as
    :class:`~anchorsfactory.dsl.DSLError` (like any other line error); this type
    surfaces from :meth:`Document.resolve` / construction parsing, when a
    condition is evaluated against a context."""


# --------------------------------------------------------------------------- #
#  Context
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RuleContext:
    """What a condition can see for one master.

    ``style_name`` — the master's style name. ``None`` means "not given": the
    font's ``info.styleName`` is used (see :meth:`for_font`), and failing that
    ``""``, against which ``styleName`` conditions are simply false. A context
    built from a designspace (:func:`contexts_from_designspace`) carries the
    source's ``stylename``, which wins over fontinfo.

    ``xvalues`` / ``uservalues`` — the master's location in design and user
    coordinates, keyed by axis **name** or **tag**. ``axis_aliases`` maps a tag
    to its name (and is read both ways), so ``wght.xvalue`` and
    ``weight.xvalue`` find the same value.

    ``axes`` — every axis name and tag the family defines, when known (a
    designspace). With it, a condition naming any other axis is an error even
    in a branch that is not reached (a typo-catcher); without it (``None``),
    only an axis lookup that is actually evaluated can fail.
    """
    style_name: Optional[str] = None
    xvalues: Mapping[str, float] = field(default_factory=dict)
    uservalues: Mapping[str, float] = field(default_factory=dict)
    axis_aliases: Mapping[str, str] = field(default_factory=dict)
    axes: Optional[frozenset] = None

    def for_font(self, font) -> "RuleContext":
        """This context with ``style_name`` filled from *font*'s
        ``info.styleName`` when it was not given (``""`` if the font has none)."""
        if self.style_name is not None:
            return self
        try:
            style = font.info.styleName
        except AttributeError:
            style = None
        return replace(self, style_name=style or "")

    def axis_value(self, axis: str, kind: str):
        """The *kind* (``"xvalue"``/``"uservalue"``) coordinate of *axis* (a
        name or tag), or ``None`` if the context has none."""
        values = self.xvalues if kind == "xvalue" else self.uservalues
        for key in self._axis_keys(axis):
            if key in values:
                return values[key]
        return None

    def knows_axis(self, axis: str) -> bool:
        if self.axes is None:
            return True
        return any(k in self.axes for k in self._axis_keys(axis))

    def _axis_keys(self, axis: str):
        yield axis
        if axis in self.axis_aliases:
            yield self.axis_aliases[axis]
        for tag, name in self.axis_aliases.items():
            if name == axis:
                yield tag


_LOCATION_RE = re.compile(r"^\s*([A-Za-z_][\w]*)\.(xvalue|uservalue)\s*=\s*(\S+)\s*$")


def parse_location(specs) -> tuple[dict, dict]:
    """Parse ``["ital.xvalue=1", "wght.uservalue=700"]`` (the CLI's
    ``--location``) into ``(xvalues, uservalues)``."""
    xvalues, uservalues = {}, {}
    for spec in specs or ():
        m = _LOCATION_RE.match(spec)
        if not m:
            raise ValueError(f"bad location {spec!r}; expected AXIS.xvalue=N "
                             f"or AXIS.uservalue=N")
        axis, kind, raw = m.groups()
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(f"bad location {spec!r}: {raw!r} is not a number")
        (xvalues if kind == "xvalue" else uservalues)[axis] = value
    return xvalues, uservalues


def _fontinfo_style_name(ufo_path: str) -> Optional[str]:
    try:
        with open(os.path.join(ufo_path, "fontinfo.plist"), "rb") as f:
            return plistlib.load(f).get("styleName")
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def contexts_from_designspace(designspace) -> dict:
    """``{absolute UFO path: RuleContext}`` for every source of *designspace*
    (a path or a loaded :class:`~fontTools.designspaceLib.DesignSpaceDocument`).

    Each context carries the source's full design location (``xvalues``, axis
    defaults filled in), the same location mapped to user coordinates through
    the axis maps (``uservalues``), the tag→name aliases and the axis set.
    ``style_name`` is the source's ``stylename``; only when the source has none
    does the UFO's own fontinfo ``styleName`` apply (and failing both, ``""``).
    Sparse-layer sources (a ``layer=`` on the source) share their UFO with a
    full master and are skipped.
    """
    from fontTools.designspaceLib import DesignSpaceDocument
    doc = designspace
    if not isinstance(doc, DesignSpaceDocument):
        doc = DesignSpaceDocument.fromfile(designspace)
    aliases = {a.tag: a.name for a in doc.axes}
    axes = frozenset(aliases) | frozenset(aliases.values())
    out = {}
    for source in doc.sources:
        if source.layerName or not source.path:
            continue
        design = source.getFullDesignLocation(doc)
        user = doc.map_backward(design)
        path = os.path.abspath(source.path)
        style = source.styleName or _fontinfo_style_name(path) or ""
        out[path] = RuleContext(style_name=style, xvalues=dict(design),
                                uservalues=dict(user), axis_aliases=aliases,
                                axes=axes)
    return out


# --------------------------------------------------------------------------- #
#  Condition expressions
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Lit:
    value: Union[str, float]

    def __str__(self):
        if isinstance(self.value, str):
            return f'"{self.value}"'
        return f"{self.value:g}"


@dataclass(frozen=True)
class StyleName:
    def __str__(self):
        return "styleName"


@dataclass(frozen=True)
class AxisValue:
    axis: str
    kind: str                     # "xvalue" | "uservalue"

    def __str__(self):
        return f"{self.axis}.{self.kind}"


@dataclass(frozen=True)
class Compare:
    op: str                       # == != < <= > >= in "not in"
    left: object
    right: object

    def __str__(self):
        return f"{self.left} {self.op} {self.right}"


@dataclass(frozen=True)
class Not:
    operand: object

    def __str__(self):
        return f"not {self.operand}"


@dataclass(frozen=True)
class BoolOp:
    op: str                       # "and" | "or"
    left: object
    right: object

    def __str__(self):
        return f"({self.left} {self.op} {self.right})"


_TOKEN_RE = re.compile(r"""
    \s*(?:
      (?P<str>"[^"]*")
    | (?P<num>-?\d+(?:\.\d+)?|-?\.\d+)
    | (?P<op>==|!=|<=|>=|<|>|\(|\))
    | (?P<word>[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)?)
    )""", re.VERBOSE)

# Spelled here (the vocabulary module imports these, never the reverse).
_KEYWORDS = ("and", "or", "not", "in")
_STYLE_NAME = "styleName"
_AXIS_KINDS = ("xvalue", "uservalue")
_CMP_OPS = ("==", "!=", "<", "<=", ">", ">=")


def _tokenize(text: str):
    pos, toks = 0, []
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            rest = text[pos:].strip()
            if rest.startswith('"'):
                raise ConditionError(f"unterminated string {rest!r}")
            raise ConditionError(f"unexpected {rest[:12]!r}")
        kind = m.lastgroup
        tok = m.group(kind)
        toks.append((kind, tok))
        pos = m.end()
    return toks


def _type(node) -> str:
    if isinstance(node, Lit):
        return "string" if isinstance(node.value, str) else "number"
    if isinstance(node, StyleName):
        return "string"
    if isinstance(node, AxisValue):
        return "number"
    return "bool"


class _CondParser:
    def __init__(self, text: str):
        self.toks = _tokenize(text)
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def is_word(self, word, k=0):
        kind, tok = self.peek(k)
        return kind == "word" and tok == word

    def parse(self):
        if not self.toks:
            raise ConditionError("missing condition")
        node = self.or_()
        if self.i < len(self.toks):
            raise ConditionError(f"unexpected {self.peek()[1]!r}")
        if _type(node) != "bool":
            raise ConditionError(f"{node} is a value, not a condition — "
                                 f"compare it (==, !=, <, in, …)")
        return node

    def or_(self):
        node = self.and_()
        while self.is_word("or"):
            self.take()
            node = BoolOp("or", self._bool(node), self._bool(self.and_()))
        return node

    def and_(self):
        node = self.not_()
        while self.is_word("and"):
            self.take()
            node = BoolOp("and", self._bool(node), self._bool(self.not_()))
        return node

    def not_(self):
        if self.is_word("not"):
            self.take()
            return Not(self._bool(self.not_()))
        return self.compare()

    def compare(self):
        left = self.operand()
        kind, tok = self.peek()
        if kind == "op" and tok in _CMP_OPS:
            self.take()
            op = tok
        elif self.is_word("in"):
            self.take()
            op = "in"
        elif self.is_word("not") and self.is_word("in", 1):
            self.take(), self.take()
            op = "not in"
        else:
            return left
        right = self.operand()
        lt, rt = _type(left), _type(right)
        if "bool" in (lt, rt):
            raise ConditionError(f"cannot compare a condition with {op!r} — "
                                 f"use parentheses with and/or/not")
        if lt != rt:
            raise ConditionError(f"cannot compare {lt} {left} with {rt} {right}")
        if op in ("in", "not in") and lt != "string":
            raise ConditionError(f"{op!r} tests a substring; {left} and {right} "
                                 f"are numbers")
        if op in ("<", "<=", ">", ">=") and lt != "number":
            raise ConditionError(f"{op!r} compares numbers; {left} and {right} "
                                 f"are strings")
        return Compare(op, left, right)

    def operand(self):
        kind, tok = self.take()
        if kind is None:
            raise ConditionError("condition ends early")
        if kind == "str":
            return Lit(tok[1:-1])
        if kind == "num":
            return Lit(float(tok))
        if kind == "op" and tok == "(":
            node = self.or_()
            if self.take() != ("op", ")"):
                raise ConditionError("missing ')'")
            return node
        if kind == "word":
            if tok == _STYLE_NAME:
                return StyleName()
            if tok in _KEYWORDS:
                raise ConditionError(f"unexpected {tok!r}")
            head, dot, attr = tok.partition(".")
            if dot and attr in _AXIS_KINDS:
                return AxisValue(head, attr)
            if dot:
                raise ConditionError(f"{tok!r}: an axis takes .xvalue or "
                                     f".uservalue, not .{attr}")
            raise ConditionError(f"unknown name {tok!r} — use styleName, "
                                 f"<axis>.xvalue or <axis>.uservalue "
                                 f"(strings take double quotes)")
        raise ConditionError(f"unexpected {tok!r}")

    @staticmethod
    def _bool(node):
        if _type(node) != "bool":
            raise ConditionError(f"{node} is a value, not a condition")
        return node


def parse_condition(text: str):
    """Parse a condition expression to its AST (raises :class:`ConditionError`)."""
    return _CondParser(text).parse()


def _axis_refs(node):
    if isinstance(node, AxisValue):
        yield node
    elif isinstance(node, (Compare, BoolOp)):
        yield from _axis_refs(node.left)
        yield from _axis_refs(node.right)
    elif isinstance(node, Not):
        yield from _axis_refs(node.operand)


def evaluate(node, context: RuleContext, line: Optional[int] = None):
    """Evaluate a parsed condition against *context*."""
    where = f"line {line}: " if line is not None else ""
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, StyleName):
        return context.style_name or ""
    if isinstance(node, AxisValue):
        value = context.axis_value(node.axis, node.kind)
        if value is None:
            if not context.knows_axis(node.axis):
                raise ConditionError(f"{where}unknown axis {node.axis!r}")
            raise ConditionError(f"{where}no {node.kind} for axis {node.axis!r} "
                                 f"in this context (give a designspace or a "
                                 f"location)")
        return float(value)
    if isinstance(node, Not):
        return not evaluate(node.operand, context, line)
    if isinstance(node, BoolOp):
        left = evaluate(node.left, context, line)
        if node.op == "and":
            return left and evaluate(node.right, context, line)
        return left or evaluate(node.right, context, line)
    if isinstance(node, Compare):
        a = evaluate(node.left, context, line)
        b = evaluate(node.right, context, line)
        op = node.op
        if op == "in":
            return a in b
        if op == "not in":
            return a not in b
        return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b,
                ">": a > b, ">=": a >= b}[op]
    raise TypeError(f"not a condition node: {node!r}")


# --------------------------------------------------------------------------- #
#  Block structure
# --------------------------------------------------------------------------- #

#: The block directives, in the order a block uses them.
KEYWORDS = ("if", "elif", "else", "endif")

_DIRECTIVE_RE = re.compile(r"^!(if|elif|else|endif)(?![\w.])(.*)$")


@dataclass(frozen=True)
class Branch:
    """One arm of a block: its directive ``line``, its ``keyword`` (``if`` /
    ``elif`` / ``else``), its parsed ``condition`` (``None`` for ``else``), the
    body line range ``start..end`` (inclusive; empty when ``end < start``) and
    the blocks nested in that body."""
    line: int
    keyword: str
    condition: object
    start: int
    end: int
    children: tuple = ()


@dataclass(frozen=True)
class Block:
    """An ``!if … !endif`` block: its branches and its ``!endif`` line."""
    branches: tuple
    end_line: int

    @property
    def start_line(self) -> int:
        return self.branches[0].line


def _lines(text_or_lines) -> list:
    if isinstance(text_or_lines, str):
        return text_or_lines.split("\n")
    return list(text_or_lines)


def _directive(raw: str):
    """``(keyword, rest)`` if *raw* is a block directive line, else ``None``."""
    line = raw.split("#", 1)[0].strip()
    m = _DIRECTIVE_RE.match(line)
    return (m.group(1), m.group(2).strip()) if m else None


def is_directive_line(raw: str) -> bool:
    """Whether *raw* is an ``!if``/``!elif``/``!else``/``!endif`` line."""
    return _directive(raw) is not None


def scan_blocks(text_or_lines) -> tuple:
    """Parse the block structure of a text (or its lines).

    Returns the top-level :class:`Block`\\ s. Every condition is parsed (so a
    syntax or type error in any branch is reported here) but none is evaluated.
    Raises :class:`ConditionError` with the line number on a stray
    ``!elif``/``!else``/``!endif``, an ``!elif`` after ``!else``, an unclosed
    ``!if``, or a directive that shares its line with something else.
    """
    lines = _lines(text_or_lines)
    # stack of open blocks: each is [branches(list of dict), children(list)]
    top: list = []
    stack: list = []

    def close_branch(frame, end):
        br = frame["branches"][-1]
        frame["done"].append(Branch(br["line"], br["keyword"], br["condition"],
                                    br["line"] + 1, end, tuple(br["children"])))

    for n, raw in enumerate(lines, 1):
        d = _directive(raw)
        if d is None:
            for stmt in raw.split("#", 1)[0].split(";")[1:]:
                late = _directive(stmt)
                if late is not None:
                    raise ConditionError(f"line {n}: !{late[0]} must be alone "
                                         f"on its line")
            continue
        kw, rest = d
        if ";" in rest:
            raise ConditionError(f"line {n}: !{kw} must be alone on its line")
        if kw in ("if", "elif"):
            if not rest:
                raise ConditionError(f"line {n}: !{kw} needs a condition")
            try:
                cond = parse_condition(rest)
            except ConditionError as e:
                raise ConditionError(f"line {n}: {e}") from None
        elif rest:
            raise ConditionError(f"line {n}: !{kw} takes no condition "
                                 f"(got {rest!r})")
        else:
            cond = None

        if kw == "if":
            stack.append({"branches": [{"line": n, "keyword": kw, "condition": cond,
                                        "children": []}],
                          "done": [], "else": False})
            continue
        if not stack:
            raise ConditionError(f"line {n}: !{kw} without !if")
        frame = stack[-1]
        if kw in ("elif", "else"):
            if frame["else"]:
                raise ConditionError(f"line {n}: !{kw} after !else")
            close_branch(frame, n - 1)
            frame["branches"].append({"line": n, "keyword": kw, "condition": cond,
                                      "children": []})
            frame["else"] = kw == "else"
            continue
        # endif
        close_branch(frame, n - 1)
        stack.pop()
        block = Block(tuple(frame["done"]), n)
        (stack[-1]["branches"][-1]["children"] if stack else top).append(block)

    if stack:
        raise ConditionError(f"line {stack[-1]['branches'][0]['line']}: "
                             f"!if without !endif")
    return tuple(top)


def _walk_blocks(blocks):
    for b in blocks:
        yield b
        for br in b.branches:
            yield from _walk_blocks(br.children)


def block_body_lines(blocks) -> set:
    """Every line inside any branch body of *blocks* (directive lines excluded)."""
    out = set()
    for b in _walk_blocks(blocks):
        for br in b.branches:
            out.update(range(br.start, br.end + 1))
    return out


def directive_lines(blocks) -> set:
    out = set()
    for b in _walk_blocks(blocks):
        out.update(br.line for br in b.branches)
        out.add(b.end_line)
    return out


def _check_axes(blocks, context: RuleContext):
    if context.axes is None:
        return
    for b in _walk_blocks(blocks):
        for br in b.branches:
            for ref in _axis_refs(br.condition):
                if not context.knows_axis(ref.axis):
                    raise ConditionError(f"line {br.line}: unknown axis "
                                         f"{ref.axis!r}; this family has "
                                         f"{', '.join(sorted(context.axes))}")


def _inactive(blocks, context: RuleContext) -> set:
    _check_axes(blocks, context)
    out: set = set()

    def walk(blocks):
        for b in blocks:
            taken = False
            for br in b.branches:
                ok = (not taken and
                      (br.condition is None
                       or bool(evaluate(br.condition, context, br.line))))
                if ok:
                    taken = True
                    walk(br.children)
                else:
                    out.update(range(br.start, br.end + 1))
    walk(blocks)
    return out


def _as_context(context) -> RuleContext:
    if context is None:
        return RuleContext()
    if not isinstance(context, RuleContext):
        raise TypeError(f"expected a RuleContext, got {type(context).__name__}")
    return context


def _source_lines(text_or_doc):
    if isinstance(text_or_doc, Document):
        if text_or_doc.layers:
            raise ValueError("a merged document has one text per layer; pass "
                             "each layer (doc.layers[i]) or the text itself")
        if text_or_doc.conditional is None:
            return None
        return list(text_or_doc.conditional.lines)
    return _lines(text_or_doc)


def inactive_lines(text_or_doc, context) -> set:
    """1-based lines that are dropped for *context*: the bodies of branches not
    taken, including any blocks nested in them. Directive lines of the blocks
    that *are* reached are in neither this set nor :func:`active_lines`."""
    lines = _source_lines(text_or_doc)
    if lines is None:
        return set()
    return _inactive(scan_blocks(lines), _as_context(context))


def active_lines(text_or_doc, context) -> set:
    """1-based lines whose content takes effect for *context*: every line that
    is neither in an untaken branch nor a block directive."""
    lines = _source_lines(text_or_doc)
    if lines is None:
        if isinstance(text_or_doc, Document):
            return set()       # no text kept: nothing to dim
        lines = []
    blocks = scan_blocks(lines)
    dropped = _inactive(blocks, _as_context(context)) | directive_lines(blocks)
    return {n for n in range(1, len(lines) + 1) if n not in dropped}


def blank_inactive(text_or_lines, context):
    """*text_or_lines* with the untaken branches and every directive line
    replaced by empty lines — same line count, so line numbers survive.
    Returns a ``str`` for a ``str`` (split/joined on ``\\n``), else a list."""
    lines = _lines(text_or_lines)
    blocks = scan_blocks(lines)
    if not blocks:
        return text_or_lines if isinstance(text_or_lines, str) else lines
    drop = _inactive(blocks, _as_context(context)) | directive_lines(blocks)
    out = ["" if n in drop else line for n, line in enumerate(lines, 1)]
    return "\n".join(out) if isinstance(text_or_lines, str) else out


def has_conditionals(text_or_lines) -> bool:
    """Whether a text has any block directive line (a cheap pre-check)."""
    return any(is_directive_line(l) for l in _lines(text_or_lines))


# --------------------------------------------------------------------------- #
#  Documents
# --------------------------------------------------------------------------- #

def resolve_document(doc: Document, context) -> Document:
    """The flat document *doc* describes for one master (*context*).

    Each conditional layer is re-parsed with its inactive branches blanked (so
    rules keep their file line numbers and origin); the layers are then merged
    again exactly as ``!extends`` merged them. A document with no conditionals
    is returned as is."""
    if not doc.has_conditionals:
        return doc
    context = _as_context(context)
    if doc.layers:
        out = None
        for layer in doc.layers:
            flat = resolve_document(layer, context)
            out = flat if out is None else merge_documents(out, flat)
        return out
    from .dsl import parse_flat
    flat = parse_flat(blank_inactive(list(doc.conditional.lines), context))
    if doc.conditional.origin is not None:
        flat = restamp(flat, origin=doc.conditional.origin)
    return flat


def all_branches(doc: Document) -> Document:
    """*doc* with **every** branch kept (directive lines only removed) — the
    permissive view a pre-flight check uses before any master is known: a
    label defined in one branch and used in another is not "undefined"."""
    if not doc.has_conditionals:
        return doc
    if doc.layers:
        out = None
        for layer in doc.layers:
            flat = all_branches(layer)
            out = flat if out is None else merge_documents(out, flat)
        return out
    from .dsl import parse_flat
    lines = list(doc.conditional.lines)
    drop = directive_lines(scan_blocks(lines))
    flat = parse_flat(["" if n in drop else l for n, l in enumerate(lines, 1)])
    if doc.conditional.origin is not None:
        flat = restamp(flat, origin=doc.conditional.origin)
    return flat


# --------------------------------------------------------------------------- #
#  Structural differences between masters
# --------------------------------------------------------------------------- #

def _anchor_names(entries) -> frozenset:
    names = set()
    for e in entries or ():
        if isinstance(e, str):
            names.add(e)
        elif isinstance(e, tuple):
            names.add(e[0])                       # (name, x, y)
        else:
            names.add(e.name)                     # PlacedAnchor / fontParts anchor
    return frozenset(names)


def _components(composite):
    if composite is None:
        return None
    if isinstance(composite, (tuple, list)):
        return tuple(composite)
    base = getattr(composite, "base", None)
    marks = tuple(m for m, _ in getattr(composite, "marks", ()))
    return ((base,) if base else ()) + marks


@dataclass
class StructureDiff:
    """Per-glyph structural differences across masters.

    ``anchors`` — ``{glyph: {label: frozenset of anchor names}}`` for glyphs
    whose anchor-name set differs between masters (a master without the glyph
    counts as the empty set). ``composites`` — ``{glyph: {label: (base,
    *marks) or None}}`` for composites whose component list differs (``None``:
    not built for that master). Differences are allowed — a designer may build
    composites and strip anchors before interpolating — so they are reported
    as warnings, not errors."""
    anchors: dict = field(default_factory=dict)
    composites: dict = field(default_factory=dict)

    def __bool__(self):
        return bool(self.anchors or self.composites)

    def warnings(self) -> list:
        out = []
        for g, per in sorted(self.anchors.items()):
            parts = "; ".join(f"{lbl}: {' '.join(sorted(names)) or '(none)'}"
                              for lbl, names in per.items())
            out.append(f"{g}: anchor sets differ across masters — {parts}")
        for g, per in sorted(self.composites.items()):
            parts = "; ".join(f"{lbl}: {' + '.join(c) if c else '(not built)'}"
                              for lbl, c in per.items())
            out.append(f"{g}: components differ across masters — {parts}")
        return out


def structure_diff(anchors=None, composites=None) -> StructureDiff:
    """Compare per-master results and report what is not structurally
    compatible.

    *anchors* is ``{label: result}`` where a result maps glyph → anchors: a
    :class:`~anchorsfactory.apply.ComputeResult` (``(name, x, y)`` rows), an
    :class:`~anchorsfactory.apply.ExplainResult` (:class:`PlacedAnchor` rows),
    or any ``{glyph: iterable of names}``. *composites* is ``{label: {name:
    Composite}}`` as :func:`~anchorsfactory.composites.build_composites`
    returns (or ``{name: (base, *marks)}``).
    """
    diff = StructureDiff()
    if anchors:
        labels = list(anchors)
        glyphs = set().union(*(set(r) for r in anchors.values()))
        for g in glyphs:
            per = {lbl: _anchor_names(anchors[lbl].get(g)) for lbl in labels}
            if len(set(per.values())) > 1:
                diff.anchors[g] = per
    if composites:
        labels = list(composites)
        glyphs = set().union(*(set(r) for r in composites.values()))
        for g in glyphs:
            per = {lbl: _components(composites[lbl].get(g)) for lbl in labels}
            if len(set(per.values())) > 1:
                diff.composites[g] = per
    return diff
