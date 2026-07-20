# Italic behavior

On a slanted font every X is automatically projected along `italicAngle` from
the height where it was measured to the anchor's own height, so anchors follow
the stems — there is nothing to write in the rules. This chapter explains the
height-aware shear (`tan(-angle)·(Y−S)` and what `S` is per frame): `0` for the
advance box and for `box.*` — which on a slanted font is measured on the outline
sheared back upright, so it is a genuine upright reference — the sample height
for `outline.*`, and its own height for the centroid.

*(stub — to be written)*
