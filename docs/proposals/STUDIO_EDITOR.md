# Studio editor on CodeMirror 6

**Status: plan (2026-10-11).** Not started.

**Goal.** Replace the Studio's textarea editors (anchor rules and
constructions, every tab) with CodeMirror 6, in the local and the web Studio
alike, without changing what the rest of the page sees.

## Why

The current editor (`makeEditor` in `static/app.js`) is a `<textarea>` under
a highlighted `<pre>` overlay with a hand-made gutter and completion popup.
It works, but:

- **Undo breaks.** `setValue` and accepting a completion assign `ta.value`,
  which wipes the browser's undo stack; Ctrl+Z after a completion does not
  return the typed text.
- **Every keystroke re-renders the whole file**: the overlay and the gutter
  are rebuilt as HTML for all lines. A long rules file (thousands of lines
  with `!if` blocks) makes typing lag.
- **The overlay must follow the textarea** by measured character width and
  line height (`CHAR_W`, `LH`, `PAD`); scroll and font-size changes have
  already caused off-by-half-a-line bugs.
- Missing everyday features: bracket matching for `( )`, comment toggle,
  multiple selections, a search with replace, folding of `!if` blocks.

## Constraints

1. **One page source.** The page lives in `anchorsfactory/studio/static/`;
   `web/` imports it. The editor must come from there for both Studios.
2. **The local Studio needs no Node.** `server.py` serves `static/` as it is,
   and `app.js` is a classic script there (a module only inside Vite).
3. **CSP** `script-src 'self'` on the site; the service worker caches what
   the page loads, so the editor must be a same-origin file.
4. **The vocabulary stays server-side.** Highlighting and completion keep
   reading `META.vocabulary` (from `anchorsfactory.vocabulary`), so the
   editor cannot drift from the parser.
5. The rest of `app.js` talks to an editor only through `makeEditor`'s
   object: `getValue`, `setValue`, `refresh`, `markErrors`, `markInactive`,
   `gotoLine`, `focus`, and `.ta` (used by the find bar).

## Design

### A vendored bundle

`web/editor/` gets a small entry (`cm.ts`) that imports the CodeMirror
packages the Studio uses and exposes them as one global, `window.CM`
(`EditorView`, `EditorState`, `StreamLanguage`, `autocompletion`, `history`,
`search`, …). A script (`npm run editor`, esbuild or Vite library mode, IIFE
output) builds it into **`static/vendor/codemirror.js`**, which is committed
with its license (`static/vendor/LICENSE-codemirror`, MIT) and the pinned
versions in `web/package-lock.json`.

- The local Studio loads it with a plain `<script>` before `app.js`; `web/`
  imports the same file, so there is still one copy.
- Rebuilding is needed only when the CodeMirror versions change; `ci.yml`
  rebuilds it and fails if the committed file differs.
- Expected size: roughly 150–250 KB minified (about 60–80 KB gzipped) for
  view, state, language, autocomplete, search and commands. Measured in
  step 1; the budget is 300 KB.

### `makeEditor` keeps its interface

`makeEditor(host, onChange, onFocus, highlight, complete)` returns the same
object, backed by an `EditorView`:

| Today | With CodeMirror |
|---|---|
| `getValue` / `setValue` | `view.state.doc.toString()` / one transaction that replaces the document and **keeps history** (a reload from disk is undoable) |
| `markErrors(set)` / `markInactive(set)` | a `StateField` of line decorations (`.err`, `.off`) plus gutter markers |
| `gotoLine(n)` | select the line, `scrollIntoView` centred, the existing flash |
| `refresh` | no-op (decorations update by themselves) |
| `.ta` | removed; the find bar uses the view (see below) |
| `onChange` | an `updateListener` on `docChanged` |

### Language

- **Highlighting.** A `StreamLanguage` tokenizer per language (anchors,
  constructions), written from the token rules `highlightLine` /
  `highlightGC` / `highlightCond` use now (selectors, `@labels`,
  `&variables`, `%refs`, frames and aligns from the vocabulary, numbers,
  operators, `!directives`, `#` comments). The CSS classes map to the
  current colours through a `HighlightStyle` on the page's CSS variables, so
  light and dark themes stay as they are.
- **Completion.** One `CompletionSource` that builds the existing context
  (`{word, head, seg, axis, line}` with the X/Y slot detection) and calls
  `ANCHOR_COMPLETE` / `GC_COMPLETE` unchanged. The providers and their
  ordering stay; CodeMirror only draws the popup.
- **Comments.** `languageData` with `commentTokens: {line: "#"}`, so Ctrl+/
  toggles comments.
- **Brackets.** `bracketMatching` and `closeBrackets` for `( )`.

### Find

Use `@codemirror/search` (Ctrl+F, next/previous, replace, regex) in place of
the Studio's own find bar, styled to match. This removes the last `.ta` use.

### Later (not in the first step)

- Error messages as lint diagnostics (squiggle and tooltip). The engine
  reports lines only; columns would need the parser to keep token offsets.
- Folding `!if … !endif` blocks.
- Hover on a selector or a `%ref`: the glyphs it matches.

## Steps

1. **Bundle.** `web/editor/cm.ts`, the build script, the committed
   `static/vendor/codemirror.js` + license; load it in `index.html` and from
   `web/src/main.ts`. Check its size and that the CSP and the service worker
   accept it.
2. **Editor swap.** `makeEditor` on `EditorView` with the table above;
   highlighting as a first `StreamLanguage`; remove the overlay, the gutter
   and `CHAR_W`/`LH`/`PAD`.
3. **Completion, comments, brackets.**
4. **Find** with `@codemirror/search`; drop the old find bar.
5. **Tests and docs.** `tests/test_studio_ui.py` types into `.cm-content`
   instead of the textarea (a small helper); new checks: undo after a
   completion, `gotoLine` from a problem, `!if` lines dimmed, Ctrl+/.
   `docs/studio.md` (editor keys), CHANGELOG, CLAUDE.md.

Each step leaves both Studios working; steps 2–4 can be one commit.

## Open questions

1. **The committed bundle.** A minified file in the repository is the price
   of a Node-free local Studio. The alternative is to build it in
   `make venv`, which makes Node a requirement of the local Studio.
2. **Find bar.** CodeMirror's search panel (replace, regex; looks different)
   or keep the current bar, reimplemented over the view.
3. **Vim / Emacs keymaps**, line wrapping, font size: needed?
