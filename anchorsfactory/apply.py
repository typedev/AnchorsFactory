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


def validate_document(doc: Document) -> list[str]:
    """Pre-flight check (font-independent): every @label reference resolves.

    Returns a list of human-readable problems (empty = ok). Catches typo'd
    label names up front instead of at apply time, glyph by glyph.
    """
    problems = []
    for lname, items in doc.labels.items():
        for it in items:
            if isinstance(it, LabelRef) and it.name not in doc.labels:
                problems.append(f"label {lname}: undefined label {it.name}")
    for sel, op, items in doc.rules:
        for it in items:
            if isinstance(it, LabelRef) and it.name not in doc.labels:
                problems.append(f"rule {sel}: undefined label {it.name}")
    return problems


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


def compute_document(font, doc: Document, *, replace=True, round_coords=True):
    """Compute the anchors *doc* describes for *font*, without mutating it.

    Returns ``{target_glyph_name: [(anchor_name, x, y), ...]}`` — exactly what
    :func:`apply_document` (with matching ``replace``/``round_coords``) would
    place, the supported way to preview placement before applying. This is the
    functional core: it owns suffix expansion (geometry sampled on the suffixed
    target), ``shift_x``, rounding, and the within-document same-name dedup;
    ``apply_document`` is the thin write step on top.

    ``replace`` applies the same-name dedup within a glyph's computed list (last
    occurrence wins, keeping that occurrence's position) — the ``=``/``+=``
    accumulator can carry several specs sharing a name. Glyphs with no matching
    rules, and suffix targets absent from *font*, are omitted.
    """
    placed: dict[str, list[tuple[str, float, float]]] = {}
    for glyph in font:
        specs = accumulate(doc, glyph.name, list(glyph.unicodes))
        if not specs:
            continue
        for sfx in doc.suffixes:
            gname = glyph.name + sfx
            if gname not in font:
                continue
            target = font[gname]
            anchors: list[tuple[str, float, float]] = []
            for spec in specs:
                x, y = resolve(font, target, spec)
                x += doc.shift_x
                if round_coords:
                    x, y = round(x), round(y)
                if replace:
                    anchors = [a for a in anchors if a[0] != spec.name]
                anchors.append((spec.name, x, y))
            placed[gname] = anchors
    return placed


def apply_document(font, doc: Document, *, clear=True, replace=True, round_coords=True):
    """Place all anchors described by *doc* onto *font* (in place).

    ``round_coords`` rounds placed anchors to whole units (the usual choice for
    a UFO); the golden regression passes ``False`` to compare raw precision.
    The computation is delegated to :func:`compute_document`; ``clear``/
    ``replace`` here govern the write against the font's *pre-existing* anchors.
    """
    placed = compute_document(font, doc, replace=replace, round_coords=round_coords)
    for gname, anchors in placed.items():
        glyph = font[gname]
        if clear:
            for anchor in list(glyph.anchors):
                glyph.removeAnchor(anchor)
        for name, x, y in anchors:
            if not clear and replace:
                _remove_named(glyph, name)
            glyph.appendAnchor(name, (x, y))


def _remove_named(glyph, name):
    for anchor in list(glyph.anchors):
        if anchor.name == name:
            glyph.removeAnchor(anchor)
