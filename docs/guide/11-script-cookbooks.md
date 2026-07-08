# Script cookbooks

Worked, figure-driven rule sets for real scripts, each built on an
open-licensed font so every example renders from live engine output. Planned
sections:

- **Latin** — top/bottom/ogonek/cedilla anchors, small caps via `!suffixes`.
- **Cyrillic** — range defaults (`U+0410..U+044F`), descender and hook
  exceptions (Г, И, ч, …).
- **Greek** — dialytika/tonos stacking, iota subscript.
- **Devanagari** — the headline (shirorekha) as the top reference, `-deva`
  top/bottom matras, rakar and nukta attachment.
- **Hebrew** — below-base niqqud (centred marks under lopsided letters), dagesh
  inside the counter.
- **Thai** — above/below vowels and tone marks, avoiding ascenders
  (`maitaikhu`-style shifted variants).
- **Arabic notes** — what the per-glyph model does and does not cover for
  joining scripts; where derived anchors (`%name`), propagation (`!propagate`),
  and per-component frames (`compN.`) come in.

*(stub — to be written)*
