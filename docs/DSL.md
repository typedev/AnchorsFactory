# AnchorsFactory rule language

A line-oriented, low-noise language for placing anchors in UFO fonts. It is
**stacked**: you define reusable *labels* once, then *mark* glyphs with them —
mixing labels and one-off anchors freely on a single line.

Every rule parses into the internal representation (`anchorsfactory.model`),
which the geometry engine consumes. The surface syntax below is one front-end;
the engine never sees it.

## Lexical

- One rule per line. Blank lines are ignored.
- `#` starts a comment (to end of line). `;` separates two rules on one line.
- Tokens are whitespace-insensitive except inside an anchor's `( … )` group,
  where a single space separates the X and Y positions.

Sigils at a glance:

| sigil | meaning |
|-------|---------|
| `@name` | label — define or reference |
| `!name` | directive (pragma) |
| `#` | comment |
| `name ( X Y )` | an anchor placement |
| `,` | separates anchors / labels in a list |
| `=` `+=` `-=` | replace / add / remove anchors |

## Anchor placement: `name ( X Y )`

An anchor is a point. It is written as the anchor name followed by a
parenthesised **X Y** pair:

```
top (box.center $H)
```

The parentheses group the placement explicitly (clear boundaries, a safe home
for the X–Y space, and room to grow extra parameters later without breaking
the grammar).

### X — horizontal position (`frame.position`)

| token | meaning |
|-------|---------|
| `width.left` / `width.center` / `width.right` | advance width: origin `0` / `width/2` / `width` |
| `box.left` / `box.center` / `box.right` | bounding box: `xMin` / centre / `xMax` |
| `outline.left` / `outline.right` | left/rightmost contour crossing at the height Y |
| `outline.center` | centre of the whole ink envelope at Y |
| `outline.first.center` / `outline.last.center` | centre of the first / last ink span (stem) |
| `outline.N.center` | centre of the N-th span, 1-based (for `m`, `ш`, `Ш`, …) |
| `outline.center@top` / `outline.center@bottom` | centre of ink at the glyph's own top / bottom edge |
| `<number>` | absolute X in font units |

`outline.*` measures where the ink actually is at height Y. Crossings pair into
spans (stems); `.first` / `.last` / `.N` pick one, otherwise the whole envelope
is used.

### Y — vertical position

| token | meaning |
|-------|---------|
| `$G` | top of glyph G's bounding box |
| `$G.bottom` | bottom of G's box |
| `$G.middle` | vertical middle of G's box |
| `$G*d1/d2` | fraction of G's height, from the baseline (e.g. `$H*5/6`) |
| `ascender` `descender` `capHeight` `xHeight` `unitsPerEm` `baseline` | a font-wide vertical metric from `font.info` (`baseline` = 0) |
| `capHeight*2/3` | a fraction of a metric |
| `<number>` | absolute Y in font units |

Font metrics are bare keywords (no `$`), so they never collide with glyph
references; they don't depend on any particular glyph being present.

## Labels

A label names a reusable list of anchors:

```
@      = top (box.center $H), bottom (box.center 0)
@desc  = desc (outline.right 0)
@bar   = bar (width.center $H*1/2)
@_     = _top (outline.center@bottom $H)
```

Reference labels (and mix with inline anchors) when marking a glyph:

```
A = @, @ogonek
L = @bot, top (box.left $H), caron (box.right $H)
t = @, barlow (width.center $x*2/3)
```

## Selectors — what a rule applies to

The left-hand side of a rule selects glyphs:

| selector | matches |
|----------|---------|
| `A` | the glyph named `A` |
| `U+0413` | the glyph mapped from code point U+0413 |
| `U+0410..U+044F` | every glyph in the (inclusive) code-point range |
| `*.sc` | glyph names by glob (`*`, `?`) |
| `{Lu}` | glyphs whose Unicode general category is `Lu` |

A range/glob/category lets one line stand in for the dozens of identical
`U+XXXX = @` lines a real font otherwise needs.

## Operators and the accumulation model

Rules are processed **in file order**. For each glyph, an accumulator (an
ordered anchor list, initially empty) is built by every rule whose selector
matches it:

- `selector  = …`  → **replace**: discard the accumulator, set it to `…`
- `selector += …`  → **add**: append `…` to the accumulator
- `selector -= a, b, @label` → **remove**: drop accumulated anchors by name
  (a bare name, or every name a label contributes)

The accumulator after the last matching rule is what gets placed. If two
anchors share a name, the later one wins (the placement engine keeps the last).
A glyph matched by no rule is left untouched.

Labels are **late-bound**: a `@label` in a rule is resolved against the final
label table, so redefining a label affects rules written before it too. This
is what makes inheritance work — a file may extend defaults and override a
shared label once.

> ⚠️ `=` is a *hard reset*. A later `=` on a glyph already covered by a range
> default wipes everything that range gave it — intentional, but mind the order.

Idiom: **broad defaults first, specific exceptions after.**

```
U+0410..U+044F = @                  # А..я all get top + bottom
U+0413        += @desc, @bar        # Г → [@, @desc, @bar]
U+0413        += @bar.alt, @_desc   # Г → [@, @desc, @bar, @bar.alt, @_desc]
U+0418        += @desc, @hook       # И → [@, @desc, @hook]
```

versus a hard reset:

```
U+0410..U+044F = @
U+0413         = bar (width.center $H)   # Г → [bar(…)] only — the @ default is dropped
```

## Directives

```
!extends  default         # inherit a base ruleset, then layer this file on top
!suffixes = .alt, .sc     # also place every rule on base+suffix glyph variants
!shiftx   = -15           # add a constant X offset to every placed anchor
```

`!extends` takes a **bundled preset name** (`default`, `default-italics` — no
extension/separator) or a **path** resolved relative to the file containing the
directive (absolute paths allowed but discouraged). Multiple `!extends` layer
in order, then this file's own rules apply last; cycles are rejected. This is
the inheritance model: ship a big standalone file, or `!extends default` plus a
small set of `+=` / `-=` / `=` adjustments.

```
!extends default
U+0413 += hook (outline.right 0)   # Г: defaults plus a hook
A      -= ogonek                   # A: defaults minus the ogonek anchor
O       = top (box.center $H)       # O: replace entirely
```

## A complete example

```
# --- labels ---
@      = top (box.center $H), bottom (box.center 0)
@desc  = desc (outline.right 0)
@bar   = bar (width.center $H*1/2)
@hook  = hook (outline.right 0)
@ogonek = ogonek (outline.right 0)

# --- Latin ---
A = @, @ogonek
H = @, @hook, @desc, @bar
L = @bot, top (box.left $H), caron (box.right $H)

# --- Cyrillic: one default + exceptions ---
U+0410..U+044F = @
U+0401 = @ ; U+0451 = @
U+0413 += @desc, @bar
U+0418 += @desc, @hook
U+0447 += @desc, @hook

# --- accents (marks carry _ anchors) ---
acute = @_
grave = @_
```

## Migration from the legacy `.txt` format

The old `name:align:vert` triples map mechanically:

| legacy | new |
|--------|-----|
| `top:centerpos:$H` | `top (box.center $H)` |
| `bar:center:$H*1/2` | `bar (width.center $H*1/2)` |
| `desc:rightinter:0` | `desc (outline.right 0)` |
| `_top:bottomcenter:$H` | `_top (outline.center@bottom $H)` |
| `$gravecomb_` | `$gravecomb.bottom` |
| `$endash-` | `$endash.middle` |
| `&0413=@` | `U+0413 = @` |
| `@SFXLIST=alt` | `!suffixes = .alt` |

A converter will translate existing rule files automatically.
