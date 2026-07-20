# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AnchorsFactory places **anchors** in UFO fonts from a text rule file: anchors
are the attachment points used for mark positioning. It computes each anchor's
coordinates from the glyph's own geometry (advance, bounding box, or contour
intersection) and writes them into the font. It is the *pre-marking* half of a
pipeline whose second half (composite assembly by snapping mark anchors to base
anchors) is done by GlyphConstruction.

The rewrite is complete and released to PyPI (currently **v0.4.1**); the package
is `anchorsfactory/`. The WS1 world-scripts features (`%name` derived anchors,
`!propagate`, `compN.` frames) are **committed on `master` but unreleased** —
they make up the pending **v0.5.0**, together with that release's boundary
change: **the distribution is the engine + CLI + vendored GlyphConstruction
only**. Rule sets (`examples/rules/`) and the Studio (`anchorsfactory/studio/`,
importable from a checkout, absent from the wheel) are repository material. The
original module script lives in `examples/legacy/` for reference only.

## Environment & commands

Dependencies are not in the system Python — use the project-local `.venv`
(managed with **uv**).

```bash
make venv                           # create .venv, install package + dev deps
make test                           # run the test suite
make build                          # build sdist + wheel (uv build) into dist/
# equivalently, by hand:
.venv/bin/python -m pytest
.venv/bin/python -m anchorsfactory <ufo> --rules default        # run the CLI
.venv/bin/python -m anchorsfactory.convert <legacy.txt>         # convert old rules
```

**uv gotcha:** if an unrelated `$VIRTUAL_ENV` is exported, `uv pip install`
targets that env; prefix manual installs with `VIRTUAL_ENV="$(pwd)/.venv"`.

No real font ships with the repo; see "test fonts" below.

## Architecture

The pipeline is `parse → validate → resolve geometry → apply → save`, split so
each layer is testable and the DSL surface is decoupled from the engine.

- `model.py` — the IR (the parser/engine contract). One `frame.position` node
  `Pos(frame, align, run, at, axis, component)` serves **both axes**:
  `Frame{ADVANCE,BOX,OUTLINE}` with `align` an `HAlign` (X) / `VEdge` (Y) /
  `Frac` (a `*n/m` position); `Run` (which ink span/stem); `component` (a
  `compN.`/`complast.` per-component qualifier, 1-based / -1). Plus `Centroid`
  (area centre of mass, polymorphic, also `component`), `Abs` (absolute,
  axis-neutral), `AnchorRef` (`%name`, another anchor's position — polymorphic),
  `EdgeOffset` (`@top-10`, an own bbox edge ± offset, as a `Pos.at` sample line),
  `Sum`/`Neg` (`+`/`-` arithmetic), `FontMetric`, `Y` (`$glyph`). Selectors
  `GlyphName/Unicode/UnicodeRange/Glob/Category`; `Op{REPLACE,ADD,REMOVE}`;
  `LabelRef`, `VarRef` (`&name`, a named axis expression); `Document` (incl.
  `propagate` mode). (`X`, `XAbs`/`YAbs`, `YSum` remain as back-compat aliases of
  `Pos`/`Abs`/`Sum`.) Dataclass `__str__`s render canonical DSL tokens (so they
  double as the serializer).
- `geometry.py` — resolves an `AnchorSpec` to (x, y). **Analytic** contour
  intersection via `fontTools.misc.bezierTools` (not a pixel scan) on a scanline
  perpendicular to the axis (horizontal for X, vertical for Y); pairs crossings
  into stems, samples at exactly the requested position (no inset/nudge). Resolves
  the two axes in dependency order (an `outline` position with no `@` samples on
  the other axis's coordinate; both at once = an axis cycle, rejected). Italic
  shear is **height-aware**: every X is projected along `italicAngle` from the
  height it was measured at to the anchor's height (`tan(-angle)·(Y−S)`; `S=0`
  for box/advance, the `@`/anchor height for outline, `cy` for centroid). Also
  `Centroid` (via `StatisticsPen`) and `Frac` positions. `@` decouples the sample
  line (a height on X, a column on Y) from the anchor's other coordinate. A
  `compN.` qualifier draws only the N-th component into a fresh recorder
  (`DecomposingRecordingPen` flattens components, so post-hoc filtering is
  impossible) and scopes crossings/bbox/centroid/`@`-edges to it.
  `glyph.bounds` is the bbox of the *already-slanted* outline, so on X a `box.*`
  position measures `_deslanted_bounds` instead (the outline sheared back
  upright) — that makes it a true `S=0` reference for **any** shape, not just a
  parallelogram: a slanted `V`'s box extremes sit at the top and an `A`'s at the
  bottom, so measuring the raw box put them ±82 units apart on a 13° face though
  both are drawn on one centre. Y edges and all `outline.*` sampling keep the
  real bbox. Documented in `docs/anchor-rules.md`.
- `parser.py` — legacy `.txt` → IR. `dsl.py` — the new language → IR. Both
  produce a `Document`; the engine never sees surface syntax.
- `apply.py` — the **accumulation model**: rules scanned in order, each matching
  selector mutates a glyph's anchor list (`=` replace, `+=` add, `-=` remove);
  labels and `&`-variables resolved late (with axis/undefined/variable-cycle and
  both-axes-outline axis-cycle checks). Plus `accumulate`, `validate_document`
  (pre-flight). `!propagate` seeds a glyph's accumulator from its components via
  `propagate_seed`/`_effective_anchors` (memoized, topo, cycle-guarded);
  `%name` refs resolve in `_resolve_specs` in dependency order (above geometry —
  the ref's computed coordinate is substituted before `resolve`).
- `runner.py` — file IO + `!extends` resolution/merge; safe-save default
  (`*_anchored.ufo`, never overwrites unless `--in-place`). `cli.py` — the
  `anchorsfactory` command; loads+validates rules once, then per-font.
- `convert.py` — legacy → new DSL, with a lossless round-trip check.
- `presets.py` — resolves a **bare set name** (`--rules`/`!extends`) against a
  search path: the referencing file's own directory, then explicit
  `search_paths=`, then the process-wide list (`set_search_paths` /
  `$ANCHORSFACTORY_RULES_PATH`). **No rule sets ship in the wheel** — the samples
  live in `examples/rules/` and the host owns its own library.
- `vocabulary.py` — the DSL's surface words (frames/aligns/runs/metrics/
  directives/sigils) as public data, derived from the IR enums; `dsl.py` builds
  its tables *from it*, so an editor's completion cannot drift from the parser.
  Axis-aware helpers: `completions_after_dot(head, axis)`,
  `completions_for_slot(axis)`, `as_dict()` for non-Python clients.

## Rule language

See `docs/anchor-rules.md` (full spec) and `README.md`. Key points: an anchor is
`name (X Y)`, and one `frame.position` grammar serves **both axes** —
`width/box/outline . [run] . align [@…]`, with `align` = `left/center/right` (X)
/ `bottom/middle/top` (Y) / a `*n/m` fraction. `outline.*` samples the contour
(on X at a height, on Y at a column); `@…` fixes that sample line (`@top-10` =
an own-edge inset); `box.top` reads the glyph's own bbox; `outline.centroid` is
the area centre. Y also takes
a number, a font metric (`capHeight`, …), or `$Glyph[.edge|*frac]`. Terms
combine with `+`/`-` (a base position plus a bias, e.g. `outline.centroid-25`).
`&name` aliases any X/Y expression (late-bound, axis-checked); `%name` is another
anchor's position on the same glyph (`bottom (%top 0)`); `compN.`/`complast.`
scopes a frame to one component; operators `=`/`+=`/`-=`; selectors include
ranges/globs/categories; `!extends` inherits a base; `!propagate` makes
composites inherit component anchors. Italic shear is automatic (height-aware).

## Conventions

- **Test fonts in `ufo-test/` are confidential and gitignored.** Never write
  their filenames into commits, code, docs, or any tracked file; refer to them
  generically. `ufo-test/` and `*.ufo` stay in `.gitignore`. (Some fonts there
  carry proprietary licenses, not OFL — also not redistributable / bundleable.)
- **Never run the CLI directly on `ufo-test/` originals** without `--output`/a
  copy — the tool can overwrite in place. Process copies in `/tmp`.
- `dev/` (gitignored) holds local golden baselines (`dev/golden/font*.anchors.txt`,
  from confidential fonts) and validation scripts (`golden_diff.py`,
  `check_numbers.py`, `validate_dsl.py`). Re-run after engine changes; verify
  rule changes against the golden / via per-glyph `accumulate` equivalence.
- No font ships in the wheel; the golden tests glob `ufo-test/` and skip if
  absent, so the public suite needs no fixture.
