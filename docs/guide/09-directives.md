# Directives

Four pragmas shape how a rules file behaves as a whole: `!extends` inherits
another rules file — by path, or by a bare set name resolved on the search path
(rules concatenate, labels/variables override),
`!suffixes` replays every rule onto `base.suffix` glyph variants (with
`=`/`+=`/`-=` list editing, plus `all` / `all except …` discovery from the
font), `!shiftx` adds a constant X offset to every placed anchor, and
`!propagate` (`composites` / `all`) makes composite glyphs inherit their
components' anchors. This chapter shows the small-override workflow: `!extends
default` plus a handful of adjustments.

*(stub — to be written)*
