"""A small synthetic in-memory font for Studio's no-font mode.

Real test fonts are confidential and never ship, so the debugger must be able to
run — and be screenshot-able and testable — with nothing external. This builds a
handful of schematic-but-real glyphs (simple closed polygons, genuinely
drawable) whose names/unicodes the bundled ``default`` preset matches, so every
overlay kind has something to show: box positions, advance centres, outline
scanlines with paired stems, and marks.

The shapes are deliberately crude (an ``H`` is two stems and a bar, an ``o`` is
two nested rectangles). They are not a typeface — they are just enough ink for
the geometry engine to sample.
"""

from __future__ import annotations

# fontParts is a hard dependency of the engine, so importing it here is safe.
from fontParts.world import RFont

UPM = 1000
CAP = 700
XH = 500
ASC = 750
DESC = -200


def _glyph(font, name, width, unicode, contours):
    """Add one glyph built from *contours* (each a list of (x, y) polygon points)."""
    g = font.newGlyph(name)
    g.width = width
    if unicode is not None:
        g.unicode = unicode
    pen = g.getPen()
    for pts in contours:
        pen.moveTo(pts[0])
        for p in pts[1:]:
            pen.lineTo(p)
        pen.closePath()
    return g


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _hole(x0, y0, x1, y1):
    """A counter — the reverse winding of :func:`_rect`, so the nonzero fill rule
    cuts it out (matching how real font counters are wound)."""
    return _rect(x0, y0, x1, y1)[::-1]


def build_demo_font():
    """Return a fresh in-memory :class:`RFont` populated with demo glyphs."""
    font = RFont()
    info = font.info
    info.familyName = "AnchorsFactory Demo"
    info.styleName = "Regular"
    info.unitsPerEm = UPM
    info.capHeight = CAP
    info.xHeight = XH
    info.ascender = ASC
    info.descender = DESC
    info.italicAngle = 0

    # ---- Uppercase (cap-height bases) ----
    # H: two stems + crossbar — a horizontal scanline finds two clean stems.
    _glyph(font, "H", 700, 0x48, [
        _rect(100, 0, 200, CAP),
        _rect(500, 0, 600, CAP),
        _rect(200, 320, 500, 400),
    ])
    # O: a ring (outer + counter) with overshoot — 4 crossings → 2 stems.
    _glyph(font, "O", 720, 0x4F, [
        _rect(80, -10, 640, CAP + 10),
        _hole(180, 110, 540, CAP - 110),
    ])
    # A: a solid trapezoid — a single stem that narrows with height.
    _glyph(font, "A", 680, 0x41, [
        [(40, 0), (200, 0), (440, CAP), (240, CAP)],
    ])

    # ---- Lowercase ----
    # n: two stems joined by a top bar (x-height).
    _glyph(font, "n", 560, 0x6E, [
        _rect(90, 0, 190, XH),
        _rect(380, 0, 480, XH),
        _rect(90, 420, 480, XH),
    ])
    # Round lowercase (o/a/e) — ring with overshoot at the x-height.
    for name, uni, w in (("o", 0x6F, 500), ("a", 0x61, 500), ("e", 0x65, 500)):
        _glyph(font, name, w, uni, [
            _rect(70, -10, w - 70, XH + 10),
            _hole(150, 100, w - 150, XH - 100),
        ])

    # ---- Marks ----
    # acute: a right-leaning parallelogram (no flat bottom → outline centre is
    # sampled on the two slanted sides).
    # Encoded like a real font's spacing accents, so codepoint-addressed rules
    # (the bundled presets) reach them.
    _glyph(font, "acute", 0, 0x00B4, [
        [(200, 520), (280, 520), (360, 640), (280, 640)],
    ])
    # dieresis: two square dots — a box-centre mark.
    _glyph(font, "dieresis", 0, 0x00A8, [
        _rect(150, 560, 230, 640),
        _rect(300, 560, 380, 640),
    ])

    # ---- Composite (for !propagate demos) ----
    # aacute = a + acute, a pure composite, so `!propagate = composites` in the
    # editor shows it inheriting a's anchors (pushed through the acute offset).
    aacute = font.newGlyph("aacute")
    aacute.unicode = 0x00E1
    aacute.width = 500
    aacute.appendComponent("a", offset=(0, 0))
    aacute.appendComponent("acute", offset=(-30, 40))
    return font


def font_metrics(font):
    """The named horizontal-guide heights a UI draws behind the glyph."""
    info = font.info
    out = {"baseline": 0.0}
    for name in ("xHeight", "capHeight", "ascender", "descender"):
        value = getattr(info, name, None)
        if value is not None:
            out[name] = float(value)
    return out
