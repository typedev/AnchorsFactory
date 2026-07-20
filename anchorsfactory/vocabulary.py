"""The surface vocabulary of the rule language — the words a user actually types.

This is the single source of truth for editor tooling (syntax highlighting,
completion, diagnostics) *and* for the parser: :mod:`anchorsfactory.dsl` builds
its lookup tables from here, so the two cannot drift. Nothing is spelled twice —
the frame/align/run words come straight off the IR enums in
:mod:`anchorsfactory.model`.

It is deliberately **not** the IR. ``Frame.ADVANCE`` is an IR node name; the word
the user types is ``width``. A consumer that reads the enums directly gets the
former and will offer a token the parser rejects — which is exactly how the
Studio's own completion list came to offer ``advance``.

Typical use, from an editor completing after a dot::

    completions_after_dot("box", axis="y")   # -> ("bottom", "middle", "top")
"""

from __future__ import annotations

import re

from .model import Axis, FONT_METRICS, Frame, HAlign, Run, VEdge

# --------------------------------------------------------------------------- #
#  Position words — derived from the IR enums, never re-spelled
# --------------------------------------------------------------------------- #

#: Frame words opening a position token: ``width`` / ``box`` / ``outline``.
FRAMES = tuple(f.value for f in Frame)

#: Horizontal alignments — valid in the **X** slot only.
X_ALIGNS = tuple(a.value for a in HAlign)

#: Vertical edges — valid in the **Y** slot only. Listed bottom-up, the order
#: they read in a menu (the enum itself is declared top-down).
Y_EDGES = tuple(e.value for e in reversed(list(VEdge)))

#: Named ink spans for ``outline`` positions (an integer also works).
RUNS = tuple(r.value for r in Run)

#: Font-wide vertical metrics, usable in a Y slot.
METRICS = FONT_METRICS

#: The one axis-free position word.
CENTROID = "centroid"

#: Frames that accept a ``*n/m`` fractional position (``outline`` does not).
FRACTIONAL_FRAMES = tuple(f.value for f in (Frame.ADVANCE, Frame.BOX))

#: The advance frame has no vertical analogue (see ``Pos.__post_init__``), so it
#: is offered on X only.
_X_ONLY_FRAMES = (Frame.ADVANCE.value,)

# --------------------------------------------------------------------------- #
#  Directives, operators, sigils
# --------------------------------------------------------------------------- #

#: Document directives, with their leading ``!``.
DIRECTIVES = ("!extends", "!suffixes", "!shiftx", "!propagate")

#: Values ``!propagate`` accepts.
PROPAGATE_VALUES = ("none", "composites", "all")

#: Words ``!suffixes`` accepts besides a suffix list.
SUFFIX_KEYWORDS = ("all", "except", "none")

#: Rule operators: replace / add / remove.
OPERATORS = ("=", "+=", "-=")

#: Leading characters that give a token its kind.
SIGILS = {
    "label": "@",    # @label — a named anchor group
    "var": "&",      # &name  — a named axis expression
    "anchor": "%",   # %name  — another anchor on the same glyph
    "glyph": "$",    # $Glyph — a reference glyph's height
}

#: Regex source for the per-component frame qualifier, without its trailing dot
#: (``comp2`` / ``complast``) — the form an editor sees while the user is typing.
COMPONENT_HEAD_PATTERN = r"comp(\d+|last)"

#: Regex source for the full qualifier as it appears in a token (``comp2.``).
COMPONENT_PATTERN = COMPONENT_HEAD_PATTERN + r"\."

_COMPONENT_HEAD_RE = re.compile(COMPONENT_HEAD_PATTERN)

#: Own-edge sentinels usable in an ``@`` sample line: on X it is a height, on Y
#: a column. Both also take a signed offset (``@top-10``).
AT_X_EDGES = tuple(e.value for e in (VEdge.TOP, VEdge.BOTTOM))
AT_Y_SIDES = tuple(a.value for a in (HAlign.LEFT, HAlign.RIGHT))


# --------------------------------------------------------------------------- #
#  Completion
# --------------------------------------------------------------------------- #

def _axis_value(axis) -> str | None:
    """Normalise an axis argument (``"x"``/``"y"``/:class:`~.model.Axis`/None)."""
    if axis is None:
        return None
    if isinstance(axis, Axis):
        return axis.value
    a = str(axis).lower()
    if a not in (Axis.X.value, Axis.Y.value):
        raise ValueError(f"axis must be 'x', 'y' or None, got {axis!r}")
    return a


def aligns_for(axis=None) -> tuple[str, ...]:
    """The alignment words valid in *axis*'s slot.

    ``HAlign`` applies on X and ``VEdge`` on Y — the parser picks its table by
    axis (:func:`anchorsfactory.dsl._parse_align`), so a client that knows which
    slot the cursor sits in can offer three words instead of six. With *axis*
    ``None`` (slot unknown) both sets come back.
    """
    a = _axis_value(axis)
    if a == Axis.X.value:
        return X_ALIGNS
    if a == Axis.Y.value:
        return Y_EDGES
    return X_ALIGNS + Y_EDGES


def completions_after_dot(head: str, axis=None) -> tuple[str, ...]:
    """What may follow ``head.`` in an anchor expression, for *axis*'s slot.

    *head* is the token before the dot — a frame (``box``), a component
    qualifier (``comp2``), or a ``$Glyph`` reference. Returns an empty tuple for
    anything else, including a frame that has no form on the requested axis
    (``width`` on Y).
    """
    if head.startswith(SIGILS["glyph"]):          # $Glyph.top / .middle / .bottom
        return Y_EDGES
    if head.startswith("comp"):                   # comp2. / complast. -> a frame
        return FRAMES if _COMPONENT_HEAD_RE.fullmatch(head) else ()
    if head not in FRAMES:
        return ()
    a = _axis_value(axis)
    if head in _X_ONLY_FRAMES and a == Axis.Y.value:
        return ()
    aligns = aligns_for(axis)
    if head in _X_ONLY_FRAMES and a is None:
        aligns = X_ALIGNS                          # width has no vertical analogue
    if head == Frame.OUTLINE.value:
        return RUNS + aligns + (CENTROID,)
    return aligns


def completions_for_slot(axis=None) -> tuple[str, ...]:
    """The words that may **open** a position token in *axis*'s slot.

    Frames and alignments on both axes; font metrics only on Y, where a height
    term is legal (``_parse_slot`` sends X tokens to the frame grammar alone).
    ``$Glyph`` references are Y-only for the same reason, but they carry a sigil
    rather than a word, so a client filters those by :data:`SIGILS`.
    """
    a = _axis_value(axis)
    words = FRAMES + aligns_for(axis) + (CENTROID,)
    if a != Axis.X.value:
        words += tuple(METRICS)
    return words


def completion_table() -> dict:
    """Every frame's completions, pre-computed per axis: ``{frame: {axis: words}}``
    with axis keys ``"x"``, ``"y"`` and ``""`` (slot unknown).

    Lets a non-Python client (the Studio's browser UI) be purely data-driven —
    without it, each one would have to re-implement "``width`` is X-only" and
    "``outline`` also offers runs and the centroid", which is exactly the kind of
    re-implementation this module exists to prevent.
    """
    return {
        head: {(axis or ""): list(completions_after_dot(head, axis))
               for axis in (None, Axis.X.value, Axis.Y.value)}
        for head in FRAMES
    }


def as_dict() -> dict:
    """The whole vocabulary as one JSON-serialisable dict.

    For clients that would rather ship the tables across a wire (the Studio hands
    this to its browser UI) than import a dozen names. Deliberately *not*
    re-exported from the package root: a module-level name ``vocabulary`` there
    would shadow this module itself.
    """
    return {
        "frames": list(FRAMES),
        "xAligns": list(X_ALIGNS),
        "yEdges": list(Y_EDGES),
        "runs": list(RUNS),
        "metrics": list(METRICS),
        "centroid": CENTROID,
        "fractionalFrames": list(FRACTIONAL_FRAMES),
        "xOnlyFrames": list(_X_ONLY_FRAMES),
        "directives": list(DIRECTIVES),
        "propagateValues": list(PROPAGATE_VALUES),
        "suffixKeywords": list(SUFFIX_KEYWORDS),
        "operators": list(OPERATORS),
        "sigils": dict(SIGILS),
        "componentPattern": COMPONENT_PATTERN,
        "componentHeadPattern": COMPONENT_HEAD_PATTERN,
        "completionsAfterDot": completion_table(),
        "completionsForSlot": {(axis or ""): list(completions_for_slot(axis))
                               for axis in (None, Axis.X.value, Axis.Y.value)},
        "atXEdges": list(AT_X_EDGES),
        "atYSides": list(AT_Y_SIDES),
    }
