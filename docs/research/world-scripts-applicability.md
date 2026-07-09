# Anchors beyond Latin: applicability of the rule DSL to world scripts

*Research report, July 2026. 21 open-licensed fonts, ~63,000 designer-placed
anchors. Machine-readable results and the analysis scripts lived in a session
scratchpad; everything needed to reproduce is described in [Method](#method).*

## Question

AnchorsFactory's rule language was designed against Latin, Cyrillic and Greek.
Can it place the anchors that real Arabic, Indic, South-East Asian, Hebrew and
CJK fonts actually carry — under the project's core constraint that anchors are
**never absolute coordinates**, only positions derived from the glyph's own
geometry and the font's metrics, so that rules stay portable across fonts?

## Method

Three data channels, so the corpus isn't biased toward one authoring culture:

1. **UFO sources with authorial anchor names** — SIL Scheherazade New,
   Harmattan, Awami Nastaliq; Ek Type Anek (Devanagari, Bangla, Tamil);
   Noto Sans Thai. All OFL.
2. **Compiled TTF/OTF from Google Fonts** — a GPOS extractor (fontTools)
   reconstructs attachment points from `MarkBasePos`, `MarkMarkPos`,
   `MarkLigPos` (per-ligature-component!) and `CursivePos` lookups. Designer
   names are lost; groups are synthesized per (feature, lookup, class), which
   matches attachment classes closely enough for grouping.
3. **Glyphs sources via glyphsLib** — Noto Sans Devanagari
   (`.glyphspackage` → UFO master).

For every anchor, a battery of candidate expressions — all of them expressible
in the current DSL — was evaluated with AnchorsFactory's own geometry
primitives (`_crossings`, `_spans`, `_centroid`): every `frame × align` combo
(`width/box/outline` × `left/center/right` / `bottom/middle/top`), outline
scans at the anchor's own height, at fixed `&var` heights, and at the glyph's
own `@top`/`@bottom` edges, `outline.centroid`, fractional positions
(`box*n/m`, `width*n/m`), font metrics, and constants (expressible via
`$Glyph`/`&var`).

Scoring, per (anchor-name group, candidate): residual = actual − predicted; a
candidate *explains* an anchor when the residual is within tolerance of the
group's constant bias (a `+n` term). Tolerance = **0.5 % of UPM** (5–10
units). Two headline metrics:

- **best** — coverage of the single best rule (one candidate + one bias) for
  the whole group;
- **any** — coverage of a *small ruleset*: per glyph, does any candidate (with
  its group bias) hit? This models what subclass selectors achieve. The number
  of residual clusters estimates how many rule lines a group needs.

## Corpus results

| Font | Anchors | best X | any X | best Y | any Y |
|---|--:|--:|--:|--:|--:|
| **Arabic** | | | | | |
| Noto Naskh Arabic (TTF) | 1,973 | 62% | 85% | 57% | 74% |
| Amiri (TTF) | 11,580¹ | 12% | 49% | 68% | 72% |
| Scheherazade New (UFO, SIL) | 4,671 | 24% | 55% | 22% | 39% |
| Harmattan (UFO, SIL) | 4,935 | 26% | 72% | 36% | 57% |
| **Nastaliq** | | | | | |
| Gulzar (TTF) | 5,405 | 19% | 51% | 33% | 50% |
| Awami Nastaliq (UFO, SIL)² | 6,024 | 43% | 63% | 40% | 55% |
| **Indic** | | | | | |
| Anek Devanagari (UFO) | 3,297 | 72% | 85% | 84% | 93% |
| Noto Sans Devanagari (Glyphs→UFO) | 1,440 | 61% | 79% | 80% | 88% |
| Noto Sans Devanagari (TTF) | 2,217 | 63% | 84% | 82% | 90% |
| Anek Bangla (UFO) | 2,090 | 44% | 74% | 69% | 75% |
| Noto Sans Bengali (TTF) | 1,708 | 58% | 81% | 68% | 81% |
| Anek Tamil (UFO) | 627 | 54% | 83% | 70% | 88% |
| Noto Sans Tamil (TTF) | 802 | 72% | 92% | 84% | 92% |
| **SE Asia & Tibet** | | | | | |
| Noto Sans Thai (UFO) | 182 | 47% | 83% | 71% | 86% |
| Noto Sans Thai (TTF) | 221 | 52% | 86% | 78% | 94% |
| Noto Sans Khmer (TTF) | 1,420 | 59% | 86% | 81% | 90% |
| Noto Sans Myanmar (TTF) | 1,432 | 66% | 90% | 87% | 94% |
| Noto Serif Tibetan (TTF) | 11,532 | 62% | 90% | 71% | 78% |
| **Hebrew** | | | | | |
| Noto Sans Hebrew (TTF) | 1,296 | 69% | 93% | 66% | 80% |
| **CJK** | | | | | |
| Source Han Sans (OTF) | 144 | 96% | 96% | 100% | 100% |
| Noto Sans KR (TTF) | 144 | 96% | 96% | 100% | 100% |

¹ Amiri repeats anchors across many contextual lookups; the count and the low
bestX are inflated/deflated by that duplication.
² Awami is positioned by Graphite; its UFO anchors mix mark/mkmk semantics
with SIL build-system attachment points.

## Per-script findings

### Indic (Devanagari, Bangla, Tamil) — good, 75–93 %

- **Top anchors** live on the headline shelf: `Y ≈ capHeight−40` (constant,
  79–80 %); X is the right ink edge minus a constant (matras dock to the
  right stem).
- **Bottom anchors** hug the ink: `outline.bottom+23` (81–93 %); X is the
  last stem's centre — which needs a `@`-fixed sample height (see
  [engine notes](#engine-notes)).
- **Marks**: the classic `_top (outline.center@bottom &headline)`.
- **Stacking levels are exact derived anchors.** In Anek Devanagari,
  `bottom2`, `bottom3`, `bottom5` sit at *constant offsets* from `bottom`:
  (−7, 0), (+94, 0), (−1, +19.5) — **zero spread over 480–564 glyphs**. The
  DSL currently forces duplicating the whole expression per level.
- Ligature caret anchors (`caret_1`, `caret_2`) exist and the DSL already
  accepts the names.

### Arabic naskh — partial; the residual is real hand-tuning

- Noto Naskh automates at 85/74 %. Hand-built SIL sources score lower and the
  reason is structural: **74 % of Scheherazade's anchored glyphs are pure
  composites** (skeleton + dots), and SIL re-places `diaA` above the dots by
  hand. Case study `teh-ar`: base `diaA` (957, 848) → composite (873, 1288);
  the dot component carries only `_above`, so naive component propagation
  reproduces 38 %, and the lift above the dots is optical, not constant
  (+355 over a dot-top of 933).
- Honest verdict: professional naskh ≈ 55–85 % from global rules; the rest is
  per-glyph. Crucially, per-glyph rules stay **relative**
  (`teh-ar = diaA (outline.center@top box.top+355)`) — no absolute
  coordinates needed, so weight/master portability survives.
- Positional forms (`.init/.medi/.fina`) map directly onto `!suffixes` and
  glob selectors.
- **Ligature anchors** (`diaA_1`/`diaA_2`, GPOS `MarkLigPos`) parse fine as
  names, but the geometry engine cannot address "the first/second part of a
  ligature": `outline.first/last` picks ink spans on one scanline, not
  components.
- Cursive anchors of naskh itself are geometric: Scheherazade `entry` =
  `outline.center@bottom` 82 % (anyX 100 %); Amiri `exit` = `width.left`
  88 %.

### Nastaliq — the applicability limit

- Gulzar `exit`: X = `outline.left` with zero bias (71 %, zero spread),
  Y = baseline (99 %) — every word lands on the baseline. `entry` X reaches
  80 % with a small ruleset, but **`entry` Y is 32 %**: the pen-entry height
  of the cascade is chosen per glyph.
- Gulzar's nuqta rows are bands exactly 200 units apart (box.top−7 / +193 /
  +393, mirrored below) — derived anchors again.
- Verdict: draft placement + manual finishing (studio); full automation is
  not realistic, and that matches how these fonts are made.

### Hebrew, Thai/Khmer/Myanmar, Tibetan — good to very good

- Hebrew: niqqud centres on the box (`box*1/2`, 72–93 %); heights are three
  constant bands (baseline / 528 / 714 at UPM 1000); shin/sin dots at
  `width.right−20` (91 %).
- Thai: zero-width marks sit at constant offsets left of the origin
  (x ≈ −90); top anchors on a constant band (536); anyX 83–86 %.
- Tibetan: the heaviest mkmk font of the corpus (11.5k anchors, 1,525
  Mark2 records) still yields anyX 90 %; stacking rides on the carrier
  glyph's `box.bottom`/`box.top`.

### CJK — empirically not applicable (and that's fine)

Source Han Sans and Noto Sans KR contain GPOS anchors on **54 glyphs** only
(134 base records, features `mark`/`vert`): kana and Hangul-adjacent
combining marks on a modular grid (`width.left+960`, `baseline+600`, …),
trivially expressible at 96–100 %. Han ideographs and precomposed Hangul use
no attachment anchors at all. AnchorsFactory is simply not needed for CJK —
a property of the writing system, not a gap in the tool.

## End-to-end proof of concept

An 8-line rules file, run through the real engine (`apply_document`) on Anek
Devanagari Medium (804 anchored glyphs, 3,106 comparable anchors):

```
# only glyph-relative expressions; a single `*` selector
&hl = capHeight-40
&stemh = 100
* = top (outline.right-298 box.top-31),
    bottom (outline.last.center@&stemh outline.bottom+23),
    bottom2 (outline.last.center@&stemh-7 outline.bottom+23),
    bottom3 (outline.right@&stemh baseline+23),
    bottom5 (outline.last.center@&stemh outline.bottom+42),
    _top (outline.center@bottom &hl),
    _bottom (width.left-265 baseline+23)
```

| Anchor | Hits | Accuracy (tol 10 units) |
|---|--:|--:|
| bottom5 | 419 / 488 | 86% |
| _bottom | 11 / 14 | 79% |
| bottom2 | 423 / 553 | 76% |
| bottom3 | 378 / 564 | 67% |
| bottom | 445 / 676 | 66% |
| top | 402 / 738 | 54% |
| _top | 19 / 73 | 26% |
| **Total** | **2,097 / 3,106** | **68%** |

The candidate analysis puts the ceiling with refined per-class selectors at
~85 % X / 93 % Y.

## Cross-master portability

Rules fitted on Regular were checked against Bold (Scheherazade) and
ExtraBold (Anek): **the rule structure transfers; the numeric bias drifts
with weight** (clearances grow as ink thickens: −247→−265, +23→+37). Strict
candidate+bias transfer passes for 11/40 and 12/22 axis rules, but the
winning candidate is almost always the same. This is exactly the scenario the
existing mechanism covers: a family file plus a three-line master file of
`!extends family.anchors` and re-tuned `&gap` variables.

## Engine notes {#engine-notes}

Two behaviors surfaced by the POC, worth addressing:

1. **Axis cycle for the most common Indic idiom.** "Stem centre on X × ink
   bottom on Y" is rejected (both axes outline-sampled, no `@`) — correctly,
   but this is the single most frequent combination in Indic rules; the docs
   and the studio should teach the `@&stemh` form.
2. **Exact-edge sampling grazes.** `@top`/`@bottom` sample the contour at
   exactly the bbox edge, where the scanline is tangent to a smooth peak; the
   battery's hair-inside samples (edge ∓ 2 units) performed markedly better
   (`_top`: 26 % in-engine vs ~60 % expected). An ε-inset option would close
   the gap.

## Recommendations

Priority order, with the evidence that motivates each. RFCs live in
`docs/proposals/`.

1. **P1 — Derived anchors** (anchor = another anchor + offset). Evidence:
   Anek stacking levels with zero spread over ~550 glyphs; Gulzar ±200
   bands; `_bottom/_bottom2` pairs in Noto Devanagari. Collapses hundreds of
   anchors into one line and makes mkmk chains declarative.
2. **P1 — Component anchor propagation** (`!propagate`). Composites without
   own contours inherit components' anchors (transformed) as defaults; rules
   and manual anchors override. Covers 76 % of composite anchors in Noto
   Devanagari, ~38 % even in hand-tuned Scheherazade; the big win is the
   hundreds of "letter + dots" composites in Arabic.
3. **P1 — Per-component frames** for ligature anchors
   (e.g. geometry of the *i*-th component for lam-alef's `diaA_1`/`diaA_2`;
   `MarkLigPos` is a standard part of Arabic mark positioning).
4. **P2 — ε-inset edge sampling** for `@top`/`@bottom` (see engine notes).
5. **P2 — Cursive preset for Arabic**: `entry`/`exit` are ordinary anchor
   names and already placeable; ship a documented preset
   (`exit (outline.left@baseline baseline)` etc.) and note that nastaliq's
   cascade Y stays per-glyph.
6. **P2 — Document the stem × ink-bottom idiom** (axis-cycle guidance).
7. **P3 — Script starter presets** (`devanagari`, `hebrew`, `thai`) at the
   quality bar of the current `default`.
8. **P3 — Script/Unicode-block selector** (`{script:Deva}`) — convenience;
   U+ ranges and globs already cover the need.

## Limitations

- The 0.5 % UPM tolerance is conservative; at 1 % the numbers rise by 5–10
  points.
- Grouping by anchor name mixes heterogeneous glyph classes — `best` is
  pessimistic; `any` is closer to practice but ignores the cost of writing
  selectors.
- Binaries: class names synthesized per lookup (slight over-split);
  variable fonts read at the default instance.
- Awami's UFO anchors only partially map to mark/mkmk semantics (Graphite).
- No confidential fonts were used; the whole corpus is OFL
  (SIL, Ek Type, Noto, Amiri, Gulzar, Source Han).
