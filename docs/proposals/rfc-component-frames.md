# RFC: Per-component frames — `comp1.outline.*`, `comp2.box.*`

Status: **implemented** (v0.5.0) · Priority: P1 · Evidence: [world-scripts research](../research/world-scripts-applicability.md)

## Motivation

Ligatures attach marks **per component**: GPOS `MarkLigPos` gives lam-alef one
`diaA` per ligature part, and UFO sources carry the convention as indexed
names (`diaA_1`, `diaA_2` in Scheherazade/Harmattan — 134 glyphs each; the
fontmake feature writers use the same `top_1`/`top_2` convention). The DSL
already *names* such anchors fine, but the geometry engine can only see the
whole glyph: `outline.first/last` picks ink spans on a single scanline, which
is not "the first/second letter of the ligature" (parts overlap vertically,
spans split on counters, etc.).

## Proposal

An optional **component qualifier** in front of any frame:

```
comp1.outline.center@top      # ink centre at the top of the 1st component
comp2.box.right               # bbox right edge of the 2nd component
complast.outline.left@&h      # last component
```

Usage:

```
# lam-alef: one mark seat per ligature part
*lam_alef* += diaA_1 (comp1.outline.center@top box.top+&liftA),
              diaA_2 (comp2.outline.center@top box.top+&liftA)
```

Grammar: `comp<N>.` (1-based, component order in the glyph) or `complast.`,
prefixed to the existing `frame.position` expression — the rest of the token
grammar (`run`, `align`, `@…`) is unchanged. Rejected alternative:
`outline.comp2.center` — overloads the `run` slot, which already means ink
spans; two different selection concepts should not share a position.

## Semantics

- The qualifier restricts **which outline the frame measures**: the decomposed
  outline contributed by the N-th top-level component (recursively flattened,
  with its transform applied — coordinates stay in the glyph's space).
- Works with all frames: `box` = bbox of that component's outline; `outline`
  = crossings against only its segments; `centroid` = its area centre.
  `width` takes no qualifier (the advance belongs to the whole glyph) —
  load-time error.
- On a glyph with fewer components than N (or none): warning + fall back to
  the unqualified frame (consistent with the bbox-edge degrade policy).
- Contours mixed with components: `comp1` still means the first *component*;
  own contours are only measured by unqualified frames. (A hypothetical
  `self.` qualifier for "own contours only" is deferred until needed.)
- Italic shear: unchanged — the shift is a function of sample height,
  independent of which outline subset was sampled.

## IR / engine changes

- `model.py`: `Pos` gains `component: Optional[int]` (`-1` = last);
  serialized as the `compN.` prefix.
- `dsl.py`: prefix parsing; `comp` is safe — current grammar has no
  identifier position before a frame keyword.
- `geometry.py`: `_segments(glyph, component=None)` — the existing
  `DecomposingRecordingPen` walk, filtered to the N-th `addComponent`
  subtree; `_crossings`/`_centroid`/bbox take the filtered segment stream.
  Bounds for `box` come from the same stream (not `glyph.bounds`).

## Relationship to other proposals

- [`!propagate`](rfc-propagate.md) *copies* existing component anchors;
  component frames *measure fresh geometry*. Ligature seats typically need
  the latter (the parts' own anchors aren't the ligature's seats).
- Combines naturally with [derived anchors](rfc-derived-anchors.md):
  `diaB_2 (%diaA_2 %diaB_1)` style mixes are legal since both are terms.
