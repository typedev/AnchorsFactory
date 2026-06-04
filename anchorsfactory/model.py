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
    at: Optional[VEdge] = None              # OUTLINE only; sample at glyph extreme

    def __post_init__(self):
        if self.frame is not Frame.OUTLINE:
            if self.run is not None:
                raise ValueError(f"`run` only applies to OUTLINE, not {self.frame.value}")
            if self.at is not None:
                raise ValueError(f"`@{self.at.value}` only applies to OUTLINE, not {self.frame.value}")
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
            s += f"@{self.at.value}"
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


XStrategy = Union[X, XAbs]
YStrategy = Union[Y, YAbs, FontMetric]


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
class GlyphName:
    """Selector: target a glyph by its name."""
    name: str


@dataclass(frozen=True)
class Unicode:
    """Selector: target a glyph by its Unicode code point."""
    codepoint: int


@dataclass(frozen=True)
class UnicodeRange:
    """Selector: target glyphs in an inclusive code-point range."""
    start: int
    end: int


@dataclass(frozen=True)
class Glob:
    """Selector: target glyphs whose name matches a shell glob (`*`, `?`)."""
    pattern: str


@dataclass(frozen=True)
class Category:
    """Selector: target glyphs by Unicode general category (e.g. ``Lu``).

    A one-letter value (``L``) matches any subcategory (``Lu``, ``Ll``, ...).
    """
    value: str


Selector = Union[GlyphName, Unicode, UnicodeRange, Glob, Category]


@dataclass
class Document:
    """A parsed rule file: reusable labels + ordered selector applications.

    Bodies hold :data:`Item`\\ s (anchors and unresolved :class:`LabelRef`\\ s);
    for ``REMOVE`` rules the body is the set of names/labels to drop. Labels are
    resolved late, at apply time, against the (possibly merged) label table.
    """
    labels: dict[str, list] = field(default_factory=dict)
    rules: list[tuple[Selector, Op, list]] = field(default_factory=list)
    shift_x: int = 0                          # document-wide X offset (!shiftx)
    suffixes: list[str] = field(default_factory=lambda: [""])  # variants (!suffixes)
    extends: list[str] = field(default_factory=list)  # base rules to inherit (!extends)
