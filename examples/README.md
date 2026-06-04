# examples / legacy material

Reference material kept for migration; **not** part of the installed package.

- `*.txt` — the original rule files in the legacy format. Convert any of them
  to the current `.af` syntax with:

  ```
  anchorsfactory-convert examples/default-anchors-list.txt -o my-rules.af
  ```

  (The conversion is verified lossless.) `afii_to_GLapp.txt` is a glyph-name
  mapping table, not a rule file.

- `legacy/` — the original module-level script (`tdAnchorsFactory.py`) and its
  batch driver (`batch.py`), superseded by the `anchorsfactory` package and the
  `anchorsfactory` command. Retained for reference only.

The maintained defaults now ship inside the package as presets
(`anchorsfactory/rules/default.af`, `default-italics.af`), usable by name:
`--rules default` or `!extends default`.
