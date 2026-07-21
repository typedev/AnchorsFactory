# Roadmap: world-scripts era

Derived from the [world-scripts applicability research](../research/world-scripts-applicability.md)
(July 2026). Workstreams are designed to be independently executable — each
lists its dependencies explicitly.

## Workstreams

### WS1 — Language features (RFCs in this directory)

| # | Feature | RFC | Prio | Status |
|---|---------|-----|------|--------|
| 1a | Derived anchors (`%name` term) | [rfc-derived-anchors](rfc-derived-anchors.md) | P1 | ✅ implemented |
| 1b | Component anchor inheritance (`!propagate`) | [rfc-propagate](rfc-propagate.md) | P1 | ✅ implemented |
| 1c | Per-component frames (`compN.`) | [rfc-component-frames](rfc-component-frames.md) | P1 | ✅ implemented |
| 1d | `@` arithmetic / edge insets | [rfc-edge-sampling](rfc-edge-sampling.md) | P2 | ✅ implemented |
| 1e | Cursive preset (`entry`/`exit`) + nastaliq caveats in docs | — (docs + `examples/rules/*.anchors`) | P2 | — |
| 1f | Stem × ink-bottom idiom documentation (axis cycle guidance) | — (docs, studio hint) | P2 | — |
| 1g | Script/Unicode-block selector `{script:…}` | — (needs a mini-RFC if picked up) | P3 | — |

Implementation notes:
- **1a–1c landed** (July 2026) in the designed merge order: 1b (pure seeding, no
  grammar) → 1a (grammar + resolve order) → 1c (grammar + geometry). Each shipped
  with a model node + serializer round-trip test, dsl parser tests, engine tests
  on synthetic glyphs, an `anchor-rules.md` section, and studio provenance
  (propagated / `%ref` badges).
- Release mapping: 1a+1b+1c+1d → **v0.5.0** (released 2026-07-20; v0.5.1
  followed the same day with a packaging fix). Presets and docs ride any release
  (additive).

### WS2 — Studio documentation → `docs/studio.md`

Launch, CLI options, feature walkthrough (layer stack, rule layers: base
preset + custom overrides, provenance), typical debugging workflows,
troubleshooting. No code changes.

### WS3 — User guide → `docs/guide/`

Chapter-per-topic guide with **SVG illustrations generated from real OFL
fonts by the actual engine** (`docs/guide/tools/make_examples.py`): the
example images can never drift from engine behavior. Scripts covered: Latin
(`default`), Cyrillic and Greek (custom rules — `default` is Latin-only now, the
old Latin+Cyrillic set is `examples/rules/legacy-default.anchors`), then
cookbooks for Devanagari, Hebrew, Thai (from the WS4 sample sets) and an Arabic
notes chapter (what automates, what stays per-glyph). Font sources are fetched by script into a gitignored cache;
only curated SVGs are committed. Depends on: WS4 for the script cookbooks;
nothing for the core chapters.

### WS4 — Script starter presets → `examples/rules/{devanagari,hebrew,thai}.anchors` ✅ shipped (v0.5.0)

Written in the *current* syntax (no dependency on WS1), numeric gaps exposed
as `&variables` for per-font retuning via `!extends`. Each ships with a
loading test and an optional accuracy smoke test that skips when the OFL
reference fonts are absent. Delivered as repository samples (no rule sets ship
in the wheel); `devanagari` already uses a `%bottom` derived anchor.

### WS5 — Beyond the research list (proposed additions)

| Idea | What it is | Why |
|------|-----------|-----|
| `anchorsfactory-learn` | Infer draft rules from an already-anchored font: the research battery run in reverse, emitting the best candidate + bias per anchor group as an `.anchors` skeleton | The single biggest adoption lever: every existing font becomes a starting ruleset; ~80 % of the code already exists as the research tooling |
| `--check` mode | Apply rules, diff against the font's existing anchors, exit non-zero over a drift threshold; machine-readable report | Turns AnchorsFactory into a CI guard for anchor regressions; formalizes the `dev/golden_diff.py` workflow |
| Designspace awareness | Apply one family ruleset across all masters of a `.designspace`, with per-master `&var` override files; verify anchor sets are interpolation-compatible (same names everywhere) | The cross-master transfer test showed structure transfers while gaps drift — this is the productized version |
| Feature-writer handoff docs | Document the full pipeline: AnchorsFactory anchors → fontmake/ufo2ft feature writers (mark/mkmk/abvm/blwm/curs) and GlyphConstruction | Users keep asking "then what?"; the naming conventions (`top_1`, `_top`, `entry/exit`) already align — say so explicitly |
| SVG anchor report | Shared rendering core with WS3 tooling: `anchorsfactory --report out.html` renders every anchored glyph with its anchors + provenance | Review without opening a font editor; doubles as guide illustration engine |

## Parallelization map

```
WS2 (studio docs)      — independent, agent-runnable now
WS3 (guide skeleton)   — independent now; cookbooks blocked on WS4
WS4 (presets)          — independent now (current syntax); refresh after WS1
WS1a/1b/1c (RFCs)      — design done; implement in parallel branches,
                          merge order 1b → 1a → 1c
WS5 learn/check        — after WS1 stabilizes the rule vocabulary
```

## Non-goals (from the research)

- **CJK support** — empirically unnecessary (54 anchored glyphs on a modular
  grid in Source Han Sans; Han/Hangul use no attachment anchors).
- **Full nastaliq automation** — `entry` cascade heights are a per-glyph
  design decision; the goal is draft placement + studio finishing, not
  replacement.
