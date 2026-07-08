# RFC: Arithmetic on `@` sample positions (edge insets)

Status: **implemented** (v0.5.0) · Priority: P2 · Evidence: [world-scripts research](../research/world-scripts-applicability.md), §Engine notes

## Motivation

`@top`/`@bottom` sample the contour at *exactly* the glyph's bbox edge. At a
smooth peak the scanline is tangent to the outline: the engine returns the
grazing point or, when the intersection math finds nothing, falls back to the
bbox edge with a warning. Measured cost: the research battery sampled 2 units
inside the edge and reproduced Devanagari `_top` marks at ~60 %, while the
identical rule through the engine's exact-edge sampling scored **26 %**.
The same applies to Arabic tooth-finding (`outline.center@top`), the single
most useful X reference for above-marks.

## Proposal

Allow a numeric offset after any `@` base token:

```
outline.center@top-10        # sample 10 units below the glyph's own bbox top
outline.center@bottom+8      # 8 units above the bbox bottom
outline.right@xHeight-20     # metrics and &vars too
outline.center@&h+5
```

Semantics: the offset adjusts the **sample line position only**; the anchor's
other coordinate and italic projection source (`S`) use the adjusted height —
i.e. `@top-10` behaves exactly like an `@<number>` whose value happens to be
`yMax-10`, kept glyph-relative.

Bare `@top`/`@bottom` keep today's exact-edge behavior — no silent change.

## Grammar note

The spec currently says "a bias and an `@` sample on the same term don't
combine inline — the `@` owns the rest of the token". That stays true for the
*position* bias (`outline.center+25@top` remains illegal); this RFC extends
what the `@`-owned tail may contain: `<base>[±n]`. No ambiguity: the tail is
parsed as a mini Y/X expression that already supports sums
(`@capHeight*1/2+10` falls out for free if the tail reuses the axis-expression
parser — recommended).

## Alternatives considered

- `!edgeinset = 10` directive making bare `@top`/`@bottom` inset by default:
  convenient but changes the meaning of existing files that inherit it via
  `!extends`; deferred.
- Engine-side auto-widening at tangency (retry a few units inside when the
  scanline yields no span): fixes the no-crossing case but silently moves the
  measured point; explicit syntax keeps rules honest.

## Engine changes

Small: `dsl.py` reuses the axis-expression parser for the `@` tail;
`geometry._sample_line` already takes a resolved number. `model.Pos.at`
gains `Sum` support (it may already, via `resolve_y` — verify and test the
serializer round-trip).
