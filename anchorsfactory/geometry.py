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
from fontTools.pens.statisticsPen import StatisticsPen

import logging

from .model import (
    Frame, Axis, HAlign, VEdge, Run, Frac,
    Pos, Centroid, Abs, Y, FontMetric, Sum, Neg, AnchorSpec,
)

log = logging.getLogger(__name__)


class AxisCycleError(ValueError):
    """Both axes of an anchor are OUTLINE-sampled with ``at=None`` — each would
    need the other's coordinate as its scanline, so neither can be resolved.
    Break the cycle by giving one axis an explicit ``@`` sample line."""

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


def _seg_crossings(seg, value: float, axis: Axis = Axis.X) -> list[float]:
    """Coordinates (along *axis*) where one segment crosses the perpendicular
    scanline at *value*.

    ``axis=X``: a horizontal scanline at ``y=value`` → returns crossing *x*'s.
    ``axis=Y``: a vertical scanline at ``x=value`` → returns crossing *y*'s.

    Computed explicitly and clamped to the segment: lines analytically (with a
    range check on the fixed coordinate), curves via ``curveLineIntersections``
    (which clamps to the curve's t in [0, 1]). This avoids the unbounded
    infinite-line intersection that ``segmentSegmentIntersections`` returns for
    the line case.
    """
    fix = 1 if axis is Axis.X else 0       # the coordinate the scanline pins
    out = 1 - fix                          # the coordinate we read off
    if len(seg) == 2:
        p0, p1 = seg
        a0, a1 = p0[fix], p1[fix]
        if a0 == a1:                       # parallel to the scanline: no crossing
            return []
        if not (min(a0, a1) <= value <= max(a0, a1)):
            return []
        t = (value - a0) / (a1 - a0)
        return [p0[out] + t * (p1[out] - p0[out])]
    if len(seg) == 3:                      # quadratic -> elevate to cubic
        p0, c, p1 = seg
        seg = (
            p0,
            (p0[0] + 2 / 3 * (c[0] - p0[0]), p0[1] + 2 / 3 * (c[1] - p0[1])),
            (p1[0] + 2 / 3 * (c[0] - p1[0]), p1[1] + 2 / 3 * (c[1] - p1[1])),
            p1,
        )
    line = ((0, value), (1, value)) if axis is Axis.X else ((value, 0), (value, 1))
    return [ix.pt[out] for ix in curveLineIntersections(seg, line)]


def _crossings(glyph, value: float, axis: Axis = Axis.X) -> list[float]:
    """Sorted coordinates (along *axis*) where the outline crosses the scanline
    perpendicular to *axis* at *value* (horizontal scanline on X, vertical on Y)."""
    if glyph.bounds is None:
        return []
    cs: list[float] = []
    for seg in _segments(glyph):
        cs.extend(_seg_crossings(seg, value, axis))
    cs.sort()
    return cs


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
    if isinstance(yspec, Abs):
        return float(yspec.value)
    if isinstance(yspec, FontMetric):
        value = _font_metric(font, yspec.name, warnings=warnings)
        return value * yspec.frac.num / yspec.frac.den if yspec.frac else value
    if isinstance(yspec, Neg):
        return -resolve_y(font, yspec.term, warnings=warnings)
    if isinstance(yspec, Sum):
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


def _t(align) -> float:
    """The position of an *align* within its frame as a fraction from the near
    edge (left/bottom = 0, center/middle = 1/2, right/top = 1, or a Frac)."""
    if isinstance(align, Frac):
        return align.num / align.den
    return {
        HAlign.LEFT: 0.0, HAlign.CENTER: 0.5, HAlign.RIGHT: 1.0,
        VEdge.BOTTOM: 0.0, VEdge.MIDDLE: 0.5, VEdge.TOP: 1.0,
    }[align]


def _along(lo: float, hi: float, align) -> float:
    """Interpolate between the frame's near (*lo*) and far (*hi*) edges. For an
    OUTLINE span this yields lo / midpoint / hi for near / center / far; for
    BOX/ADVANCE it additionally honours a fractional position."""
    return lo + _t(align) * (hi - lo)


def _centroid(glyph, *, warnings=None) -> tuple[float, float]:
    """Area centre of mass of the (component-decomposed) outline."""
    if glyph.bounds is None:
        _degrade(warnings, f"glyph {glyph.name!r} has no outline; centroid using origin")
        return (0.0, 0.0)
    rec = DecomposingRecordingPen(glyph.font)
    glyph.draw(rec)
    stats = StatisticsPen(glyph.font)
    rec.replay(stats)
    if not stats.area:                     # empty / open / zero-area contour
        xMin, yMin, xMax, yMax = glyph.bounds
        _degrade(warnings, f"glyph {glyph.name!r}: zero-area outline; centroid using bbox centre")
        return ((xMin + xMax) / 2, (yMin + yMax) / 2)
    return (stats.meanX, stats.meanY)


def _sample_line(font, glyph, p: Pos, axis: Axis, cross, bounds, *, warnings=None) -> float:
    """The scanline position for an OUTLINE *p*: from its ``@`` (an edge or a
    position on the other axis) or, when ``at is None``, the anchor's other
    coordinate *cross*."""
    xMin, yMin, xMax, yMax = bounds
    at = p.at
    if at is None:
        return float(cross) if cross is not None else 0.0
    if axis is Axis.X:                     # a height
        if at is VEdge.TOP:
            return yMax
        if at is VEdge.BOTTOM:
            return yMin
        return resolve_y(font, at, warnings=warnings)
    if at is HAlign.LEFT:                  # axis Y → a column
        return xMin
    if at is HAlign.RIGHT:
        return xMax
    return _axis(font, glyph, at, Axis.X, warnings=warnings)


def _pos(font, glyph, p: Pos, axis: Axis, *, cross=None, warnings=None) -> float:
    """Resolve a frame-relative :class:`Pos` along *axis* (no italic shift)."""
    bounds = glyph.bounds
    if bounds is None:
        if p.frame is not Frame.ADVANCE:   # BOX/OUTLINE need a box; ADVANCE uses width
            _degrade(warnings, f"glyph {glyph.name!r} has no bounds; using empty box")
        bounds = (0.0, 0.0, 0.0, 0.0)
    xMin, yMin, xMax, yMax = bounds

    if p.frame is Frame.ADVANCE:           # X-only (guarded in the IR)
        return _along(0.0, float(glyph.width), p.align)
    if p.frame is Frame.BOX:
        lo, hi = (xMin, xMax) if axis is Axis.X else (yMin, yMax)
        return _along(lo, hi, p.align)

    # OUTLINE — sample where the ink actually is, on the scanline perpendicular
    # to this axis, at exactly the requested position (no inset/nudge).
    sample = _sample_line(font, glyph, p, axis, cross, bounds, warnings=warnings)
    cs = _crossings(glyph, sample, axis)
    if not cs:
        # No ink crosses there — fall back to the bounding-box edge, and say why:
        # a sample outside the ink box versus one inside it that still finds no
        # crossing (a degenerate/collinear edge). Still placed, but flagged.
        lo, hi = (xMin, xMax) if axis is Axis.X else (yMin, yMax)
        amin, amax = (yMin, yMax) if axis is Axis.X else (xMin, xMax)
        what = "height" if axis is Axis.X else "column"
        if sample < amin or sample > amax:
            _degrade(warnings, f"glyph {glyph.name!r}: requested sample {what}={sample:g} is "
                               f"outside the ink box [{amin:g}, {amax:g}]; using bounding-box edge")
        else:
            _degrade(warnings, f"glyph {glyph.name!r}: no outline crossing at {what}={sample:g}; "
                               f"using bounding-box edge")
        return _along(lo, hi, p.align)

    run = p.run
    if run is None:
        lo, hi = cs[0], cs[-1]             # whole ink envelope
    else:
        spans = _spans(cs)
        idx = 0 if run is Run.FIRST else (-1 if run is Run.LAST else run - 1)
        try:
            lo, hi = spans[idx]
        except IndexError:
            _degrade(warnings, f"glyph {glyph.name!r}: stem {p.run} absent at {sample:g}; "
                               f"using ink envelope")
            lo, hi = cs[0], cs[-1]         # requested stem absent → envelope
    return _along(lo, hi, p.align)


def _axis(font, glyph, spec, axis: Axis, *, cross=None, warnings=None) -> float:
    """Resolve a position *spec* along *axis* to font units (no italic shift).

    *cross* is the other-axis coordinate, used as the scanline for an OUTLINE
    spec with ``at=None``. Absolute numbers and the glyph-independent Y kinds
    (metric / ``$glyph`` / sum) delegate to :func:`resolve_y`; the area
    :class:`Centroid` yields its x or y."""
    if isinstance(spec, Abs):
        return float(spec.value)
    if isinstance(spec, Centroid):
        cx, cy = _centroid(glyph, warnings=warnings)
        return cx if axis is Axis.X else cy
    if isinstance(spec, Neg):              # subtracted term inside a sum
        return -_axis(font, glyph, spec.term, axis, cross=cross, warnings=warnings)
    if isinstance(spec, Sum):              # terms resolved on this same axis
        return sum(_axis(font, glyph, t, axis, cross=cross, warnings=warnings)
                   for t in spec.terms)
    if isinstance(spec, (FontMetric, Y)):
        return resolve_y(font, spec, warnings=warnings)
    return _pos(font, glyph, spec, axis, cross=cross, warnings=warnings)


def _dependent(spec) -> bool:
    """Whether *spec* needs the other axis as its scanline (an OUTLINE position
    with no ``@``, or a sum containing one)."""
    if isinstance(spec, Neg):
        return _dependent(spec.term)
    if isinstance(spec, Sum):
        return any(_dependent(t) for t in spec.terms)
    return isinstance(spec, Pos) and spec.frame is Frame.OUTLINE and spec.at is None


def _needs_shift(xspec) -> bool:
    """Whether an X expression references an upright BOX/ADVANCE frame (so it
    needs the italic shear; OUTLINE crossings and the centroid are already on
    the slanted outline)."""
    if isinstance(xspec, Pos):
        return xspec.frame in (Frame.ADVANCE, Frame.BOX)
    if isinstance(xspec, Neg):
        return _needs_shift(xspec.term)
    if isinstance(xspec, Sum):
        return any(_needs_shift(t) for t in xspec.terms)
    return False


def _shift_x(font, xspec, y: float) -> float:
    """The italic shear correction (a single shift of the anchor point) for an X
    expression that references a BOX/ADVANCE frame."""
    return _italic_shift(font, y) if (_needs_shift(xspec) and y) else 0.0


def resolve_x(font, glyph, xspec, y: float, *, warnings=None) -> float:
    """Resolve an X strategy to a position in font units, at height *y*."""
    return _axis(font, glyph, xspec, Axis.X, cross=y, warnings=warnings) \
        + _shift_x(font, xspec, y)


def resolve(font, glyph, spec: AnchorSpec, *, warnings=None) -> tuple[float, float]:
    """Resolve a full anchor spec on *glyph* to an (x, y) position.

    Axes are resolved in dependency order: an OUTLINE position with ``at=None``
    is sampled on the *other* axis's resolved coordinate. The common case (Y
    independent) keeps the historical order — Y first, then X at that height. If
    Y is the dependent one, X is resolved first and used as Y's column. Both
    dependent at once is a cycle → :class:`AxisCycleError`.

    Pass a list as *warnings* to collect soft degradations (a value produced via
    a fallback — no outline crossing, missing metric/reference glyph) as reason
    strings; the coordinate is still returned. ``warnings=None`` (default) just
    logs them. Hard failures (malformed contours) still raise.
    """
    xs, ys = spec.x, spec.y
    if _dependent(xs) and _dependent(ys):
        raise AxisCycleError(
            f"anchor {spec.name!r}: both axes are outline-sampled with no @-fix "
            f"({xs} {ys}); add @ to one (e.g. {xs}@<height> or {ys}@<column>)")
    if _dependent(ys) and not _dependent(xs):
        x = _axis(font, glyph, xs, Axis.X, warnings=warnings)
        y = _axis(font, glyph, ys, Axis.Y, cross=x, warnings=warnings)
        x += _shift_x(font, xs, y)         # apply shear now that the height is known
    else:
        y = _axis(font, glyph, ys, Axis.Y, warnings=warnings)
        x = _axis(font, glyph, xs, Axis.X, cross=y, warnings=warnings)
        x += _shift_x(font, xs, y)
    return (x, y)
