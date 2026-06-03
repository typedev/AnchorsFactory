"""Geometry engine: resolve an :class:`AnchorSpec` to concrete (x, y) units.

This replaces the old point-in-polygon scan with analytic contour
intersection (``fontTools.misc.bezierTools``). It is the layer the rest of
the package and the golden regression tests exercise, and it is fully
decoupled from any DSL surface syntax — it consumes only the IR.
"""

from __future__ import annotations

import math
from typing import Optional

from fontTools.misc.bezierTools import segmentSegmentIntersections
from fontTools.pens.recordingPen import DecomposingRecordingPen

from .model import (
    Frame, HAlign, VEdge, Run, Frac,
    X, XAbs, Y, YAbs, AnchorSpec,
)

# Crossings closer than this (font units) are treated as one — collapses the
# duplicate roots you get when a scanline passes through a shared on-curve point.
_MERGE_EPS = 1.0


def _segments(glyph):
    """Yield outline segments (components decomposed) as point tuples.

    Each yielded tuple is a segment in the form accepted by
    ``segmentSegmentIntersections``: 2 points = line, 3 = quadratic,
    4 = cubic.
    """
    pen = DecomposingRecordingPen(glyph.font)
    glyph.draw(pen)
    cur = start = None
    for op, pts in pen.value:
        if op == "moveTo":
            cur = start = pts[0]
        elif op == "lineTo":
            yield (cur, pts[0])
            cur = pts[0]
        elif op == "curveTo":
            yield (cur, *pts)
            cur = pts[-1]
        elif op == "qCurveTo":
            # Expand TrueType quadratics, inserting implied on-curve midpoints
            # between consecutive off-curve points.
            offs = list(pts[:-1])
            last = pts[-1]
            if last is None:  # all-off-curve closed quad — rare; skip safely
                cur = start
                continue
            prev = cur
            for i, off in enumerate(offs):
                if i + 1 < len(offs):
                    nxt = offs[i + 1]
                    end = ((off[0] + nxt[0]) / 2, (off[1] + nxt[1]) / 2)
                else:
                    end = last
                yield (prev, off, end)
                prev = end
            cur = last
        elif op == "closePath":
            if cur is not None and start is not None and cur != start:
                yield (cur, start)
            cur = start
        elif op == "endPath":
            cur = start


def _crossings(glyph, y: float) -> list[float]:
    """Sorted x-coordinates where the outline crosses the horizontal line at *y*."""
    bounds = glyph.bounds
    if bounds is None:
        return []
    xMin, _, xMax, _ = bounds
    scanline = ((xMin - 1000, y), (xMax + 1000, y))
    xs: list[float] = []
    for seg in _segments(glyph):
        for ix in segmentSegmentIntersections(seg, scanline):
            xs.append(ix.pt[0])
    xs.sort()
    return xs


def _spans(xs: list[float], eps: float = _MERGE_EPS) -> list[tuple[float, float]]:
    """Merge near-coincident crossings and pair them into ink spans (stems)."""
    merged: list[float] = []
    for x in xs:
        if not merged or abs(x - merged[-1]) > eps:
            merged.append(x)
    return [(merged[i], merged[i + 1]) for i in range(0, len(merged) - 1, 2)]


def _italic_shift(font, y: float) -> float:
    angle = font.info.italicAngle
    if not angle:
        return 0.0
    return y * math.tan(math.radians(-angle))


def resolve_y(font, yspec) -> float:
    """Resolve a Y strategy to a height in font units."""
    if isinstance(yspec, YAbs):
        return float(yspec.y)
    glyph = font[yspec.glyph]              # KeyError if the reference is missing
    bounds = glyph.bounds
    if bounds is None:
        return 0.0
    _, yMin, _, yMax = bounds
    ref = yspec.ref
    if isinstance(ref, Frac):
        # Fraction of the glyph's top extent, measured from the baseline.
        return yMax * ref.num / ref.den
    if ref is VEdge.TOP:
        return float(yMax)
    if ref is VEdge.BOTTOM:
        return float(yMin)
    return (yMin + yMax) / 2               # VEdge.MIDDLE


def resolve_x(font, glyph, xspec, y: float) -> float:
    """Resolve an X strategy to a position in font units, at height *y*."""
    if isinstance(xspec, XAbs):
        return float(xspec.x)

    shift = _italic_shift(font, y) if y != 0 else 0.0
    bounds = glyph.bounds or (0.0, 0.0, 0.0, 0.0)
    xMin, yMin, xMax, yMax = bounds

    if xspec.frame is Frame.ADVANCE:
        base = {HAlign.LEFT: 0.0, HAlign.CENTER: glyph.width / 2, HAlign.RIGHT: float(glyph.width)}[xspec.align]
        return base + shift

    if xspec.frame is Frame.BOX:
        base = {HAlign.LEFT: xMin, HAlign.CENTER: (xMin + xMax) / 2, HAlign.RIGHT: xMax}[xspec.align]
        return base + shift

    # OUTLINE — sample where the ink actually is.
    sample = y
    if xspec.at is VEdge.TOP:
        sample = yMax - 1
    elif xspec.at is VEdge.BOTTOM:
        sample = yMin + 1

    xs = _crossings(glyph, sample)
    if not xs:
        # No ink at this height: fall back to the bounding box edge.
        return {HAlign.LEFT: xMin, HAlign.RIGHT: xMax}.get(xspec.align, (xMin + xMax) / 2)

    run = xspec.run
    if run is None:
        lo, hi = xs[0], xs[-1]            # whole ink envelope
    else:
        spans = _spans(xs)
        idx = 0 if run is Run.FIRST else (-1 if run is Run.LAST else run - 1)
        try:
            lo, hi = spans[idx]
        except IndexError:
            lo, hi = xs[0], xs[-1]        # requested stem absent → envelope

    if xspec.align is HAlign.LEFT:
        return lo
    if xspec.align is HAlign.RIGHT:
        return hi
    return (lo + hi) / 2                  # CENTER


def resolve(font, glyph, spec: AnchorSpec) -> tuple[float, float]:
    """Resolve a full anchor spec on *glyph* to an (x, y) position."""
    y = resolve_y(font, spec.y)
    x = resolve_x(font, glyph, spec.x, y)
    return (x, y)
