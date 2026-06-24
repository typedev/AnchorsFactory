# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AnchorsFactory places **anchors** in UFO fonts from a text rule file: anchors
are the attachment points used for mark positioning. It computes each anchor's
coordinates from the glyph's own geometry (advance, bounding box, or contour
intersection) and writes them into the font. It is the *pre-marking* half of a
pipeline whose second half (composite assembly by snapping mark anchors to base
anchors) is done by GlyphConstruction.

The rewrite is complete and released to PyPI (currently **v0.4.1**, on
`master`); the package is `anchorsfactory/`. The original module script lives in
`examples/legacy/` for reference only.

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

- `model.py` — the IR (the parser/engine contract). `frame.position` vocabulary:
  `Frame{ADVANCE,BOX,OUTLINE}`×`HAlign`, `Run` (which ink span/stem), `VEdge`,
  `Frac`, `FontMetric`, `YSum` (summed heights); selectors
  `GlyphName/Unicode/UnicodeRange/Glob/Category`; `Op{REPLACE,ADD,REMOVE}`;
  `LabelRef`, `VarRef` (`&name`, a named axis expression); `Document`. Dataclass
  `__str__`s render canonical DSL tokens (so they double as the serializer).
- `geometry.py` — resolves an `AnchorSpec` to (x, y). **Analytic** contour
  intersection via `fontTools.misc.bezierTools` (not a pixel scan); decomposes
  components, pairs crossings into stems, applies italic shift, and samples the
  contour at exactly the requested height (no inset/nudge). Reads `font.info` for
  metrics; `X.at` may sample the contour at a fixed height (metric/number/
  `$glyph`/`&variable`) decoupled from the anchor's Y.
- `parser.py` — legacy `.txt` → IR. `dsl.py` — the new language → IR. Both
  produce a `Document`; the engine never sees surface syntax.
- `apply.py` — the **accumulation model**: rules scanned in order, each matching
  selector mutates a glyph's anchor list (`=` replace, `+=` add, `-=` remove);
  labels and `&`-variables resolved late (with axis/undefined/cycle checks). Plus
  `accumulate`, `validate_document` (pre-flight).
- `runner.py` — file IO + `!extends` resolution/merge; safe-save default
  (`*_anchored.ufo`, never overwrites unless `--in-place`). `cli.py` — the
  `anchorsfactory` command; loads+validates rules once, then per-font.
- `convert.py` — legacy → new DSL, with a lossless round-trip check.
- `presets.py` + `rules/*.af` — bundled `default`/`default-italics`, read via
  `importlib.resources`, referenced by bare name in `--rules`/`!extends`.

## Rule language

See `docs/anchor-rules.md` (full spec) and `README.md`. Key points: an anchor is
`name (X Y)`; X is `width/box/outline . [run] . align [@edge]` where `@edge` is a
glyph extreme (`@top`/`@bottom`) or a fixed sample height (`@xHeight`, `@<n>`);
Y is a number, a font metric keyword (`capHeight`, `xHeight`, …), `$Glyph[.edge|
*frac]`, or a `+`-sum of those (no spaces); a `&name` variable can alias any X/Y
expression (late-bound like a label, with axis checking); operators `=`/`+=`/`-=`;
selectors include ranges/globs/categories; `!extends` inherits a base.

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
