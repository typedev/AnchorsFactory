# AnchorsFactory rule language

A line-oriented, low-noise language for placing anchors in UFO fonts. It is
**stacked**: you define reusable *labels* (named anchor sets) and *variables*
(named X/Y values) once, then *mark* glyphs with them — mixing labels and
one-off anchors freely on a single line.

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
| `@name` | label — define or reference (a list of anchors) |
| `&name` | variable — define or reference (one axis's value) |
| `$Glyph` | reference a glyph's own geometry (in a Y position) |
| `!name` | directive (pragma) |
| `#` | comment |
| `name ( X Y )` | an anchor placement |
| `,` | separates anchors / labels in a list |
| `=` `+=` `-=` | replace / add / remove anchors |

## Anchor placement: `name ( X Y )`

An anchor is a point. It is written as the anchor name followed by a
parenthesised **X Y** pair:

```
top (box.center capHeight)
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
| `outline.center@xHeight` / `@<metric>` / `@<number>` | sample the contour at a fixed height (a font metric, number, `$glyph`, or `&variable`), **decoupled from the anchor's Y** |
| `width*1/3` / `box*2/3` | a **fractional** position along the frame, from the left edge (BOX/ADVANCE only; `center` = `*1/2`) — same `*n/m` as `capHeight*2/3` |
| `outline.centroid` | the **area centre of mass** — the glyph's optical centre (the x of it here); see [Centroid](#centroid) |
| `<number>` | absolute X in font units (integer) |
| `&name` | a variable standing in for the whole X — see [Variables](#variables) |

`outline.*` measures where the ink actually is at height Y. Crossings pair into
spans (stems); `.first` / `.last` / `.N` pick one, otherwise the whole envelope
is used. `@…` overrides *where* the contour is sampled — e.g. centre a round
letter's top anchor on its x-height crossing (`outline.center@xHeight`) while
its Y sits higher.

The contour is sampled at **exactly** the requested height — no inset or nudge.
`outline.right@0` is the rightmost crossing at `y=0`, even when `0` coincides
with the glyph's own top/bottom extreme (e.g. an open hook). At a smooth peak
the scanline grazes the outline, so `@top`/`@bottom` returns that tangent point;
if a height finds no crossing at all (outside the ink box, or a flat collinear
edge) the bounding-box edge is used and a warning is recorded.

### Y — vertical position

| token | meaning |
|-------|---------|
| `$G` | top of glyph G's bounding box |
| `$G.bottom` | bottom of G's box |
| `$G.middle` | vertical middle of G's box |
| `$G*d1/d2` | fraction of G's height, from the baseline (e.g. `$H*5/6`) |
| `ascender` `descender` `capHeight` `xHeight` `unitsPerEm` `baseline` | a font-wide vertical metric from `font.info` (`baseline` = 0) |
| `capHeight*2/3` | a fraction of a metric |
| `capHeight*1/2+xHeight*1/2` | a **sum** of terms (no spaces); here the midpoint between x-height and cap-height |
| `box.bottom` / `box.middle` / `box.top` | this glyph's **own** bbox: `yMin` / centre / `yMax` |
| `box*2/3` | a fractional position up the bbox |
| `outline.bottom` / `outline.top` / `outline.center` | lowest / highest / centre crossing on a **vertical** scanline at the anchor's X |
| `outline.N.center` | centre of the N-th vertical span at X (e.g. a bar of `E`, `Ё`) |
| `outline.centroid` | the area centre of mass (the y of it); see [Centroid](#centroid) |
| `<number>` | absolute Y in font units (integer) |
| `&name` | a variable standing in for the whole Y — see [Variables](#variables) |

Font metrics are bare keywords (no `$`), so they never collide with glyph
references; they don't depend on any particular glyph being present. Terms can
be summed with `+` (written without spaces) to combine metrics/glyphs/numbers.

The same `frame.position` grammar serves **both axes**: on Y the alignment
words are `bottom`/`middle`/`top` (rather than `left`/`center`/`right`). So
`box.top` is *this glyph's* own bbox top — no need to name the glyph as `$Glyph`
just to read its own height. An `outline` position on Y samples a *vertical*
scanline at the anchor's X (mirroring the horizontal scanline X uses); its
`@…` is therefore a **column** — an own-side edge (`@left`/`@right`) or a fixed
X value (`outline.center@right`, `outline.middle@40`), decoupled from the
anchor's X. `$Glyph` still reads a *different* glyph's geometry.

> ⚠️ If **both** axes are an `outline` position with no `@` fix, each would need
> the other's coordinate as its scanline — a cycle, rejected up front. Pin one
> axis's sample line with `@` (e.g. `outline.right@40 outline.1.center`).

### Centroid

`outline.centroid` is the **area centre of mass** of the glyph's outline — its
optical centre. Unlike the scanline-sampled `outline.left/center/right`, it is a
single global 2-D point: used as X it yields the centroid's x, as Y its y. It
takes no `run` or `@`, and is polymorphic (legal in either slot). It best
suits *base* glyphs whose shape is lopsided — `a (top (outline.centroid
capHeight))` centres the diacritic over the visual mass — and, on both axes
(`center (outline.centroid outline.centroid)`), enclosing/overlay marks.

### Summed positions (a base plus a bias)

Terms combine with `+` and `-` on either axis (written without spaces). On Y
this sums/subtracts heights — `capHeight*1/2+xHeight*1/2` is the midpoint between
x-height and cap-height, `ascender-descender` the full em extent. On X it adds a
**bias** to a base position:

```
&acuteShift = -25
acute = _top (outline.centroid+&acuteShift capHeight)   # nudge toward the foot
grave = _top (outline.centroid+25 capHeight)
```

Any term may be added or subtracted (a number, metric, `$glyph`, `&variable`, or
another position — `box.right-box.left` is the box width). The centroid is the
optical centre, so a slanted mark (acute/grave) wants a small horizontal bias off
it — `+`/`-` is how you dial that in, scalably, in one rule.

Two caveats: a `-` next to a `$glyph` is read as subtraction (`$H-50` = `$H`
minus 50), so a glyph *named* with a hyphen can't be referenced inline in a sum —
the missing-glyph fallback flags it when the font is applied. And a bias and an
`@` sample on the *same* term don't combine inline — the `@` owns the rest of the
token; put the sampled position in a `&variable` and add the bias to that.

## Italic fonts

On a slanted font (`italicAngle ≠ 0`) every **X** is projected along the angle
from the height at which it was *measured* to the anchor's own height — so an
anchor follows the stem instead of sitting beside it. The shift is
`tan(-italicAngle) · (Y − S)`, where `S` is where the X source is defined:

- `outline.center@xHeight` placed at `ascender+40` is measured at x-height but
  the anchor is higher, so it slides right onto the stem at that height
  (`S = xHeight`);
- `outline.center` / `outline.center@capHeight` *at* cap-height get **no** shift
  — the sample height equals the anchor height (`S = Y`), so an `H`'s top stays
  exactly between its two slanted stems;
- `box.*` / `width.*` are upright references (`S = 0`), sheared by `tan·Y` as
  before; `outline.centroid` projects from its own height.

It's automatic — nothing to write in a rule — and on an upright font the angle is
0, so every shift is 0.

## Labels

A label names a reusable list of anchors:

```
@      = top (box.center capHeight), bottom (box.center 0)
@desc  = desc (outline.right 0)
@bar   = bar (width.center capHeight*1/2)
@_     = _top (outline.center@bottom capHeight)
```

Prefer font metrics (`capHeight`, `xHeight`, …) over a glyph's bbox top
(`$H`, `$x`) for heights — they don't depend on a particular glyph being
present. Use `$Glyph` when you specifically need *that glyph's* geometry.

Reference labels (and mix with inline anchors) when marking a glyph:

```
A = @, @ogonek
L = @bot, top (box.left capHeight), caron (box.right capHeight)
t = @, barlow (width.center xHeight*2/3)
```

## Variables

A variable names a reusable **axis expression** — anything you could write in an
anchor's X or Y slot — so a value used in many places is written once:

```
&mid  = capHeight*1/2+xHeight*1/2     # a Y expression
&inkc = outline.center@xHeight        # an X expression

@bar = bar (width.center &mid)
O    = top (box.center &inkc), bottom (box.center &mid)
```

Where a label (`@`) stands for a *list of anchors*, a variable (`&`) stands for
*one axis's value*. Define one with `&name = <expr>`; the value parses exactly
like an X or Y slot.

- **Typed by axis.** Which axis a variable *is* falls out of its expression
  (`box.center` → X, `capHeight*…` → Y). Using an X variable where Y is expected
  (or vice versa) is an error, reported up front. A **bare number is
  polymorphic** — usable on either axis.
- **Composable.** A variable may appear as a term of a `+`-sum
  (`&mid+ascender*1/12`), as an `@` sample height (`outline.center@&mid`), and a
  variable may reference another (`&b = &a`).
- **Late-bound, like labels.** A `&name` resolves at apply time against the
  final (possibly `!extends`-merged) table, so a later definition — including one
  in a file that extends this — wins, and definitions may appear anywhere.
- **Checked up front.** An undefined variable and a reference cycle
  (`&a = &b`, `&b = &a`) are both rejected at load time, before any glyph is
  touched, with the offending name / cycle chain named.

## Selectors — what a rule applies to

The left-hand side of a rule selects glyphs:

| selector | matches |
|----------|---------|
| `A` | the glyph named `A` |
| `U+0413` | the glyph mapped from code point U+0413 |
| `U+0410..U+044F` | every glyph in the (inclusive) code-point range |
| `*.sc` | glyph names by glob (`*`, `?`) |
| `{Lu}` | glyphs whose Unicode general category is `Lu` (a one-letter `{L}` matches every subcategory: `Lu`, `Ll`, …) |
| `C, O, S` | a comma-separated list — applies to each listed selector |

A range/glob/category lets one line stand in for the dozens of identical
`U+XXXX = @` lines a real font otherwise needs.

A **comma-separated list** on the left applies the same right-hand side to
every selector in it, exactly as if you had written one line per selector:

```
C, O, S += top (outline.center@top capHeight), bottom (outline.center@bottom 0)
```

The list may mix selector kinds (`A, U+0421, *.sc = @round`); each entry is
parsed independently with the table above.

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

### `!suffixes` — apply every rule to glyph variants

Every rule is replayed on `base + suffix` for each configured suffix (geometry
re-sampled on each variant's own outline), in addition to the bare base. The
unsuffixed base (`""`) is always included. `!suffixes` takes the **same
operators as rules** and they compose through `!extends` (base directives first,
then this file's):

```
!suffixes  = .sc, .alt    # set the list (replaces any inherited list)
!suffixes += .smcp        # add a suffix to the inherited list
!suffixes -= .alt         # drop a suffix from the inherited list
!suffixes  = none         # reset to base glyphs only (no variants)
```

Instead of listing suffixes, **`all`** discovers them from the font — every
glyph named `base.<suffix>` is treated as a variant of `base`:

```
!suffixes = all                      # all `base.*` variants in the font
!suffixes = all except .numr, .dnom  # …minus suffixes that need different anchors
```

In `all` mode the operators adjust the exclusion set: `-= .numr` excludes a
suffix, `+= .numr` puts it back. (`all` / `none` are whole-list states, so they
require `=`, not `+=`/`-=`.)

```
!extends default
U+0413 += hook (outline.right 0)   # Г: defaults plus a hook
A      -= ogonek                   # A: defaults minus the ogonek anchor
O       = top (box.center $H)       # O: replace entirely
```

## A complete example

```
# --- variables ---
&barY  = capHeight*1/2                # uppercase crossbar height

# --- labels ---
@      = top (box.center capHeight), bottom (box.center 0)
@bot   = bottom (box.center 0)
@_     = _top (outline.center@bottom capHeight)
@desc  = desc (outline.right 0)
@bar   = bar (width.center &barY)
@hook  = hook (outline.right 0)
@ogonek = ogonek (outline.right 0)

# --- Latin ---
A = @, @ogonek
H = @, @hook, @desc, @bar
L = @bot, top (box.left capHeight), caron (box.right capHeight)

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

Convert existing files automatically — the conversion is checked lossless:

```
anchorsfactory-convert examples/default-anchors-list.txt -o my-rules.af
```
