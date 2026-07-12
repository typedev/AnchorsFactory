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

from fontTools.misc.transform import Transform

from .geometry import resolve, _dependent
from .model import (
    Document, Op, LabelRef, VarRef, AnchorRef, AnchorSpec, resolve_suffixes,
    Axis, Pos, Centroid, Abs, Y, FontMetric, Sum, Neg, EdgeOffset, VEdge, HAlign,
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
    if isinstance(node, (Abs, Centroid, AnchorRef)):   # polymorphic — fine on either axis
        return node
    if isinstance(node, Neg):
        return Neg(_resolve_x(node.term, variables, seen))
    if isinstance(node, Sum):
        return Sum(tuple(_resolve_x(t, variables, seen) for t in node.terms))
    if isinstance(node, Pos):
        if node.axis is not Axis.X:
            raise ValueError(f"variable holds a Y expression ({node}) but X is required")
        if node.at is not None and not isinstance(node.at, (VEdge, EdgeOffset)):
            node = replace(node, at=_resolve_y(node.at, variables, seen))
        return node
    raise ValueError(f"variable holds a Y expression ({node}) but X is required")


def _resolve_y(node, variables, seen=()):
    """Substitute variables in a Y strategy, validating it resolves to a Y."""
    node, seen = _expand(node, variables, seen)
    if isinstance(node, (Abs, Centroid, AnchorRef)):   # polymorphic — fine on either axis
        return node
    if isinstance(node, Neg):
        return Neg(_resolve_y(node.term, variables, seen))
    if isinstance(node, Pos):
        if node.axis is not Axis.Y:
            raise ValueError(f"variable holds an X expression ({node}) but Y is required")
        if node.at is not None and not isinstance(node.at, (HAlign, EdgeOffset)):
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
        if node.at is not None and not isinstance(node.at, (VEdge, HAlign, EdgeOffset)):
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
    for rule in doc.rules:
        sel, items = rule.selector, rule.items
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
        for rule in doc.rules:
            sel, op, items = rule.selector, rule.op, rule.items
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


def accumulate(doc: Document, name: str, unicodes, *, seed=()) -> list:
    """Build a glyph's anchor list by applying matching rules in order.

    ``=`` replaces, ``+=`` appends, ``-=`` drops by anchor name. Labels are
    resolved here, against ``doc.labels``, so overrides take effect late.

    *seed* is the initial accumulator — the anchors inherited from a glyph's
    components under ``!propagate`` (see :func:`propagate_seed`). A ``=`` rule
    wipes it, ``+=`` extends it, ``-=`` drops from it, all for free.
    """
    acc: list = list(seed)
    for rule in doc.rules:
        selector, op, items = rule.selector, rule.op, rule.items
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


def accumulate_provenance(doc: Document, name: str, unicodes, *, seed=()) -> list:
    """Like :func:`accumulate`, but tag each surviving spec with the rule that
    placed it.

    Returns a list of ``(AnchorSpec, Rule)`` in final order — each
    :class:`~anchorsfactory.model.Rule` carries its ``.source``
    (:class:`~anchorsfactory.model.RuleSource`: origin/line/inherited), so an
    editor can map an anchor back to the rule that produced it. This is the
    provenance backbone for interactive tools; the plain :func:`accumulate` is
    unchanged for the batch/apply path.

    *seed* is a list of ``(AnchorSpec, provenance)`` pairs seeding the accumulator
    (propagated component anchors); their provenance is a :class:`Propagated`
    marker rather than a ``Rule``, which consumers render specially.
    """
    acc: list = list(seed)                     # (spec, Rule | Propagated)
    for rule in doc.rules:
        selector, op, items = rule.selector, rule.op, rule.items
        if not _matches(selector, name, unicodes):
            continue
        if op is Op.REMOVE:
            drop = _remove_targets(items, doc.labels)
            acc = [(s, prov) for (s, prov) in acc if s.name not in drop]
        else:
            specs = _resolve_items(items, doc.labels)
            if doc.variables:
                specs = [_resolve_vars_in_spec(s, doc.variables) for s in specs]
            tagged = [(s, rule) for s in specs]
            acc = tagged if op is Op.REPLACE else acc + tagged
    return acc


# --------------------------------------------------------------------------- #
#  !propagate — seed a composite's accumulator with its components' anchors.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Propagated:
    """Provenance marker for a seeded (inherited) anchor: the base glyph it came
    from. Stands in for the ``int`` rule index in :func:`accumulate_provenance`."""
    component: str


def _anchor_refs(node) -> set:
    """Names referenced by ``%anchor`` (:class:`AnchorRef`) terms within a
    strategy node, descending sums/negations and an ``@`` sample line."""
    if isinstance(node, AnchorRef):
        return {node.name}
    if isinstance(node, Neg):
        return _anchor_refs(node.term)
    if isinstance(node, Sum):
        out: set = set()
        for t in node.terms:
            out |= _anchor_refs(t)
        return out
    if isinstance(node, Pos) and node.at is not None and not isinstance(node.at, (VEdge, HAlign, EdgeOffset)):
        return _anchor_refs(node.at)
    return set()


def _sub_refs(node, coords: dict, axis: Axis):
    """Substitute every :class:`AnchorRef` in *node* with the referenced anchor's
    already-computed coordinate: its x on the X axis, its y on the Y axis. Inside
    an ``@`` sample line the axis flips (an X position's ``@`` is a height)."""
    if isinstance(node, AnchorRef):
        x, y = coords[node.name]
        return Abs(x if axis is Axis.X else y)
    if isinstance(node, Neg):
        return Neg(_sub_refs(node.term, coords, axis))
    if isinstance(node, Sum):
        return Sum(tuple(_sub_refs(t, coords, axis) for t in node.terms))
    if isinstance(node, Pos) and node.at is not None and not isinstance(node.at, (VEdge, HAlign, EdgeOffset)):
        other = Axis.Y if axis is Axis.X else Axis.X
        return replace(node, at=_sub_refs(node.at, coords, other))
    return node


def _resolve_specs(font, target, specs, doc, *, dedup, round_coords,
                   on_error, diagnostics, apply_shift=True):
    """Resolve *specs* onto *target*, returning ``[(name, x, y), ...]``.

    The single spec→coordinate step: same-name dedup (last wins, keeping that
    occurrence's position), ``%name`` derived-anchor resolution in dependency
    order, geometry resolve, ``shift_x``, rounding, and diagnostics. Shared by
    :func:`compute_document` (``apply_shift=True``) and :func:`_effective_anchors`
    (``apply_shift=False`` — propagation copies pre-shift geometry so the global
    ``shift_x`` is applied once, at the composite's own placement).

    ``%name`` resolves against the glyph's **final** list: non-derived anchors
    first, then derived ones once their referents have coordinates. A reference
    cycle raises (``on_error='raise'``) or is flagged (``'collect'``); a missing
    target degrades — the anchor is skipped, with a warning under ``'collect'``.
    """
    gname = target.name
    final = list(specs)
    if dedup:                                   # last occurrence wins, keeps its position
        deduped: list = []
        for s in specs:
            deduped = [t for t in deduped if t.name != s.name]
            deduped.append(s)
        final = deduped

    coords: dict[str, tuple] = {}               # name -> (x, y) pre-shift, for %refs
    result: list = [None] * len(final)          # per-position (x, y) or None (skipped)
    pending = list(range(len(final)))
    while pending:
        progressed = False
        rest = []
        for i in pending:
            spec = final[i]
            refs = _anchor_refs(spec.x) | _anchor_refs(spec.y)
            if any(r not in coords for r in refs):
                rest.append(i)
                continue
            if refs:
                spec = replace(spec, x=_sub_refs(spec.x, coords, Axis.X),
                               y=_sub_refs(spec.y, coords, Axis.Y))
            sink = [] if on_error == "collect" else None
            try:
                x, y = resolve(font, target, spec, warnings=sink)
            except Exception as exc:
                if on_error == "raise":
                    raise
                diagnostics.append(
                    ComputeDiagnostic(gname, spec.name, str(exc), severity="error"))
                progressed = True
                continue
            for reason in sink or ():
                diagnostics.append(
                    ComputeDiagnostic(gname, spec.name, reason, severity="warning"))
            result[i] = (x, y)
            coords[final[i].name] = (x, y)       # available to later derived anchors
            progressed = True
        if not progressed:                       # remaining refs are cycles or missing
            for i in rest:
                spec = final[i]
                refs = _anchor_refs(spec.x) | _anchor_refs(spec.y)
                missing = sorted(r for r in refs if r not in {s.name for s in final})
                if missing:
                    if on_error == "collect":
                        diagnostics.append(ComputeDiagnostic(
                            gname, spec.name,
                            f"references undefined anchor {missing[0]!r}", severity="warning"))
                    # raise mode: skip silently, like the missing-$glyph degrade
                elif on_error == "raise":
                    raise ValueError(
                        f"{gname}: anchor {spec.name!r} is in a %reference cycle")
                else:
                    diagnostics.append(ComputeDiagnostic(
                        gname, spec.name,
                        f"anchor {spec.name!r} is in a %reference cycle", severity="error"))
            break
        pending = rest

    anchors: list[tuple[str, float, float]] = []
    for i, spec in enumerate(final):
        if result[i] is None:
            continue
        x, y = result[i]
        if apply_shift:
            x += doc.shift_x
        if round_coords:
            x, y = round(x), round(y)
        anchors.append((spec.name, x, y))
    return anchors


def substitute_anchor_refs(font, target, specs, doc):
    """Studio helper: replace every ``%ref`` in *specs* with the referenced
    anchor's computed coordinate on *target*, so callers can :func:`explain` each
    spec without the geometry layer meeting an :class:`AnchorRef`.

    Returns ``(eff_specs, info)`` parallel to *specs*: ``eff_specs[i]`` is the
    substituted spec (unchanged when it has no refs, or when its refs don't
    resolve), and ``info[i]`` is ``(sorted_ref_names, resolved_bool)``.
    """
    refs_per = [sorted(_anchor_refs(s.x) | _anchor_refs(s.y)) for s in specs]
    if not any(refs_per):
        return list(specs), [(r, True) for r in refs_per]
    coords = {n: (x, y) for n, x, y in
              _resolve_specs(font, target, specs, doc, dedup=True, round_coords=False,
                             on_error="collect", diagnostics=[], apply_shift=False)}
    eff, info = [], []
    for s, refs in zip(specs, refs_per):
        ok = all(r in coords for r in refs)
        if refs and ok:
            s = replace(s, x=_sub_refs(s.x, coords, Axis.X),
                        y=_sub_refs(s.y, coords, Axis.Y))
        eff.append(s)
        info.append((refs, ok if refs else True))
    return eff, info


def _existing_anchors(font, gname: str) -> dict:
    """A glyph's pre-existing font anchors as ``{name: (x, y)}`` (fallback source
    when a component produced no computed anchors this run)."""
    if gname not in font:
        return {}
    return {a.name: (a.x, a.y) for a in font[gname].anchors}


def _effective_anchors(font, gname, doc, memo, stack, *, round_coords) -> dict:
    """The anchors glyph *gname* would be placed with, as ``{name: (x, y)}``
    (pre-``shift_x``) — the propagation source for composites that reference it.

    Memoised across a compute; *stack* holds the glyphs currently being resolved
    so a component cycle (a font bug) is detected and treated as "no anchors"
    rather than recursing forever.
    """
    if gname in memo:
        return memo[gname]
    if gname in stack:
        log.warning("component cycle through %r; skipping its propagation", gname)
        return {}
    if gname not in font:
        return {}
    glyph = font[gname]
    seed = [s for s, _ in propagate_seed(font, glyph, doc, memo,
                                         stack + (gname,), round_coords=round_coords)]
    specs = accumulate(doc, glyph.name, list(glyph.unicodes), seed=seed)
    anchors = _resolve_specs(font, glyph, specs, doc, dedup=True,
                             round_coords=round_coords, on_error="collect",
                             diagnostics=[], apply_shift=False)
    result = {name: (x, y) for name, x, y in anchors}   # final list → last wins
    memo[gname] = result
    return result


def propagate_seed(font, glyph, doc, memo, stack=(), *, round_coords=True) -> list:
    """Anchors glyph inherits from its components under ``doc.propagate``.

    Returns a list of ``(AnchorSpec, source_base_name)`` pairs — one per inherited
    anchor, in first-seen order, later components overriding earlier by name. Each
    spec is ``AnchorSpec(name, Abs(x), Abs(y))`` in the glyph's own coordinate
    space (the component transform already applied), so it flows through
    :func:`resolve` unchanged to the copied point. ``_``-prefixed (mark-side)
    anchors are never propagated. Empty when propagation is off or the glyph is
    not covered (``composites`` = components and no contours; ``all`` = any glyph
    with components).
    """
    mode = doc.propagate
    if mode == "none":
        return []
    components = list(getattr(glyph, "components", ()))
    if not components:
        return []
    if mode == "composites" and len(glyph.contours):
        return []
    inherited: dict[str, tuple] = {}                # name -> (x, y, source)
    for comp in components:
        base = comp.baseGlyph
        coords = _effective_anchors(font, base, doc, memo, stack,
                                    round_coords=round_coords) or _existing_anchors(font, base)
        t = Transform(*comp.transformation)
        for name, (x, y) in coords.items():
            if name.startswith("_"):               # mark-side anchor — never inherited
                continue
            nx, ny = t.transformPoint((x, y))
            inherited[name] = (nx, ny, base)
    return [(AnchorSpec(name, Abs(x), Abs(y)), src)
            for name, (x, y, src) in inherited.items()]


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
    memo: dict[str, dict] = {}                  # glyph name -> effective anchors (propagation)
    placed = ComputeResult()
    for glyph in font:
        seed = [s for s, _ in propagate_seed(font, glyph, doc, memo,
                                             round_coords=round_coords)]
        specs = accumulate(doc, glyph.name, list(glyph.unicodes), seed=seed)
        if not specs:
            continue
        for sfx in sfx_spec.expand(glyph.name, font_names):
            gname = glyph.name + sfx
            if gname not in font:
                continue
            if keep is not None and gname not in keep:
                continue
            anchors = _resolve_specs(font, font[gname], specs, doc, dedup=replace,
                                     round_coords=round_coords, on_error=on_error,
                                     diagnostics=placed.diagnostics)
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
