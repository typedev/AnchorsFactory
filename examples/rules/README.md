# Sample rule sets

**Nothing here ships with the package.** Rule sets are data, and data belongs to
whoever runs the tool: bundled, they sat in `site-packages` where a user could
not edit them, and a change of *data* rode out on a version of *code*. So the
library carries the engine and a resolver, and these are samples — copy them,
edit them, keep them under your own version control.

Use one by path, or by name once a search path points here:

```bash
anchorsfactory MyFont.ufo --rules examples/rules/latin-ext-additional.anchors
anchorsfactory MyFont.ufo --rules-path examples/rules --rules default
export ANCHORSFACTORY_RULES_PATH=examples/rules      # or via the environment
```

A bare name in `!extends` is looked up in the referencing file's **own
directory** first, which is why `default-italics.anchors` can say
`!extends default` and find its neighbour with nothing configured at all.

In the Studio a set loads either as a **layer** (open / drop the file) or, if
its name is on the Studio's search path, via `!extends` — the Studio still
rejects `!extends <path>`. `make studio` points that path here.

| File | What it covers |
| --- | --- |
| `default.*` | **Latin core** — Basic Latin, Latin-1 Supplement, Latin Extended-A. The set to start from |
| `default-italics.anchors` | The italic overlay: `!extends default` plus the eight rules a slanted *drawing* actually changes (the shear itself is automatic) |
| `latin-ext-b.*` | Latin Extended-B (U+0180–U+024F) — the composites of that block, plus the `horn` anchors Vietnamese `ơ`/`ư` need |
| `latin-ext-additional.*` | Latin Extended Additional (U+1E00–U+1EFF) — Vietnamese and the dot-below accents |
| `devanagari.anchors` | Devanagari — above/below/head-line mark seats |
| `hebrew.anchors` | Hebrew — niqqud below the base, dagesh inside it |
| `thai.anchors` | Thai — the above/below stack over the loop-and-ascender skeleton |
| `legacy-default.anchors` | The pre-generation `default` ruleset, kept for reference: Latin **and** Cyrillic, plus foundry-specific component marks addressed by name |
| `legacy-basic.glyphsConstruction` | The matching pre-generation construction list (name-addressed) |
| `legacy-default-italics.anchors` | The pre-0.5.0 italic ruleset, a full standalone copy of the upright one. Superseded by `default-italics` |

Each Latin set comes in two halves meant to be used together: `.anchors` places
the anchors, `.glyphsConstruction` assembles the composites that hang off them.

The `default`/`latin-*` sets are **generated** from the Unicode database by a
maintainer-side script (`dev/gen_latin_rules.py`, not part of the repository) —
do not hand-edit them; layer your own rules on top instead. The `legacy-*` files
are historical and are not regenerated.

An extension set covers only its own block: the bases it builds on (`ê` for the
Vietnamese stack) get their `top`/`bottom` from `default`, so load it under
these — the accumulation model means later rules add to earlier ones.
