# Italic behavior

On a slanted font every X is automatically projected along `italicAngle` from
the height where it was measured to the anchor's own height, so anchors follow
the stems — there is nothing to write in the rules. This chapter explains the
height-aware shear (`tan(-angle)·(Y−S)` and what `S` is per frame), and why
`box.*`/`width.*` should be avoided for horizontal positioning on italics in
favour of `outline.*` and the centroid.

*(stub — to be written)*
