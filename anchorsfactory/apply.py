"""Apply a parsed :class:`Document` to a font: place the anchors.

This layer owns the *mutation* policy (clear / replace, suffix variants,
the document-wide X shift) and delegates all coordinate maths to
:mod:`anchorsfactory.geometry`. Behaviour intentionally mirrors the legacy
tool so the golden regression compares like with like; the safer-default and
rounding changes are layered on top afterwards.
"""

from __future__ import annotations

import logging

from .geometry import resolve
from .model import Document, GlyphName, Unicode

log = logging.getLogger(__name__)


def _resolve_selector(selector, cmap):
    """Return the target glyph name, or None if a unicode is not in the font."""
    if isinstance(selector, GlyphName):
        return selector.name
    if isinstance(selector, Unicode):
        names = cmap.get(selector.codepoint)
        return names[0] if names else None
    raise TypeError(f"unknown selector {selector!r}")


def _remove_named(glyph, name):
    for anchor in list(glyph.anchors):
        if anchor.name == name:
            glyph.removeAnchor(anchor)


def apply_document(font, doc: Document, *, clear=True, replace=True, round_coords=False):
    """Place all anchors described by *doc* onto *font* (in place)."""
    cmap = font.getCharacterMapping()

    # Resolve selectors to glyph names once; later rules win for the same glyph
    # (matches the legacy dict-overwrite semantics).
    resolved: dict[str, list] = {}
    for selector, specs in doc.rules:
        name = _resolve_selector(selector, cmap)
        if name is None:
            log.error("Unicode selector not in font: U+%04X", selector.codepoint)
            continue
        resolved[name] = specs

    for base_name, specs in resolved.items():
        if base_name not in font:
            log.warning("Glyph not found: %s", base_name)
            continue
        for sfx in doc.suffixes:
            gname = base_name + sfx
            if gname not in font:
                continue
            _place(font, font[gname], specs, doc.shift_x, clear, replace, round_coords)


def _place(font, glyph, specs, shift_x, clear, replace, round_coords):
    if clear:
        for anchor in list(glyph.anchors):
            glyph.removeAnchor(anchor)
    for spec in specs:
        x, y = resolve(font, glyph, spec)
        if replace:
            _remove_named(glyph, spec.name)
        x += shift_x
        if round_coords:
            x, y = round(x), round(y)
        glyph.appendAnchor(spec.name, (x, y))
