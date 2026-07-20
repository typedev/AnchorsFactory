# Presets

Rule sets that live in the repository rather than in the wheel. The package
bundles only `default` (Latin core); everything here is referenced **by path**:

```bash
anchorsfactory MyFont.ufo --rules presets/latin-ext-additional.anchors
```

In the Studio these load as a **layer** (open / drop the file), not via
`!extends` — the Studio deliberately rejects `!extends <path>`.

| File | What it covers |
| --- | --- |
| `latin-ext-b.*` | Latin Extended-B (U+0180–U+024F) — the composites of that block, plus the `horn` anchors Vietnamese `ơ`/`ư` need |
| `latin-ext-additional.*` | Latin Extended Additional (U+1E00–U+1EFF) — Vietnamese and the dot-below accents |
| `legacy-default.anchors` | The pre-generation `default` ruleset, kept for reference: Latin **and** Cyrillic, plus foundry-specific component marks addressed by name |
| `legacy-basic.glyphsConstruction` | The matching pre-generation construction list (name-addressed) |

Each set comes in two halves that are meant to be used together: `.anchors`
places the anchors, `.glyphsConstruction` assembles the composites that hang off
them.

The `latin-*` sets are **generated** from the Unicode database by a
maintainer-side script (`dev/gen_latin_rules.py`, not part of the
repository) — do not hand-edit them; layer your own rules on top instead.
The `legacy-*` files are historical and are not regenerated.

An extension set covers only its own block: the bases it builds on (`ê` for the
Vietnamese stack) get their `top`/`bottom` from `default`, so load it under
these — the accumulation model means later rules add to earlier ones.
