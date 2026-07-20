# examples

**Not** part of the installed package — the repository's sample material.

- `rules/` — the **sample rule sets** (`default`, `default-italics`,
  `latin-ext-*`, `devanagari`, `hebrew`, `thai`, and the pre-0.5.0 `legacy-*`).
  No rule sets ship with the wheel; these are the ones to copy and make your
  own. See [`rules/README.md`](rules/README.md).

- `*.txt` — the original rule files in the legacy format. Convert any of them
  to the current `.anchors` syntax with:

  ```
  anchorsfactory-convert examples/default-anchors-list.txt -o my-rules.anchors
  ```

  (The conversion is verified lossless.) `afii_to_GLapp.txt` is a glyph-name
  mapping table, not a rule file.

- `legacy/` — the original module-level script (`tdAnchorsFactory.py`) and its
  batch driver (`batch.py`), superseded by the `anchorsfactory` package and the
  `anchorsfactory` command. Retained for reference only.

The maintained sets live in [`rules/`](rules/) — usable by path
(`--rules examples/rules/default.anchors`) or by name once a search path points
at them (`--rules-path examples/rules --rules default`).
