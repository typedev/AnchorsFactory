# AnchorsFactory

A module for working with the rules for placing anchors in a font.
The rule describes the position of one or several anchors at once.
Several rules can be applied to one fingerboard at once.
The rules are stored in a separate text file, for example 
[anchors-list.txt](anchors-list.txt)

### General recording format:

 
```
@Label1=Anchor:Alignment:VertPosition
@Label2=..
# a comment
GlyphName=@Label1,@Label2,..
```

### General rules syntax
```
@Label=Anchor:Alignment:VertPosition, ...
```

`@Label` - the name of the rule label, always starting with `@`

`Anchor` - the name of the anchor, in names to indicate anchors in accents you must use the `_` sign


`Alignment` - horizontal alignment of the anchor.
If a numeric value is specified, this will be the horizontal position of the anchor.
`left`/`center`/`right` - anchor position on the left/right border of the glyph (glyph.bounds) or in the middle of the glyph glyph.width/2;
`centerpos` - in the middle glyph.bounds

`leftinter`/`rightinter` - position is calculated by intersection with the glyph outline at the height specified after `$..` (intersection)



`VertPosition` - anchor height. Numeric value, or the height of the glyph indicated by `$..`
after `$GlyphName` you can write the fractional value of the anchor height using the `*` sign
`1/2` - in the middle in height,
`1/3` - in the first lower third of the height,
`2/3` - in the upper third of the height

For example:

`@bar=bar:center:$H*2/3` - `@bar` label, `bar` anchor, aligned to the center of the character width, height - `2/3` of the `H` glyph height
`@back=back:left:700` - `@back` label, `back` anchor, on the left border of the glyph, at height `700`


If the glyph name ends with `_` the height is calculated by its lower bound glyph.bounds, can be used for multi-story accents

Example:

`@_grave=_grave:center:$gravecomb_`
the `_grave` anchor will be centered, but at the height of the bottom border of the `gravecomb` glyph

One rule can have several anchors; they are listed with a comma

`@=top:center:700,bottom:center:0`

If there are alternatives in the font, they can be indicated via a label
`@SFXLIST=alt,alt01`
in this case, alternatives with suffixes `*.alt`, `*.alt01` will be found for all glyphs listed in the file and the same anchor rules will be applied as for the base character