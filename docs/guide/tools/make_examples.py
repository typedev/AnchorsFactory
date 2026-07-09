#!/usr/bin/env python
"""Render SVG illustrations for the AnchorsFactory user guide.

Self-contained: run it with the project venv (fontTools + fontParts +
anchorsfactory are available there)::

    .venv/bin/python docs/guide/tools/make_examples.py render \
        --font path/to/Font.ufo --glyph Ka.dv \
        --anchor top:818:1238 --anchor bottom:812:23 \
        --hguide top:headline -o out.svg

    .venv/bin/python docs/guide/tools/make_examples.py rules \
        --font path/to/Font.ufo --glyph Ka.dv \
        --rules docs/guide/examples/deva-top-bottom.anchors \
        --hguide top:headline -o out.svg

Two modes:

``render``
    You supply the anchors explicitly (``--anchor name:x:y[:label]``) —
    useful for hand-drawn didactic figures.

``rules``
    The script runs **the real engine** (``anchorsfactory.runner.load_document``
    + ``anchorsfactory.apply.apply_document``) on an in-memory copy of the
    font and renders whatever anchors the given ``.anchors`` rules file produces
    for the glyph, annotated with the rule text.  Nothing is ever saved back
    to the font.  This keeps every guide illustration honest: the picture *is*
    the engine output.

The drawing is theme-neutral (dark strokes on a transparent background),
about 420 px tall, with the glyph filled using the nonzero rule, crosshair
anchor markers, dashed guide lines, baseline/metrics lines and em-box
padding.  UFOs are opened with fontParts, TTF/OTF binaries with fontTools.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen

# Make the repo importable even if anchorsfactory isn't installed in the env.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# palette — muted tones that survive both light and dark page themes
INK_FILL = "#7d7d7d"          # glyph body (semi-transparent)
INK_FILL_OPACITY = "0.38"
INK_STROKE = "#4a4a4a"        # glyph contour
METRIC_COLOR = "#8f8f8f"      # ascender/descender/x-height/cap-height
BASELINE_COLOR = "#5f5f5f"
GUIDE_COLOR = "#3d7ea6"       # dashed user guides (scanlines, headline, …)
ANCHOR_COLOR = "#c14a2e"      # anchor crosshairs + labels
CAPTION_COLOR = "#6b6b6b"     # rule-text caption
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
SANS = "system-ui, -apple-system, 'Segoe UI', sans-serif"


@dataclass
class FontData:
    family: str
    style: str
    upm: float
    ascender: float
    descender: float
    x_height: float | None
    cap_height: float | None
    glyph_set: object                       # name -> drawable glyph
    _ufo: object = None                     # fontParts font, when UFO

    def metric(self, name):
        table = {
            "baseline": 0,
            "ascender": self.ascender,
            "descender": self.descender,
            "xHeight": self.x_height,
            "capHeight": self.cap_height,
            "unitsPerEm": self.upm,
        }
        return table.get(name)

    def glyph_path(self, glyph_name):
        """Return (svg_path_d, advance_width, ink_bounds) for a glyph."""
        glyph = self.glyph_set[glyph_name]
        pen = SVGPathPen(self.glyph_set)
        glyph.draw(pen)
        bp = BoundsPen(self.glyph_set)
        glyph.draw(bp)
        width = getattr(glyph, "width", None)
        if width is None:                   # fontTools _TTGlyphSet glyph
            width = glyph.width if hasattr(glyph, "width") else 0
        return pen.getCommands(), width, bp.bounds


def load_font(path: str) -> FontData:
    path = path.rstrip(os.sep)
    if path.lower().endswith(".ufo"):
        from fontParts.world import OpenFont

        font = OpenFont(path, showInterface=False)
        info = font.info
        return FontData(
            family=info.familyName or "?",
            style=info.styleName or "",
            upm=info.unitsPerEm or 1000,
            ascender=info.ascender if info.ascender is not None else 800,
            descender=info.descender if info.descender is not None else -200,
            x_height=info.xHeight,
            cap_height=info.capHeight,
            glyph_set=font,
            _ufo=font,
        )
    # binary font (TTF/OTF)
    from fontTools.ttLib import TTFont

    tt = TTFont(path)
    name = tt["name"]
    os2 = tt["OS/2"] if "OS/2" in tt else None
    return FontData(
        family=name.getDebugName(1) or "?",
        style=name.getDebugName(2) or "",
        upm=tt["head"].unitsPerEm,
        ascender=tt["hhea"].ascender,
        descender=tt["hhea"].descender,
        x_height=getattr(os2, "sxHeight", None) if os2 else None,
        cap_height=getattr(os2, "sCapHeight", None) if os2 else None,
        glyph_set=tt.getGlyphSet(),
    )


# ---------------------------------------------------------------------------
# argument parsing helpers

@dataclass
class Anchor:
    name: str
    x: float
    y: float
    label: str = ""


@dataclass
class Guide:
    value: str          # number | metric name | top/bottom (H) | left/right (V)
    label: str = ""


def parse_anchor(text: str) -> Anchor:
    parts = text.split(":")
    if len(parts) < 3:
        raise argparse.ArgumentTypeError(f"--anchor wants name:x:y[:label], got {text!r}")
    name, x, y = parts[0], float(parts[1]), float(parts[2])
    return Anchor(name, x, y, ":".join(parts[3:]))


def parse_guide(text: str) -> Guide:
    value, _, label = text.partition(":")
    return Guide(value.strip(), label.strip())


def resolve_guide(value: str, font: FontData, ink) -> float | None:
    """A guide position: a number, a font-metric name, or an ink-box edge."""
    try:
        return float(value)
    except ValueError:
        pass
    m = font.metric(value)
    if m is not None:
        return float(m)
    if ink is not None:
        edges = {"left": ink[0], "bottom": ink[1], "right": ink[2], "top": ink[3]}
        if value in edges:
            return float(edges[value])
    return None


# ---------------------------------------------------------------------------
# SVG assembly

def fmt(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


@dataclass
class Scene:
    """Collects SVG fragments in font units, then serialises with a y-flip."""
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    height_px: float
    caption: list = field(default_factory=list)
    body: list = field(default_factory=list)

    @property
    def u(self) -> float:
        """Font units per output pixel (so strokes/text keep a px-true size)."""
        return (self.max_y - self.min_y) / self.height_px

    def sx(self, x):
        return x - self.min_x

    def sy(self, y):
        return self.max_y - y

    def hline(self, y, color, width_px, dash=None, opacity=None):
        d = f' stroke-dasharray="{fmt(dash[0]*self.u)} {fmt(dash[1]*self.u)}"' if dash else ""
        o = f' stroke-opacity="{opacity}"' if opacity else ""
        self.body.append(
            f'<line x1="0" y1="{fmt(self.sy(y))}" x2="{fmt(self.max_x - self.min_x)}"'
            f' y2="{fmt(self.sy(y))}" stroke="{color}"'
            f' stroke-width="{fmt(width_px * self.u)}"{d}{o}/>'
        )

    def vline(self, x, color, width_px, dash=None, opacity=None):
        d = f' stroke-dasharray="{fmt(dash[0]*self.u)} {fmt(dash[1]*self.u)}"' if dash else ""
        o = f' stroke-opacity="{opacity}"' if opacity else ""
        self.body.append(
            f'<line x1="{fmt(self.sx(x))}" y1="0" x2="{fmt(self.sx(x))}"'
            f' y2="{fmt(self.max_y - self.min_y)}" stroke="{color}"'
            f' stroke-width="{fmt(width_px * self.u)}"{d}{o}/>'
        )

    def text(self, x, y, s, color, size_px, anchor="start", mono=False, opacity=None):
        o = f' fill-opacity="{opacity}"' if opacity else ""
        esc = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.body.append(
            f'<text x="{fmt(self.sx(x))}" y="{fmt(self.sy(y))}" fill="{color}"'
            f' font-family="{MONO if mono else SANS}" font-size="{fmt(size_px * self.u)}"'
            f' text-anchor="{anchor}"{o}>{esc}</text>'
        )


def build_svg(font: FontData, glyph_name: str, anchors: list[Anchor],
              hguides: list[Guide], vguides: list[Guide],
              caption_lines: list[str], title: str | None,
              height_px: float = 420.0, fit: str = "em") -> str:
    path_d, adv_width, ink = font.glyph_path(glyph_name)

    # --- extent: em box (or ink box) + anchors, padded ------------------------
    pad = 0.05 * font.upm
    xs = [0.0, float(adv_width)]
    ys = [0.0]                                   # the baseline is always shown
    if fit == "em":
        ys += [float(font.descender), float(font.ascender)]
    if ink:
        xs += [ink[0], ink[2]]
        ys += [ink[1], ink[3]]
    for a in anchors:
        xs.append(a.x)
        ys.append(a.y)
    resolved_h = [(g, resolve_guide(g.value, font, ink)) for g in hguides]
    resolved_v = [(g, resolve_guide(g.value, font, ink)) for g in vguides]
    ys += [y for _, y in resolved_h if y is not None]
    xs += [x for _, x in resolved_v if x is not None]

    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad

    sc = Scene(min_x, max_x, min_y, max_y, height_px)
    u = sc.u

    # room for anchor labels that stick out on the right, and for the
    # caption/title text (the scale is set by the height, so long lines
    # would otherwise run past the viewBox)
    label_overhang = 0.0
    for a in anchors:
        text = a.label or f"{a.name} ({fmt(a.x)}, {fmt(a.y)})"
        end = a.x + (12 + 6.4 * len(text)) * u
        label_overhang = max(label_overhang, end - max_x)
    text_w = 0.0
    if caption_lines:
        text_w = max(text_w, (12 + 6.4 * max(map(len, caption_lines))) * u)
    if title:
        text_w = max(text_w, (12 + 6.0 * len(title)) * u)
    sc.max_x += max(label_overhang, 0.0, text_w - (max_x - min_x))
    if title:                                  # headroom so the title floats free
        sc.max_y += 26 * u

    # --- metrics (only the lines that fall inside the view) -------------------
    for mname in ("ascender", "descender", "xHeight", "capHeight"):
        v = font.metric(mname)
        if v is None or v == 0 or not (sc.min_y <= v <= sc.max_y - (30 * u if title else 0)):
            continue
        sc.hline(v, METRIC_COLOR, 0.8, opacity="0.55")
        sc.text(sc.min_x + 6 * u, v + 4 * u, mname, METRIC_COLOR, 9, opacity="0.8")
    sc.hline(0, BASELINE_COLOR, 1.1)
    sc.text(sc.min_x + 6 * u, 4 * u, "baseline", BASELINE_COLOR, 9, opacity="0.85")

    # advance-width sidebearings
    for x in (0.0, float(adv_width)):
        sc.vline(x, METRIC_COLOR, 0.8, dash=(2, 3), opacity="0.5")

    # --- user guides ----------------------------------------------------------
    for g, y in resolved_h:
        if y is None:
            print(f"warning: hguide {g.value!r} not resolvable, skipped", file=sys.stderr)
            continue
        sc.hline(y, GUIDE_COLOR, 1.1, dash=(7, 5))
        if g.label:
            # below the line, right-aligned — anchor labels live above lines
            sc.text(sc.max_x - 6 * u, y - 15 * u, g.label, GUIDE_COLOR, 10, anchor="end")
    for g, x in resolved_v:
        if x is None:
            print(f"warning: vguide {g.value!r} not resolvable, skipped", file=sys.stderr)
            continue
        sc.vline(x, GUIDE_COLOR, 1.1, dash=(7, 5))
        if g.label:
            sc.text(x + 5 * u, sc.max_y - 14 * u, g.label, GUIDE_COLOR, 10)

    # --- glyph (y-flipped group; nonzero fill renders overlaps correctly) ----
    if path_d:
        sc.body.append(
            f'<g transform="translate({fmt(-sc.min_x)},{fmt(sc.max_y)}) scale(1,-1)">'
            f'<path d="{path_d}" fill="{INK_FILL}" fill-opacity="{INK_FILL_OPACITY}"'
            f' fill-rule="nonzero" stroke="{INK_STROKE}"'
            f' stroke-width="{fmt(1.0 * u)}"/></g>'
        )

    # --- anchors: crosshair circles + labels ----------------------------------
    r = 4.5 * u
    tick = 9.0 * u
    for a in anchors:
        cx, cy = sc.sx(a.x), sc.sy(a.y)
        w = fmt(1.4 * u)
        sc.body.append(
            f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(r)}" fill="none"'
            f' stroke="{ANCHOR_COLOR}" stroke-width="{w}"/>'
            f'<line x1="{fmt(cx - tick)}" y1="{fmt(cy)}" x2="{fmt(cx + tick)}" y2="{fmt(cy)}"'
            f' stroke="{ANCHOR_COLOR}" stroke-width="{w}"/>'
            f'<line x1="{fmt(cx)}" y1="{fmt(cy - tick)}" x2="{fmt(cx)}" y2="{fmt(cy + tick)}"'
            f' stroke="{ANCHOR_COLOR}" stroke-width="{w}"/>'
        )
        text = a.label or f"{a.name} ({fmt(a.x)}, {fmt(a.y)})"
        sc.text(a.x + 12 * u, a.y + 10 * u, text, ANCHOR_COLOR, 11)

    # --- title ----------------------------------------------------------------
    if title:
        sc.text(sc.min_x + 6 * u, sc.max_y - 16 * u, title, CAPTION_COLOR, 11)

    # --- caption below the drawing --------------------------------------------
    caption_svg = []
    line_h = 15 * u
    cap_h = (len(caption_lines) * line_h + 12 * u) if caption_lines else 0.0
    for i, line in enumerate(caption_lines):
        esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        y = (sc.max_y - sc.min_y) + (i + 1) * line_h
        caption_svg.append(
            f'<text x="{fmt(6 * u)}" y="{fmt(y)}" fill="{CAPTION_COLOR}"'
            f' font-family="{MONO}" font-size="{fmt(10.5 * u)}">{esc}</text>'
        )

    vb_w = sc.max_x - sc.min_x
    vb_h = (sc.max_y - sc.min_y) + cap_h
    px_w = round(vb_w / u)
    px_h = round(vb_h / u)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {fmt(vb_w)} {fmt(vb_h)}"'
        f' width="{px_w}" height="{px_h}">',
        *sc.body,
        *caption_svg,
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# rules mode: run the real engine on an in-memory font

def anchors_from_rules(font: FontData, glyph_name: str, rules: str) -> list[Anchor]:
    if font._ufo is None:
        raise SystemExit("rules mode needs a UFO font (fontParts)")
    from anchorsfactory.apply import apply_document
    from anchorsfactory.runner import load_document

    doc = load_document(rules)
    # Mutates the in-memory font only; we never call font.save().
    apply_document(font._ufo, doc, names=[glyph_name])
    glyph = font._ufo[glyph_name]
    return [Anchor(a.name, a.x, a.y) for a in glyph.anchors]


def rule_caption(rules: str, max_lines: int = 8) -> list[str]:
    if not os.path.exists(rules):        # bundled preset name
        return [f"!rules {rules}"]
    lines = []
    with open(rules, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            if line.strip():
                lines.append(line)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["…"]
    return lines


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="mode", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--font", required=True, help="UFO directory or TTF/OTF file")
    common.add_argument("--glyph", required=True, help="glyph name")
    common.add_argument("--hguide", action="append", default=[], type=parse_guide,
                        help="horizontal dashed guide: 'y[:label]' — a number, a "
                             "metric name (xHeight, capHeight, …) or top/bottom "
                             "(the glyph's ink box)")
    common.add_argument("--vguide", action="append", default=[], type=parse_guide,
                        help="vertical dashed guide: 'x[:label]' — a number or left/right")
    common.add_argument("--title", default=None,
                        help="small title line (default: 'glyph — Family Style')")
    common.add_argument("--no-title", action="store_true")
    common.add_argument("--height", type=float, default=420.0,
                        help="drawing height in px (default 420)")
    common.add_argument("--fit", choices=("em", "ink"), default="em",
                        help="vertical extent: the full em box (default), or just "
                             "the ink box + baseline (better for large-em designs)")
    common.add_argument("-o", "--out", required=True, help="output .svg path")

    p_render = sub.add_parser("render", parents=[common],
                              help="render explicitly supplied anchors")
    p_render.add_argument("--anchor", action="append", default=[], type=parse_anchor,
                          help="anchor as name:x:y[:label]; repeatable")
    p_render.add_argument("--caption", action="append", default=[],
                          help="caption line under the drawing; repeatable")

    p_rules = sub.add_parser("rules", parents=[common],
                             help="run anchorsfactory on the font and render the result")
    p_rules.add_argument("--rules", required=True,
                         help=".anchors rules file (or bundled preset name)")
    p_rules.add_argument("--caption", action="append", default=None,
                         help="override the rule-text caption; repeatable")
    p_rules.add_argument("--no-caption", action="store_true")

    args = ap.parse_args(argv)
    font = load_font(args.font)

    if args.mode == "render":
        anchors = args.anchor
        caption = args.caption
    else:
        anchors = anchors_from_rules(font, args.glyph, args.rules)
        if not anchors:
            print(f"warning: rules produced no anchors for {args.glyph}", file=sys.stderr)
        caption = [] if args.no_caption else (args.caption or rule_caption(args.rules))

    title = None if args.no_title else (
        args.title or f"{args.glyph} — {font.family} {font.style}".rstrip())

    svg = build_svg(font, args.glyph, anchors, args.hguide, args.vguide,
                    caption, title, height_px=args.height, fit=args.fit)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)
    size = os.path.getsize(args.out)
    print(f"wrote {args.out} ({size} bytes, {len(anchors)} anchors)")


if __name__ == "__main__":
    main()
