"""Apply a parsed :class:`Document` to a font: place the anchors.

Resolution follows the accumulation model: rules are scanned in file order and
every rule whose selector matches a glyph mutates that glyph's anchor list —
``=`` replaces it, ``+=`` appends. This single path serves both front-ends
(the legacy parser emits all-``REPLACE`` rules, so each glyph matched once
behaves exactly as before).

Coordinate maths is delegated to :mod:`anchorsfactory.geometry`.
"""

from __future__ import annotations

import fnmatch
import logging
import unicodedata

from .geometry import resolve
from .model import (
    Document, Op, LabelRef,
    GlyphName, Unicode, UnicodeRange, Glob, Category,
)

log = logging.getLogger(__name__)


def _resolve_items(items, labels, _seen=()):
    """Expand LabelRefs to concrete AnchorSpecs against *labels* (late binding)."""
    specs = []
    for it in items:
        if isinstance(it, LabelRef):
            if it.name in _seen:
                raise ValueError(f"label cycle through {it.name}")
            if it.name not in labels:
                raise ValueError(f"undefined label {it.name}")
            specs.extend(_resolve_items(labels[it.name], labels, _seen + (it.name,)))
        else:
            specs.append(it)
    return specs


def _remove_targets(items, labels):
    """Names to drop for a REMOVE rule: bare names plus the names a label defines."""
    names = set()
    for it in items:
        if isinstance(it, LabelRef):
            names.update(s.name for s in _resolve_items([it], labels))
        else:
            names.add(it)
    return names


def _matches(selector, name: str, unicodes) -> bool:
    if isinstance(selector, GlyphName):
        return name == selector.name
    if isinstance(selector, Unicode):
        return selector.codepoint in unicodes
    if isinstance(selector, UnicodeRange):
        return any(selector.start <= u <= selector.end for u in unicodes)
    if isinstance(selector, Glob):
        return fnmatch.fnmatchcase(name, selector.pattern)
    if isinstance(selector, Category):
        return any(unicodedata.category(chr(u)).startswith(selector.value) for u in unicodes)
    raise TypeError(f"unknown selector {selector!r}")


def accumulate(doc: Document, name: str, unicodes) -> list:
    """Build a glyph's anchor list by applying matching rules in order.

    ``=`` replaces, ``+=`` appends, ``-=`` drops by anchor name. Labels are
    resolved here, against ``doc.labels``, so overrides take effect late.
    """
    acc: list = []
    for selector, op, items in doc.rules:
        if not _matches(selector, name, unicodes):
            continue
        if op is Op.REMOVE:
            drop = _remove_targets(items, doc.labels)
            acc = [s for s in acc if s.name not in drop]
        else:
            specs = _resolve_items(items, doc.labels)
            acc = specs if op is Op.REPLACE else acc + specs
    return acc


def apply_document(font, doc: Document, *, clear=True, replace=True, round_coords=True):
    """Place all anchors described by *doc* onto *font* (in place).

    ``round_coords`` rounds placed anchors to whole units (the usual choice for
    a UFO); the golden regression passes ``False`` to compare raw precision.
    """
    for glyph in font:
        specs = accumulate(doc, glyph.name, list(glyph.unicodes))
        if not specs:
            continue
        for sfx in doc.suffixes:
            gname = glyph.name + sfx
            if gname in font:
                _place(font, font[gname], specs, doc.shift_x, clear, replace, round_coords)


def _remove_named(glyph, name):
    for anchor in list(glyph.anchors):
        if anchor.name == name:
            glyph.removeAnchor(anchor)


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
