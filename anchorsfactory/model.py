"""Internal representation (IR) for anchor placement rules.

This module is the contract between the rule parser(s) and the geometry
engine. Any DSL front-end — the current ``.txt`` format or a future syntax —
parses *into* these structures; the engine consumes them. The IR is
vocabulary-agnostic: it encodes *frame + position*, not surface keywords.

Naming follows the ``frame.position`` scheme agreed during design:

    frame    : ADVANCE | BOX | OUTLINE   — what we measure against
    h-align  : LEFT | CENTER | RIGHT     — position within the frame
    run      : which ink span (stem) when the frame is OUTLINE
    at-edge  : sample OUTLINE at the glyph's own TOP/BOTTOM extreme

Horizontal (X) tokens -> IR::

    width.center          -> X(ADVANCE, CENTER)
    width.left            -> X(ADVANCE, LEFT)            # origin (x = 0)
    width.right           -> X(ADVANCE, RIGHT)           # advance width
    box.left              -> X(BOX, LEFT)                # bbox xMin
    box.center            -> X(BOX, CENTER)
    box.right             -> X(BOX, RIGHT)               # bbox xMax
    outline.left          -> X(OUTLINE, LEFT)            # leftmost crossing
    outline.right         -> X(OUTLINE, RIGHT)           # rightmost crossing
    outline.first.center  -> X(OUTLINE, CENTER, run=Run.FIRST)   # left stem
    outline.last.center   -> X(OUTLINE, CENTER, run=Run.LAST)    # right stem
    outline.2.center      -> X(OUTLINE, CENTER, run=2)           # 2nd stem (1-based)
    outline.center@top    -> X(OUTLINE, CENTER, at=VEdge.TOP)    # old `topcenter`
    400                   -> XAbs(400)

Vertical (height / Y) tokens -> IR::

    $H        -> Y("H", VEdge.TOP)        # default edge is TOP
    $H.bottom -> Y("H", VEdge.BOTTOM)
    $H.middle -> Y("H", VEdge.MIDDLE)
    $H*5/6    -> Y("H", Frac(5, 6))       # fraction of the glyph's top, from baseline
    575       -> YAbs(575)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class Frame(Enum):
    """Reference system the X coordinate is measured against."""
    ADVANCE = "width"    # the advance width: 0 .. glyph.width
    BOX = "box"          # the bounding box: xMin .. xMax
    OUTLINE = "outline"  # the actual contour, sampled at a height


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
#  Horizontal (X) strategies
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class X:
    """A computed horizontal position: ``frame.[run.]align[@at]``."""
    frame: Frame
    align: HAlign
    run: Optional[Union[Run, int]] = None   # OUTLINE only; None = whole envelope
    # OUTLINE only — where to sample the contour for X: None = at the anchor's
    # own Y; VEdge.TOP/BOTTOM = the glyph's own extreme; or a height strategy
    # (FontMetric/YAbs/Y/YSum) to sample at a fixed height, decoupled from Y.
    at: object = None

    def __post_init__(self):
        if self.frame is not Frame.OUTLINE:
            if self.run is not None:
                raise ValueError(f"`run` only applies to OUTLINE, not {self.frame.value}")
            if self.at is not None:
                raise ValueError(f"`@…` only applies to OUTLINE, not {self.frame.value}")
        if isinstance(self.run, int) and not isinstance(self.run, bool) and self.run < 1:
            raise ValueError("integer `run` is 1-based and must be >= 1")
        if self.at is VEdge.MIDDLE:
            raise ValueError("`@middle` is meaningless; sample edge must be top or bottom")

    def __str__(self):
        parts = [self.frame.value]
        if self.run is not None:
            parts.append(self.run.value if isinstance(self.run, Run) else str(self.run))
        parts.append(self.align.value)
        s = ".".join(parts)
        if self.at is not None:
            s += "@" + (self.at.value if isinstance(self.at, VEdge) else str(self.at))
        return s


@dataclass(frozen=True)
class XAbs:
    """An absolute horizontal position in font units."""
    x: float

    def __str__(self):
        return str(self.x)


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


@dataclass(frozen=True)
class YAbs:
    """An absolute height in font units."""
    y: float

    def __str__(self):
        return str(self.y)


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
class YSum:
    """A height that is the sum of several Y terms (e.g. ``capHeight*1/2 +
    xHeight*1/2`` for the midpoint between x-height and cap-height)."""
    terms: tuple

    def __str__(self):
        return "+".join(str(t) for t in self.terms)


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


XStrategy = Union[X, XAbs, VarRef]
YStrategy = Union[Y, YAbs, FontMetric, YSum, VarRef]


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
