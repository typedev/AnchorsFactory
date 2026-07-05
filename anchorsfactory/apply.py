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
from dataclasses import dataclass, replace

from .geometry import resolve, _dependent
from .model import (
    Document, Op, LabelRef, VarRef, resolve_suffixes,
    Axis, Pos, Centroid, Abs, Y, FontMetric, Sum, Neg, VEdge, HAlign,
    GlyphName, Unicode, UnicodeRange, Glob, Category,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComputeDiagnostic:
    """One spec that :func:`compute_document` (``on_error='collect'``) flagged.

    ``severity`` is ``"error"`` — the anchor was skipped (geometry raised) — or
    ``"warning"`` — the anchor *was* placed but via a geometry fallback rather
    than a clean computation, so its position is suspect (see :func:`_degrade`).
    ``rule`` will point at the originating rule's source once provenance
    (issue #3) lands; it stays ``None`` until then.
    """
    glyph: str                       # target (suffixed) glyph name
    anchor: str                      # spec.name
    reason: str                      # str(exc)
    severity: str = "error"
    rule: object | None = None       # RuleSource once #3 lands


class ComputeResult(dict):
    """``{target_glyph: [(name, x, y), ...]}`` plus a ``diagnostics`` list.

    A plain ``dict`` subclass: it compares equal to the equivalent dict and works
    anywhere a dict does, so :func:`apply_document` and existing callers are
    unaffected. ``diagnostics`` is empty unless :func:`compute_document` ran with
    ``on_error='collect'``.
    """

    def __init__(self, *args, diagnostics=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.diagnostics: list[ComputeDiagnostic] = (
            diagnostics if diagnostics is not None else []
        )


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


# --------------------------------------------------------------------------- #
#  Variable (&name) substitution — late, like labels, but per axis.
# --------------------------------------------------------------------------- #
def _expand(node, variables, seen):
    """Follow a chain of leading VarRefs to the underlying strategy node.

    Returns ``(node, seen)`` where *node* is no longer a VarRef and *seen* lists
    the variables crossed (so a caller recursing into the node's own parts keeps
    detecting cycles). Raises on an undefined variable or a reference cycle.
    """
    while isinstance(node, VarRef):
        if node.name in seen:
            chain = " → ".join(seen + (node.name,))
            raise ValueError(f"cyclic variable reference: {chain}")
        if node.name not in variables:
            raise ValueError(f"undefined variable {node.name}")
        seen = seen + (node.name,)
        node = variables[node.name]
    return node, seen


def _resolve_x(node, variables, seen=()):
    """Substitute variables in an X strategy, validating it resolves to an X.

    A bare number (:class:`Abs`) and the area :class:`Centroid` are polymorphic;
    a Y expression used where X is required is an error.
    """
    node, seen = _expand(node, variables, seen)
    if isinstance(node, (Abs, Centroid)):       # polymorphic — fine on either axis
        return node
    if isinstance(node, Neg):
        return Neg(_resolve_x(node.term, variables, seen))
    if isinstance(node, Sum):
        return Sum(tuple(_resolve_x(t, variables, seen) for t in node.terms))
    if isinstance(node, Pos):
        if node.axis is not Axis.X:
            raise ValueError(f"variable holds a Y expression ({node}) but X is required")
        if node.at is not None and not isinstance(node.at, VEdge):
            node = replace(node, at=_resolve_y(node.at, variables, seen))
        return node
    raise ValueError(f"variable holds a Y expression ({node}) but X is required")


def _resolve_y(node, variables, seen=()):
    """Substitute variables in a Y strategy, validating it resolves to a Y."""
    node, seen = _expand(node, variables, seen)
    if isinstance(node, (Abs, Centroid)):       # polymorphic — fine on either axis
        return node
    if isinstance(node, Neg):
        return Neg(_resolve_y(node.term, variables, seen))
    if isinstance(node, Pos):
        if node.axis is not Axis.Y:
            raise ValueError(f"variable holds an X expression ({node}) but Y is required")
        if node.at is not None and not isinstance(node.at, HAlign):
            node = replace(node, at=_resolve_x(node.at, variables, seen))
        return node
    if isinstance(node, Sum):
        return Sum(tuple(_resolve_y(t, variables, seen) for t in node.terms))
    if isinstance(node, (Y, FontMetric)):
        return node
    raise ValueError(f"variable holds an X expression ({node}) but Y is required")


def _resolve_vars_in_spec(spec, variables):
    """Return *spec* with every VarRef in its X and Y substituted out."""
    return replace(spec, x=_resolve_x(spec.x, variables), y=_resolve_y(spec.y, variables))


def _check_var_node(node, variables, seen):
    """Walk a strategy node following VarRefs, raising on undefined/cycle.

    Axis-agnostic structural check (used for variable definitions, incl. unused
    ones); axis compatibility is enforced separately by :func:`_resolve_vars_in_spec`.
    """
    if isinstance(node, VarRef):
        if node.name in seen:
            chain = " → ".join(seen + (node.name,))
            raise ValueError(f"cyclic variable reference: {chain}")
        if node.name not in variables:
            raise ValueError(f"undefined variable {node.name}")
        _check_var_node(variables[node.name], variables, seen + (node.name,))
    elif isinstance(node, Pos):
        if node.at is not None and not isinstance(node.at, (VEdge, HAlign)):
            _check_var_node(node.at, variables, seen)
    elif isinstance(node, Neg):
        _check_var_node(node.term, variables, seen)
    elif isinstance(node, Sum):
        for term in node.terms:
            _check_var_node(term, variables, seen)


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
    """Pre-flight check (font-independent): every @label and &variable resolves.

    Returns a list of human-readable problems (empty = ok). Catches, up front
    instead of at apply time glyph by glyph: typo'd label names; undefined or
    cyclically-defined variables (incl. ones only reachable after !extends
    merging); and a variable used on the wrong axis (an X expression where Y is
    required, or vice versa); and an anchor whose X and Y both sample the
    outline with no ``@`` fix (a circular axis dependency).
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
    # Variable definitions: undefined refs / cycles, even if never used.
    for vname, value in doc.variables.items():
        try:
            _check_var_node(value, doc.variables, (vname,))
        except ValueError as e:
            problems.append(f"variable {vname}: {e}")
    # Variable usage in rules: axis compatibility (plus undefined/cycle in
    # anchors that name a variable directly). Skipped if labels are already
    # broken, since expanding them would just re-raise what we reported above.
    if not problems:
        for sel, op, items in doc.rules:
            if op is Op.REMOVE:
                continue
            try:
                for spec in _resolve_items(items, doc.labels):
                    rspec = _resolve_vars_in_spec(spec, doc.variables)
                    if _dependent(rspec.x) and _dependent(rspec.y):
                        problems.append(
                            f"rule {sel}: anchor {rspec.name!r} samples both axes on the "
                            f"outline with no @-fix ({rspec.x} {rspec.y}); add @ to one")
            except ValueError as e:
                problems.append(f"rule {sel}: {e}")
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
            if doc.variables:
                specs = [_resolve_vars_in_spec(s, doc.variables) for s in specs]
            acc = specs if op is Op.REPLACE else acc + specs
    return acc


def accumulate_provenance(doc: Document, name: str, unicodes) -> list:
    """Like :func:`accumulate`, but tag each surviving spec with the index of the
    rule that placed it.

    Returns a list of ``(AnchorSpec, rule_index)`` in final order — where
    ``rule_index`` indexes ``doc.rules`` (and, when the DSL parser set it,
    ``doc.sources`` for the source line). This is the provenance backbone for the
    studio ("which rule produced this anchor"); the plain :func:`accumulate` is
    unchanged for the batch/apply path.
    """
    acc: list = []                             # (spec, rule_index)
    for i, (selector, op, items) in enumerate(doc.rules):
        if not _matches(selector, name, unicodes):
            continue
        if op is Op.REMOVE:
            drop = _remove_targets(items, doc.labels)
            acc = [(s, idx) for (s, idx) in acc if s.name not in drop]
        else:
            specs = _resolve_items(items, doc.labels)
            if doc.variables:
                specs = [_resolve_vars_in_spec(s, doc.variables) for s in specs]
            tagged = [(s, i) for s in specs]
            acc = tagged if op is Op.REPLACE else acc + tagged
    return acc


def compute_document(font, doc: Document, *, replace=True, round_coords=True,
                     on_error="raise", names=None) -> ComputeResult:
    """Compute the anchors *doc* describes for *font*, without mutating it.

    Returns a :class:`ComputeResult` — a ``dict`` of
    ``{target_glyph_name: [(anchor_name, x, y), ...]}`` (exactly what
    :func:`apply_document` with matching ``replace``/``round_coords`` would
    place) plus a ``diagnostics`` list. This is the supported way to preview
    placement before applying, and the functional core: it owns suffix expansion
    (geometry sampled on the suffixed target), ``shift_x``, rounding, and the
    within-document same-name dedup; ``apply_document`` is the thin write step.

    ``replace`` applies the same-name dedup within a glyph's computed list (last
    occurrence wins, keeping that occurrence's position) — the ``=``/``+=``
    accumulator can carry several specs sharing a name. Glyphs with no matching
    rules, and suffix targets absent from *font*, are omitted.

    ``on_error`` governs a spec whose geometry does not resolve cleanly:

    - ``"raise"`` (default) — propagate hard failures (batch behaviour);
      ``result.diagnostics`` stays empty.
    - ``"collect"`` — never raises; instead records :class:`ComputeDiagnostic`\\ s
      in ``result.diagnostics`` so an interactive preview can show what it
      computed and flag the rest. Two severities:

      * ``"error"`` — geometry raised (malformed contour / dangling component);
        the anchor is *skipped*. A glyph is included only if ≥1 anchor resolved.
      * ``"warning"`` — geometry produced a value via a *fallback* (no outline
        crossing, missing metric/reference glyph); the anchor is *placed* but
        flagged as suspect. Driven by the ``warnings`` channel of
        :func:`~anchorsfactory.geometry.resolve`.

    ``names`` restricts computation to a subset of **target (suffixed)** glyph
    names — the keys of the returned :class:`ComputeResult` (``glyph.name + sfx``,
    not the base glyph). ``None`` (default) computes every matched glyph; an empty
    iterable computes nothing. Besides scoping the result, the filter skips
    :func:`resolve` for non-selected glyphs, so it is also a perf win.
    """
    if on_error not in ("raise", "collect"):
        raise ValueError(f"on_error must be 'raise' or 'collect', got {on_error!r}")
    keep = None if names is None else set(names)
    sfx_spec = resolve_suffixes(doc.suffix_ops)
    font_names = {g.name for g in font} if sfx_spec.all else None
    placed = ComputeResult()
    for glyph in font:
        specs = accumulate(doc, glyph.name, list(glyph.unicodes))
        if not specs:
            continue
        for sfx in sfx_spec.expand(glyph.name, font_names):
            gname = glyph.name + sfx
            if gname not in font:
                continue
            if keep is not None and gname not in keep:
                continue
            target = font[gname]
            anchors: list[tuple[str, float, float]] = []
            for spec in specs:
                sink = [] if on_error == "collect" else None
                try:
                    x, y = resolve(font, target, spec, warnings=sink)
                except Exception as exc:
                    if on_error == "raise":
                        raise
                    placed.diagnostics.append(
                        ComputeDiagnostic(gname, spec.name, str(exc), severity="error")
                    )
                    continue
                # Anchor resolved (possibly via a fallback) — place it, and flag
                # any soft degradations as warnings (it is placed, but suspect).
                for reason in sink or ():
                    placed.diagnostics.append(
                        ComputeDiagnostic(gname, spec.name, reason, severity="warning")
                    )
                x += doc.shift_x
                if round_coords:
                    x, y = round(x), round(y)
                if replace:
                    anchors = [a for a in anchors if a[0] != spec.name]
                anchors.append((spec.name, x, y))
            if anchors:
                placed[gname] = anchors
    return placed


def apply_document(font, doc: Document, *, clear=True, replace=True,
                   round_coords=True, names=None):
    """Place all anchors described by *doc* onto *font* (in place).

    ``round_coords`` rounds placed anchors to whole units (the usual choice for
    a UFO); the golden regression passes ``False`` to compare raw precision.
    The computation is delegated to :func:`compute_document`; ``clear``/
    ``replace`` here govern the write against the font's *pre-existing* anchors.

    ``names`` is forwarded to :func:`compute_document` to restrict the write to a
    subset of target (suffixed) glyphs. With ``clear=True`` only glyphs in the
    filtered result are cleared and rewritten — **non-selected glyphs are left
    untouched** (the "apply only to selected" behaviour an editor wants).
    """
    placed = compute_document(font, doc, replace=replace,
                              round_coords=round_coords, names=names)
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
