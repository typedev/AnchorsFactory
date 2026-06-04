# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AnchorsFactory places **anchors** in UFO fonts from a text rule file: anchors
are the attachment points used for mark positioning. It computes each anchor's
coordinates from the glyph's own geometry (advance, bounding box, or contour
intersection) and writes them into the font. It is the *pre-marking* half of a
pipeline whose second half (composite assembly by snapping mark anchors to base
anchors) is done by GlyphConstruction.

The codebase is mid-rewrite on the **`refactor`** branch toward a PyPI release;
the new code is the `anchorsfactory/` package. The original module script lives
in `examples/legacy/` for reference only.

## Environment & commands

Dependencies are not in the system Python — use the project-local `.venv`
(managed with **uv**).

```bash
uv venv --python 3.12
VIRTUAL_ENV="$(pwd)/.venv" uv pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest          # tests
.venv/bin/python -m anchorsfactory <ufo> --rules default        # run the CLI
.venv/bin/python -m anchorsfactory.convert <legacy.txt>         # convert old rules
```

**uv gotcha:** if an unrelated `$VIRTUAL_ENV` is exported, `uv pip install`
targets that env; prefix installs with `VIRTUAL_ENV="$(pwd)/.venv"`.

No real font ships with the repo; see "test fonts" below.

## Architecture

The pipeline is `parse → validate → resolve geometry → apply → save`, split so
each layer is testable and the DSL surface is decoupled from the engine.

- `model.py` — the IR (the parser/engine contract). `frame.position` vocabulary:
  `Frame{ADVANCE,BOX,OUTLINE}`×`HAlign`, `Run` (which ink span/stem), `VEdge`,
  `Frac`, `FontMetric`; selectors `GlyphName/Unicode/UnicodeRange/Glob/Category`;
  `Op{REPLACE,ADD,REMOVE}`; `LabelRef`; `Document`. Dataclass `__str__`s render
  canonical DSL tokens (so they double as the serializer).
- `geometry.py` — resolves an `AnchorSpec` to (x, y). **Analytic** contour
  intersection via `fontTools.misc.bezierTools` (not a pixel scan); decomposes
  components, pairs crossings into stems, applies italic shift, insets 1u from
  horizontal extremes. Reads `font.info` for metrics.
- `parser.py` — legacy `.txt` → IR. `dsl.py` — the new language → IR. Both
  produce a `Document`; the engine never sees surface syntax.
- `apply.py` — the **accumulation model**: rules scanned in order, each matching
  selector mutates a glyph's anchor list (`=` replace, `+=` add, `-=` remove);
  labels resolved late. Plus `accumulate`, `validate_document` (pre-flight).
- `runner.py` — file IO + `!extends` resolution/merge; safe-save default
  (`*_anchored.ufo`, never overwrites unless `--in-place`). `cli.py` — the
  `anchorsfactory` command; loads+validates rules once, then per-font.
- `convert.py` — legacy → new DSL, with a lossless round-trip check.
- `presets.py` + `rules/*.af` — bundled `default`/`default-italics`, read via
  `importlib.resources`, referenced by bare name in `--rules`/`!extends`.

## Rule language

See `docs/DSL.md` (full spec) and `README.md`. Key points: an anchor is
`name (X Y)`; X is `width/box/outline . [run] . align [@edge]`; Y is a number, a
font metric keyword (`capHeight`, `xHeight`, …), or `$Glyph[.edge|*frac]`;
selectors include ranges/globs/categories; `!extends` inherits a base.

## Conventions

- **Test fonts in `ufo-test/` are confidential and gitignored.** Never write
  their filenames into commits, code, docs, or any tracked file; refer to them
  generically. `ufo-test/` and `*.ufo` stay in `.gitignore`.
- **Never run the CLI directly on `ufo-test/` originals** without `--output`/a
  copy — the tool can overwrite in place. Process copies in `/tmp`.
- `dev/` (gitignored) holds local golden baselines (`dev/golden/font*.anchors.txt`,
  from confidential fonts) and validation scripts (`golden_diff.py`,
  `check_numbers.py`, `validate_dsl.py`). The golden harness asserts the engine
  reproduces the legacy output bar intended fixes — run it after engine changes.
- Validate rule changes against the golden / via per-glyph `accumulate`
  equivalence before committing.
