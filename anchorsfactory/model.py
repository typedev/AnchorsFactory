"""Internal representation (IR) for anchor placement rules.

This module is the contract between the rule parser(s) and the geometry
engine. Any DSL front-end — the current ``.txt`` format or a future syntax —
parses *into* these structures; the engine consumes them. The IR is
vocabulary-agnostic: it encodes *frame + position*, not surface keywords.

A single :class:`Pos` node carries a ``frame.position`` for either axis (its
``axis``): the ``align`` slot is an :class:`HAlign` (X: left/center/right), a
:class:`VEdge` (Y: bottom/middle/top), or a :class:`Frac` (a ``*n/m`` position
along the frame). ``run`` picks an ink span on an ``OUTLINE`` frame; ``at`` fixes
the sample line (a height on X, a column on Y). Other strategy nodes:
:class:`Centroid` (area centre of mass, polymorphic), :class:`Abs` (absolute,
axis-neutral), :class:`Sum` / :class:`Neg` (``+``/``-`` arithmetic), and the
Y-only :class:`FontMetric` and :class:`Y` (``$glyph``). ``X``, ``XAbs``/``YAbs``,
and ``YSum`` remain as back-compat aliases of ``Pos`` / ``Abs`` / ``Sum``.

Examples (surface token -> IR)::

    width.center     -> Pos ADVANCE/CENTER (X)           # advance midpoint
    box.right        -> Pos BOX/RIGHT (X)                # bbox xMax
    box*2/3          -> Pos BOX/Frac(2,3) (X)            # fractional position
    outline.first.center -> Pos OUTLINE/CENTER run=FIRST (X)   # left stem
    outline.center@top   -> Pos OUTLINE/CENTER at=VEdge.TOP (X)
    box.top          -> Pos BOX/VEdge.TOP (Y)            # this glyph's own bbox top
    outline.middle   -> Pos OUTLINE/VEdge.MIDDLE (Y)     # vertical span centre at X
    outline.centroid -> Centroid()                       # polymorphic, both axes
    400              -> Abs(400)                          # axis-neutral
    $H*5/6           -> Y("H", Frac(5, 6))               # fraction from baseline
    capHeight*1/2+xHeight*1/2 -> Sum(FontMetric, FontMetric)
    outline.centroid-25       -> Sum(Centroid, Neg(Abs(25)))

Dataclass ``__str__``\\ s render these tokens back, so the IR doubles as the
serializer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class Frame(Enum):
    """Reference system the coordinate is measured against."""
    ADVANCE = "width"    # the advance width: 0 .. glyph.width (X only)
    BOX = "box"          # the bounding box: xMin..xMax (X) / yMin..yMax (Y)
    OUTLINE = "outline"  # the actual contour, sampled on a perpendicular scanline


class Axis(Enum):
    """Which axis a :class:`Pos` is measured along.

    The same ``frame.position`` vocabulary works on both: on X an ``OUTLINE``
    position samples a *horizontal* scanline (left/right/center crossings); on Y
    a *vertical* one (bottom/middle/top crossings). ``ADVANCE`` is X-only.
    """
    X = "x"
    Y = "y"


class HAlign(Enum):
    """Horizontal position within the chosen frame."""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class VEdge(Enum):
    """A vertical extreme of a glyph's bounding box."""
    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


class Run(Enum):
    """Which ink span (stem) at a given height, for OUTLINE frames.

    Spans are the contour crossings paired left-to-right. ``FIRST`` is the
    leftmost span, ``LAST`` the rightmost. For three-or-more-stem glyphs
    (``m``, ``ш``, ``Ш``) use a 1-based integer instead.
    """
    FIRST = "first"
    LAST = "last"


@dataclass(frozen=True)
class Frac:
    """A fraction of a glyph's height, measured from the baseline."""
    num: int
    den: int

    def __post_init__(self):
        if self.den == 0:
            raise ValueError("Frac denominator must be non-zero")

    def __str__(self):
        return f"{self.num}/{self.den}"


# --------------------------------------------------------------------------- #
#  Frame-relative positions (both axes)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Pos:
    """A computed position along one axis: ``frame.[run.]align[@at]``.

    The same node serves both axes (set ``axis``). The ``align`` slot holds a
    :class:`HAlign` (left/center/right) on X, a :class:`VEdge`
    (bottom/middle/top) on Y, or a :class:`Frac` — a proportional position along
    the frame (``box.1/3``, ``width.2/3``), valid for BOX/ADVANCE only.

    For ``OUTLINE`` the contour is sampled on a scanline perpendicular to the
    axis (horizontal on X, vertical on Y). ``at`` overrides where that scanline
    sits and is therefore a position on the *other* axis:

    - on X: ``VEdge.TOP``/``BOTTOM`` (the glyph's own extreme) or a Y strategy
      (FontMetric/YAbs/Y/YSum) — a fixed height, decoupled from the anchor's Y;
    - on Y: ``HAlign.LEFT``/``RIGHT`` (the glyph's own side) or an X strategy
      (Pos/XAbs) — a fixed column, decoupled from the anchor's X.

    ``at=None`` samples at the anchor's other coordinate (see the resolver).
    """
    frame: Frame
    align: Union[HAlign, VEdge, Frac]
    run: Optional[Union[Run, int]] = None   # OUTLINE only; None = whole envelope
    at: object = None
    axis: Axis = Axis.X                      # last field: legacy X(...) calls keep working

    def __post_init__(self):
        if self.frame is Frame.ADVANCE and self.axis is Axis.Y:
            raise ValueError("ADVANCE has no vertical analogue; use a font metric")
        # align kind must match the axis (a Frac is allowed on either)
        if not isinstance(self.align, Frac):
            want = HAlign if self.axis is Axis.X else VEdge
            if not isinstance(self.align, want):
                raise ValueError(
                    f"{self.axis.value}-axis align must be {want.__name__} or Frac, "
                    f"not {type(self.align).__name__}")
        if self.frame is not Frame.OUTLINE:
            if self.run is not None:
                raise ValueError(f"`run` only applies to OUTLINE, not {self.frame.value}")
            if self.at is not None:
                raise ValueError(f"`@…` only applies to OUTLINE, not {self.frame.value}")
        if isinstance(self.align, Frac) and self.frame is Frame.OUTLINE:
            raise ValueError("a fractional position applies to BOX/ADVANCE, not OUTLINE")
        if isinstance(self.run, int) and not isinstance(self.run, bool) and self.run < 1:
            raise ValueError("integer `run` is 1-based and must be >= 1")
        if self.at is not None:
            if self.axis is Axis.X:
                if self.at is VEdge.MIDDLE:
                    raise ValueError("`@middle` is meaningless; sample height must be top or bottom")
                if isinstance(self.at, HAlign):
                    raise ValueError("on X, `@…` is a height (top/bottom or a Y value), not an X edge")
            else:
                if self.at is HAlign.CENTER:
                    raise ValueError("`@center` is meaningless; sample column must be left or right")
                if isinstance(self.at, VEdge):
                    raise ValueError("on Y, `@…` is a column (left/right or an X value), not a Y edge")

    def __str__(self):
        if isinstance(self.align, Frac):        # frame*n/m (no run/@ — validated)
            return f"{self.frame.value}*{self.align}"
        parts = [self.frame.value]
        if self.run is not None:
            parts.append(self.run.value if isinstance(self.run, Run) else str(self.run))
        parts.append(self.align.value)
        s = ".".join(parts)
        if self.at is not None:
            s += "@" + (self.at.value if isinstance(self.at, (VEdge, HAlign)) else str(self.at))
        return s


# Back-compat alias: this node was once X-only and is widely imported as ``X``.
X = Pos


@dataclass(frozen=True)
class Centroid:
    """``outline.centroid`` — the area centre of mass of the glyph's outline.

    A single 2-D point: on X it yields the centroid's x, on Y its y. Unlike the
    scanline-sampled ``outline.left/right/center``, it is a *global* property of
    the contour, so it is independent on both axes (no axis cycle) and takes no
    ``run``/``@``. Polymorphic like a bare number — usable in either slot.
    """

    def __str__(self):
        return "outline.centroid"


@dataclass(frozen=True)
class Abs:
    """An absolute position in font units. Axis-neutral: the same node serves
    either slot (a bare number is polymorphic), so no coercion is needed when a
    numeric variable crosses axes."""
    value: float

    def __str__(self):
        return str(self.value)


# Back-compat aliases: these were once two separate per-axis classes.
XAbs = Abs
YAbs = Abs


# --------------------------------------------------------------------------- #
#  Vertical (Y) strategies
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Y:
    """A height derived from a reference glyph's bounding box."""
    glyph: str
    ref: Union[VEdge, Frac] = VEdge.TOP

    def __str__(self):
        if isinstance(self.ref, Frac):
            return f"${self.glyph}*{self.ref}"
        suffix = "" if self.ref is VEdge.TOP else f".{self.ref.value}"
        return f"${self.glyph}{suffix}"


# Font-wide vertical metrics from font.info (plus the convenience `baseline`).
FONT_METRICS = ("ascender", "descender", "capHeight", "xHeight", "unitsPerEm", "baseline")


@dataclass(frozen=True)
class FontMetric:
    """A height taken from a font-wide vertical metric, optionally a fraction.

    Names match ``font.info`` (``ascender``, ``descender``, ``capHeight``,
    ``xHeight``, ``unitsPerEm``); ``baseline`` is 0.
    """
    name: str
    frac: Optional[Frac] = None

    def __post_init__(self):
        if self.name not in FONT_METRICS:
            raise ValueError(f"unknown font metric {self.name!r}; one of {FONT_METRICS}")

    def __str__(self):
        return f"{self.name}*{self.frac}" if self.frac else self.name


@dataclass(frozen=True)
class Sum:
    """A position that is the sum of several terms, resolved on the slot's axis.

    On Y a sum of heights (``capHeight*1/2+xHeight*1/2`` — the midpoint between
    x-height and cap-height); on X a base position plus a constant/variable bias
    (``outline.centroid-25`` — the optical centre nudged toward a slanted mark's
    foot). A negative numeric term renders with ``-`` (so it round-trips)."""
    terms: tuple

    def __str__(self):
        out = str(self.terms[0])
        for t in self.terms[1:]:
            s = str(t)
            out += s if s.startswith("-") else "+" + s
        return out


# Back-compat alias: sums were once a Y-only construct.
YSum = Sum


@dataclass(frozen=True)
class Neg:
    """A negated term inside a :class:`Sum` (the subtracted operand). Resolves to
    minus the term's value; renders with a leading ``-`` so the sum round-trips
    (``ascender-descender`` → ``Sum((FontMetric('ascender'), Neg(FontMetric('descender'))))``)."""
    term: object

    def __str__(self):
        return f"-{self.term}"


@dataclass(frozen=True)
class VarRef:
    """A reference to a named axis expression (a ``&variable``).

    Like :class:`LabelRef` it is resolved late — at apply time, against the
    merged variable table, so a later file may override a variable an earlier
    one used. But where a label stands for a *list of anchors*, a ``VarRef``
    stands for *one axis's value*: it appears in an X or Y slot, as a term of a
    :class:`YSum`, or as the ``@`` sample height of an :class:`X`. It is
    substituted out (and axis-checked) before the geometry engine runs, so the
    engine never sees one.
    """
    name: str            # includes the leading '&'

    def __str__(self):
        return self.name


XStrategy = Union[Pos, Centroid, Abs, Sum, VarRef]
YStrategy = Union[Pos, Centroid, Y, Abs, FontMetric, Sum, VarRef]


# --------------------------------------------------------------------------- #
#  Anchor specification and rule document
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AnchorSpec:
    """One anchor to place: its name and how to compute X and Y."""
    name: str
    x: XStrategy
    y: YStrategy

    def __str__(self):
        return f"{self.name} ({self.x} {self.y})"


@dataclass(frozen=True)
class LabelRef:
    """A reference to a label, resolved late (at apply time) against the merged
    label table — so a later file may override a label used by an earlier one."""
    name: str            # includes the leading '@'

    def __str__(self):
        return self.name


# An item in a rule/label body: a concrete anchor or a (late-bound) label ref.
Item = Union["AnchorSpec", "LabelRef"]


class Op(Enum):
    """How a rule's anchors combine with what a glyph already accumulated."""
    REPLACE = "="     # discard the accumulator, set it to these anchors
    ADD = "+="        # append these anchors to the accumulator
    REMOVE = "-="     # drop accumulated anchors by name (payload = names/labels)


@dataclass(frozen=True)
class SuffixSpec:
    """Resolved ``!suffixes`` configuration — the variants a rule is replayed on.

    Two modes:

    - explicit (``all=False``): a fixed list of suffixes in ``items``, which
      always contains ``""`` (the unsuffixed base glyph) and never duplicates;
    - ``all`` (``all=True``): every ``<base>.<suffix>`` glyph present in the
      font, minus ``deny`` (e.g. ``.numr``/``.dnom``); ``""`` is always kept.

    Built by :func:`resolve_suffixes` from a document's ordered ``suffix_ops``;
    :meth:`expand` turns it into the concrete suffix list for one base glyph.
    """
    all: bool = False
    items: tuple[str, ...] = ("",)     # explicit suffixes incl. "" (all=False)
    deny: tuple[str, ...] = ()         # excluded suffixes (all=True only)

    def expand(self, base: str, font_names=None) -> list[str]:
        """The suffixes to apply to *base*. Explicit mode returns ``items``
        verbatim (the caller still checks each target exists); ``all`` mode
        discovers ``base.<suffix>`` variants from *font_names* (required),
        dropping any in ``deny``. ``""`` always leads the list."""
        if not self.all:
            return list(self.items)
        prefix = base + "."
        deny = set(self.deny)
        found = sorted(
            nm[len(base):] for nm in (font_names or ())
            if nm.startswith(prefix) and nm[len(base):] not in deny
        )
        return [""] + found


def _dedup_suffixes(items) -> tuple[str, ...]:
    """Drop ``""``/blanks and duplicates, preserving first-seen order."""
    out: list[str] = []
    for s in items:
        if s and s not in out:
            out.append(s)
    return tuple(out)


def resolve_suffixes(ops) -> SuffixSpec:
    """Replay ordered ``suffix_ops`` (each ``(Op, kind, payload)``) from the
    empty base into a :class:`SuffixSpec`. ``=`` resets, ``+=``/``-=`` build on
    what came before — so concatenating a base document's ops with a child's
    (how ``!extends`` merges) composes correctly across layers.

    ``kind`` is ``"all"`` (payload = deny suffixes) or ``"list"`` (payload =
    suffixes to set/add/remove). In ``all`` mode ``-=`` extends ``deny`` and
    ``+=`` re-includes (shrinks ``deny``); in explicit mode they edit ``items``.
    """
    spec = SuffixSpec()
    for op, kind, payload in ops:
        payload = tuple(payload)
        if op is Op.REPLACE:
            if kind == "all":
                spec = SuffixSpec(all=True, items=("",), deny=_dedup_suffixes(payload))
            else:
                spec = SuffixSpec(items=("",) + _dedup_suffixes(payload))
        elif op is Op.ADD:
            if spec.all:
                drop = set(payload)
                spec = SuffixSpec(all=True, items=("",),
                                  deny=tuple(d for d in spec.deny if d not in drop))
            else:
                spec = SuffixSpec(items=("",) + _dedup_suffixes(spec.items[1:] + payload))
        elif op is Op.REMOVE:
            if spec.all:
                spec = SuffixSpec(all=True, items=("",),
                                  deny=_dedup_suffixes(spec.deny + payload))
            else:
                drop = set(payload)
                spec = SuffixSpec(items=tuple(s for s in spec.items if s == "" or s not in drop))
    return spec


@dataclass(frozen=True)
class GlyphName:
    """Selector: target a glyph by its name."""
    name: str

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class Unicode:
    """Selector: target a glyph by its Unicode code point."""
    codepoint: int

    def __str__(self):
        return f"U+{self.codepoint:04X}"


@dataclass(frozen=True)
class UnicodeRange:
    """Selector: target glyphs in an inclusive code-point range."""
    start: int
    end: int

    def __str__(self):
        return f"U+{self.start:04X}..U+{self.end:04X}"


@dataclass(frozen=True)
class Glob:
    """Selector: target glyphs whose name matches a shell glob (`*`, `?`)."""
    pattern: str

    def __str__(self):
        return self.pattern


@dataclass(frozen=True)
class Category:
    """Selector: target glyphs by Unicode general category (e.g. ``Lu``).

    A one-letter value (``L``) matches any subcategory (``Lu``, ``Ll``, ...).
    """
    value: str

    def __str__(self):
        return f"{{{self.value}}}"


Selector = Union[GlyphName, Unicode, UnicodeRange, Glob, Category]


@dataclass
class Document:
    """A parsed rule file: reusable labels + ordered selector applications.

    Bodies hold :data:`Item`\\ s (anchors and unresolved :class:`LabelRef`\\ s);
    for ``REMOVE`` rules the body is the set of names/labels to drop. Labels are
    resolved late, at apply time, against the (possibly merged) label table.
    """
    labels: dict[str, list] = field(default_factory=dict)
    # named axis expressions (`&name = X-or-Y expr`); values are XStrategy /
    # YStrategy nodes that may themselves contain VarRefs. Resolved late, at
    # apply time, against the (possibly merged) table — last definition wins.
    variables: dict[str, object] = field(default_factory=dict)
    rules: list[tuple[Selector, Op, list]] = field(default_factory=list)
    shift_x: int = 0                          # document-wide X offset (!shiftx)
    # ordered !suffixes directives, each (Op, kind, payload); resolve_suffixes()
    # replays them into a SuffixSpec. Empty = just the unsuffixed base glyph.
    suffix_ops: list = field(default_factory=list)
    extends: list[str] = field(default_factory=list)  # base rules to inherit (!extends)
    # 1-based source line for each rule, parallel to `rules` — set by the DSL
    # parser for editor / provenance tooling (which rule placed an anchor). Empty
    # from the legacy parser and after !extends merges; consumers must treat it as
    # optional (degrade to "no line" when a rule's index is out of range).
    sources: list[int] = field(default_factory=list)
