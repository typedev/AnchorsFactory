# Italic behavior

On a slanted font every X is automatically projected along `italicAngle` from
the height where it was measured to the anchor's own height, so anchors follow
the stems — there is nothing to write in the rules. This chapter explains the
height-aware shear (`tan(-angle)·(Y−S)` and what `S` is per frame): `0` for the
advance box, the bounding box's own middle for `box.*`, the sample height for
`outline.*`, and its own height for the centroid. It also covers when to reach
for `outline.*` anyway — an irregular shape's box is only approximately sheared.

*(stub — to be written)*
