# RFC: Derived anchors — referencing another anchor's position

Status: **implemented** (v0.5.0) · Priority: P1 · Evidence: [world-scripts research](../research/world-scripts-applicability.md)

## Motivation

Real fonts carry families of anchors that are *exact constant offsets* of one
primary anchor. Measured: Anek Devanagari's stacking levels `bottom2/3/5` sit
at (−7, 0) / (+94, 0) / (−1, +19.5) from `bottom` with **zero spread across
480–564 glyphs**; Gulzar's nuqta rows are bands exactly 200 units apart; Noto
Devanagari pairs `_bottom/_bottom2`. Today each level repeats the full
position expression — three copies of the same outline sample that can drift
apart when edited.

## Proposal

A new polymorphic term: **`%name`** — the position of the anchor `name`
already accumulated **on the same glyph**. In an X slot it yields that
anchor's x, in a Y slot its y (same polymorphism as `outline.centroid`). It
composes with `+`/`-` like any term:

```
@stack = bottom  (outline.last.center@&stemh outline.bottom+&bgap),
         bottom2 (%bottom-7  %bottom),
         bottom3 (%bottom+94 %bottom),
         bottom5 (%bottom-1  %bottom+20)
```

One primary rule; the levels are declared as what they are — offsets.

### Sigil

`%` is the last free sigil (`@` label, `&` variable, `$` glyph, `!` directive,
`#` comment). Rejected alternatives:

- `bottom.x` / `bottom.y` bare — collides with the `box/width/outline`
  keyword namespace and with glyph names; un-greppable.
- A whole-anchor statement `bottom2 = bottom + (-7 0)` — introduces a second
  meaning for `=` inside rule lines and a new statement kind; the term form
  reuses the existing expression grammar unchanged.

## Semantics

- **Reference target.** `%name` resolves against the glyph's *final*
  accumulated anchor list (after all rules, labels late-bound, last-wins) —
  the same list the placement engine writes. Referencing an anchor that a
  later rule then removes (`-=`) or replaces follows the final list, not
  source order: consistent with the label model, no ordering surprises.
- **Resolution order.** Anchors are computed in dependency order; `%a → %b →
  %a` cycles are rejected per glyph with the chain named (same style as
  `&var` cycles). Depth is naturally bounded by anchor count.
- **Missing target.** Warning + the anchor is skipped (consistent with the
  missing-`$glyph` degrade policy).
- **Italic.** No extra shear: the referenced anchor's coordinates are already
  final (sheared). A `%ref+bias` sum shifts along the axis, not along the
  italic angle — documented; use outline terms when angle-following is needed.
- **In `&` variables.** Allowed, polymorphic like a bare number
  (`&stackdx = %bottom-7` is *not* allowed — a var must stay glyph-agnostic).
  Decision: **forbid `%` in `&` definitions** in v1; a variable is evaluated
  per glyph only through the anchor that uses it, which would make `&`
  silently glyph-dependent. Revisit if a use case appears.

## IR / engine changes

- `model.py`: new frozen dataclass `AnchorRef(name: str)`, polymorphic
  (legal as XStrategy and YStrategy); `__str__` → `%name`.
- `dsl.py`: term parser accepts `%name` (name = same charset as anchor
  names); participates in sums.
- `apply.py`: per-glyph topological resolve over the final accumulator;
  cycle/undefined checks live next to the existing late-bound label/var
  checks. `validate_document` can statically flag references to names never
  produced by any rule (warning, not error — suffix replay may add them).
- `geometry.py`: untouched — `AnchorRef` is resolved above the geometry
  layer by substituting the computed (x, y).

## Open questions

1. Should `%name` see anchors *propagated* from components
   (see [rfc-propagate](rfc-propagate.md))? Proposed: yes — propagation seeds
   the accumulator, so it falls out naturally.
2. Cross-glyph references (`%$OtherGlyph.top`)? Out of scope; `$Glyph`
   heights cover the known cases.
