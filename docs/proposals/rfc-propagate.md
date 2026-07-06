# RFC: `!propagate` — component anchor inheritance

Status: draft · Priority: P1 · Evidence: [world-scripts research](../research/world-scripts-applicability.md)

## Motivation

In composite-heavy scripts most anchored glyphs are assembled from components:
**74 % of Scheherazade New's anchored glyphs are pure composites** (letter
skeleton + dots), and in Noto Sans Devanagari a Glyphs-style propagation
reproduces **76 %** of composite anchors exactly. Today every composite needs
its own rule even when its anchors are just the base component's anchors
carried through the component transform — hundreds of redundant lines for
Arabic "letter + dots" sets.

Font editors solved this long ago: Glyphs propagates anchors from components
automatically. AnchorsFactory should offer the same as an *opt-in seed* for
the accumulation model.

## Proposal

A directive with the usual whole-list states:

```
!propagate = composites     # seed pure composites (components, no contours)
!propagate = all            # also glyphs that mix contours + components
!propagate = none           # default — current behavior
```

### Semantics

- Propagation computes each glyph's **inherited anchors**: recursively resolve
  every component's effective anchors, apply the component transform
  (offset/scale/flip), later components override earlier ones on the same
  name (a mark component placed on top carries the next attachment level —
  Glyphs' rule).
- Mark-side anchors (`_`-prefixed) are **never propagated**: an attachment
  point of the mark itself is meaningful only on the mark glyph.
- The inherited set becomes the **initial accumulator state** for that glyph,
  *before* the first rule runs. Everything else falls out of the existing
  model with zero new operators:
  - `sel += …` adds to / overrides propagated anchors (last wins by name);
  - `sel = …` is the usual hard reset — drops propagated anchors too;
  - `sel -= name` removes a propagated anchor;
  - a glyph matched by no rule but covered by `!propagate` **does** get its
    inherited anchors placed.
- Composes through `!extends` like other directives (base first, this file
  last; whole-list states require `=`).
- Provenance: the studio and `accumulate_provenance` report these as
  `propagated from <component>` instead of a rule index.

### What it does not do

Propagation copies *existing* anchors through transforms. It does not
re-measure geometry (that's per-component frames,
[rfc-component-frames](rfc-component-frames.md)) and it cannot invent the
optical lift SIL applies above dots (measured non-constant in Scheherazade:
`teh-ar` +355 over dot-top 933). The expected division of labor:

```
!propagate = composites            # dots-carrying composites inherit diaB, alef, …
teh-ar += diaA (outline.center@top box.top+&liftA)   # optical exceptions stay explicit
```

## Engine changes

- `apply.py`: seeding step before rule scan; recursive component resolution
  with cycle guard and memo (component cycles are font bugs — warn, stop).
- `runner.py`/`presets`: directive parsing identical to `!suffixes` states.
- Needs read access to component transforms — available via fontParts.

## Open questions

1. Scaled/flipped components: propagate through the full affine (proposed)
   or offset-only with a warning on non-trivial transforms? Full affine is
   correct for the measured corpora (flips occur in Arabic mirrored forms).
2. Should `!suffixes` replay interact with propagation (a `.alt` composite
   inherits from its own components anyway)? Proposed: propagation is
   per-glyph and suffix-agnostic — no special casing.
