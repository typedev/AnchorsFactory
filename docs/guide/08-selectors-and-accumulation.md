# Selectors & the accumulation model

A rule's left-hand side selects glyphs — by name, code point (`U+0413`), range
(`U+0410..U+044F`), glob (`*.sc`), Unicode category (`{Lu}`), or a
comma-separated mix — and rules are processed in file order, each matching
rule mutating the glyph's accumulated anchor list (`=` replace, `+=` add,
`-=` remove). This chapter teaches the core idiom, *broad defaults first,
specific exceptions after*, and warns about `=` being a hard reset.

*(stub — to be written)*
