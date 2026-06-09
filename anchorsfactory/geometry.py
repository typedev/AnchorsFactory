"""Geometry engine: resolve an :class:`AnchorSpec` to concrete (x, y) units.

This replaces the old point-in-polygon scan with analytic contour
intersection (``fontTools.misc.bezierTools``). It is the layer the rest of
the package and the golden regression tests exercise, and it is fully
decoupled from any DSL surface syntax — it consumes only the IR.
"""

from __future__ import annotations

import math
from typing import Optional

from fontTools.misc.bezierTools import curveLineIntersections
from fontTools.pens.recordingPen import DecomposingRecordingPen

import logging

from .model import (
    Frame, HAlign, VEdge, Run, Frac,
    X, XAbs, Y, YAbs, FontMetric, YSum, AnchorSpec,
)

log = logging.getLogger(__name__)

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


def _seg_crossings(seg, y: float) -> list[float]:
    """X-coords where one segment crosses the horizontal line at *y*.

    Computed explicitly and clamped to the segment: lines analytically (with a
    y-range check), curves via ``curveLineIntersections`` (which clamps to the
    curve's t in [0, 1]). This avoids the unbounded infinite-line intersection
    that ``segmentSegmentIntersections`` returns for the line case.
    """
    if len(seg) == 2:
        (x0, y0), (x1, y1) = seg
        if y0 == y1:                       # horizontal: collinear, no crossing
            return []
        if not (min(y0, y1) <= y <= max(y0, y1)):
            return []
        t = (y - y0) / (y1 - y0)
        return [x0 + t * (x1 - x0)]
    if len(seg) == 3:                      # quadratic -> elevate to cubic
        p0, c, p1 = seg
        seg = (
            p0,
            (p0[0] + 2 / 3 * (c[0] - p0[0]), p0[1] + 2 / 3 * (c[1] - p0[1])),
            (p1[0] + 2 / 3 * (c[0] - p1[0]), p1[1] + 2 / 3 * (c[1] - p1[1])),
            p1,
        )
    return [ix.pt[0] for ix in curveLineIntersections(seg, ((0, y), (1, y)))]


def _crossings(glyph, y: float) -> list[float]:
    """Sorted x-coordinates where the outline crosses the horizontal line at *y*."""
    if glyph.bounds is None:
        return []
    xs: list[float] = []
    for seg in _segments(glyph):
        xs.extend(_seg_crossings(seg, y))
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


def _degrade(warnings, msg: str) -> None:
    """Record a *soft* geometry degradation: a value was produced via a fallback
    rather than a clean computation. Always logged; also appended to the optional
    *warnings* sink (a list) so ``compute_document(on_error='collect')`` can
    surface it as a ``severity='warning'`` diagnostic. ``warnings=None`` (the
    batch default) just logs, exactly as before.
    """
    log.warning(msg)
    if warnings is not None:
        warnings.append(msg)


def _font_metric(font, name: str, *, warnings=None) -> float:
    if name == "baseline":
        return 0.0
    value = getattr(font.info, name, None)
    if value is None:
        _degrade(warnings, f"font has no {name} metric; using 0")
        return 0.0
    return float(value)


def resolve_y(font, yspec, *, warnings=None) -> float:
    """Resolve a Y strategy to a height in font units."""
    if isinstance(yspec, YAbs):
        return float(yspec.y)
    if isinstance(yspec, FontMetric):
        value = _font_metric(font, yspec.name, warnings=warnings)
        return value * yspec.frac.num / yspec.frac.den if yspec.frac else value
    if isinstance(yspec, YSum):
        return sum(resolve_y(font, t, warnings=warnings) for t in yspec.terms)
    if yspec.glyph not in font:
        _degrade(warnings, f"reference glyph {yspec.glyph!r} not found; using 0")
        return 0.0
    glyph = font[yspec.glyph]
    bounds = glyph.bounds
    if bounds is None:
        _degrade(warnings, f"reference glyph {yspec.glyph!r} has no bounds; using 0")
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


def resolve_x(font, glyph, xspec, y: float, *, warnings=None) -> float:
    """Resolve an X strategy to a position in font units, at height *y*."""
    if isinstance(xspec, XAbs):
        return float(xspec.x)

    shift = _italic_shift(font, y) if y != 0 else 0.0
    bounds = glyph.bounds
    if bounds is None:
        if xspec.frame is not Frame.ADVANCE:   # BOX/OUTLINE need a box; ADVANCE uses width
            _degrade(warnings, f"glyph {glyph.name!r} has no bounds; using empty box")
        bounds = (0.0, 0.0, 0.0, 0.0)
    xMin, yMin, xMax, yMax = bounds

    if xspec.frame is Frame.ADVANCE:
        base = {HAlign.LEFT: 0.0, HAlign.CENTER: glyph.width / 2, HAlign.RIGHT: float(glyph.width)}[xspec.align]
        return base + shift

    if xspec.frame is Frame.BOX:
        base = {HAlign.LEFT: xMin, HAlign.CENTER: (xMin + xMax) / 2, HAlign.RIGHT: xMax}[xspec.align]
        return base + shift

    # OUTLINE — sample where the ink actually is, at exactly the requested
    # height. The anchor asked for a height; resolve it there verbatim, with no
    # inset/nudge: `outline.right@0` is the rightmost crossing at y=0, and a
    # height that coincides with the glyph's own extreme (e.g. an open hook
    # whose top is y=0) is honoured — its clean crossings are not discarded.
    if xspec.at is None:
        sample = y
    elif xspec.at is VEdge.TOP:
        sample = yMax
    elif xspec.at is VEdge.BOTTOM:
        sample = yMin
    else:                                  # a fixed height (metric / number / glyph)
        sample = resolve_y(font, xspec.at, warnings=warnings)

    xs = _crossings(glyph, sample)
    if not xs:
        # No ink crosses at this height — fall back to the bounding-box edge,
        # and say why: a height outside the ink box (e.g. @ascender on an
        # x-height glyph) versus one inside it that still finds no crossing
        # (a degenerate/collinear edge). The anchor is still placed, but flagged.
        if sample < yMin or sample > yMax:
            _degrade(warnings, f"glyph {glyph.name!r}: requested sample height y={sample:g} is "
                               f"outside the ink box [{yMin:g}, {yMax:g}]; using bounding-box edge")
        else:
            _degrade(warnings, f"glyph {glyph.name!r}: no outline crossing at y={sample:g}; "
                               f"using bounding-box edge")
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
            _degrade(warnings, f"glyph {glyph.name!r}: stem {xspec.run} absent at y={sample:g}; "
                               f"using ink envelope")
            lo, hi = xs[0], xs[-1]        # requested stem absent → envelope

    if xspec.align is HAlign.LEFT:
        return lo
    if xspec.align is HAlign.RIGHT:
        return hi
    return (lo + hi) / 2                  # CENTER


def resolve(font, glyph, spec: AnchorSpec, *, warnings=None) -> tuple[float, float]:
    """Resolve a full anchor spec on *glyph* to an (x, y) position.

    Pass a list as *warnings* to collect soft degradations (a value produced via
    a fallback — no outline crossing, missing metric/reference glyph) as reason
    strings; the coordinate is still returned. ``warnings=None`` (default) just
    logs them, as before. Hard failures (malformed contours) still raise.
    """
    y = resolve_y(font, spec.y, warnings=warnings)
    x = resolve_x(font, glyph, spec.x, y, warnings=warnings)
    return (x, y)
