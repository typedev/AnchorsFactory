# Variables & labels

A label (`@name`) names a reusable *list of anchors*; a variable (`&name`)
names a reusable *axis expression* — anything you could write in an X or Y
slot. Both are late-bound, so a redefinition (including one in a file that
`!extends` this one) wins everywhere, and both are checked up front: variables
are typed by axis, and undefined names and reference cycles are rejected
before any glyph is touched.

*(stub — to be written)*
