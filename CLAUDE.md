# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AnchorsFactory automatically places **anchors** in UFO fonts according to a text-based rule file. Anchors are the attachment points used for mark positioning (accents/combining marks). One rule can define several anchors at once, and several rules can apply to one glyph. Built on `fontParts` (the defcon/RoboFont object model).

## Environment & commands

Dependencies are NOT in the system Python — use the project-local `.venv` (managed with **uv**).

```bash
# Create env + install deps
uv venv --python 3.12
VIRTUAL_ENV="$(pwd)/.venv" uv pip install -r requirements.txt

# Run on one font (always invoke the venv interpreter explicitly)
.venv/bin/python tdAnchorsFactory.py --ufo ufo-test/<font>.ufo --rules default-anchors-list.txt --output

# Batch over a folder of UFOs (edit the `folder` path in batch.py first)
.venv/bin/python batch.py
```

**uv gotcha:** if an unrelated `$VIRTUAL_ENV` is exported in the shell, `uv pip install` targets *that* env instead of the local `.venv`. Always prefix installs with `VIRTUAL_ENV="$(pwd)/.venv"` to be sure packages land in the project venv.

There is no test framework, linter, or build step — verification is done by running the tool against a real UFO and inspecting the resulting anchors / the log in `logs/`.

### CLI flags (`tdAnchorsFactory.py`)
- `--ufo` path to UFO (default `test/test-font.ufo`, which does **not** exist in the repo — always pass a real path).
- `--rules` path to an anchor-rules file (default `default-anchors-list.txt`).
- `--output` save to `<name>_anchored.ufo` instead of overwriting. **Without `--output` the tool calls `font.save()` and overwrites the input UFO in place** — pass `--output` (or work on a copy) when you don't want the source modified.
- `--save-existing` dumps the font's current anchors to a timestamped `.txt` before applying new ones.

## Architecture

Single class `TDAnchorsFactory` in `tdAnchorsFactory.py`. The pipeline (`run` → `process_anchors_from_file` → `apply_anchors`):

1. **Parse** (`_parse_anchors_rules`) — reads the rules file into `labels` (reusable `@label` definitions), `glyphs` (per-glyph rule references), plus the special `@SFXLIST` (alternate suffixes) and `@SHIFTX` (global X offset) directives.
2. **Resolve** (`_process_anchor_labels`) — expands each glyph's `@label` references into concrete anchor codes; a glyph is skipped entirely if any referenced label is missing.
3. **Place** (`set_glyph_anchor`) — for each anchor code `name:align:Ypos`, computes Y (a number, or derived from a reference glyph's bounds), computes X via `_calculate_anchor_position`, and appends the anchor. Applies to the base glyph and every suffixed variant from `@SFXLIST`.

`batch.py` instantiates `TDAnchorsFactory` once per UFO in a folder and calls `.run()`.

Everything is logged (INFO + errors) to both stdout and a timestamped file in `logs/`.

## Anchor rule DSL

See `README.md` for the full reference. Key points for editing rule files (`default-anchors-list.txt`, `default-anchors-list-italics.txt`, `anchors-list-*.txt`):

- `@Label=anchor:align:Ypos,...` defines a reusable label; `GlyphName=@Label1,@Label2` applies labels to a glyph.
- `&FFFF=@Label` targets a glyph by **Unicode hex** (resolved via the font's cmap) instead of by name.
- `#` starts a comment (inline and full-line).
- **align**: number | `left`/`center`/`right` | `centerpos` (center of bounds) | `leftinter`/`rightinter` (outline intersection at Ypos) | `topcenter`/`bottomcenter` (center of the outline slice at the top/bottom edge).
- **Ypos**: a number, or `$Glyph` (top of a reference glyph's bounds), `$Glyph_` (bottom bound), `$Glyph-` (vertical midpoint), `$Glyph*1/2` etc. (fraction of the reference glyph's height).
- Anchors used by combining marks are prefixed with `_` (e.g. `_top`).

`afii_to_GLapp.txt` and `anchors-list-GLapp.txt` map legacy `afii*` Cyrillic glyph names to GLApp/Unicode names — reference tables, not run inputs.

## Conventions

- **Test fonts in `ufo-test/` are confidential and gitignored.** Never write their filenames into commits, `CLAUDE.md`, the README, code, or any tracked file. Refer to them generically (e.g. "a test UFO"). `ufo-test/` and `*.ufo` must stay in `.gitignore`.
- `logs/` and `*.ufo` are gitignored.
