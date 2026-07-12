"""Read-only queries over a :class:`~anchorsfactory.model.Document` for
interactive editors (issue #3).

Everything here is pure over ``(name, unicodes)`` — no fontParts (a consumer
feeds glyph names/codepoints from a font). It answers the two directions an
editor needs — a rule's selector → the glyphs it hits (cursor → grid), and a
glyph → the rules that place its anchors (grid → editor) — and traces the
per-glyph accumulation so a deep ``!extends`` chain is legible. Placed
coordinates + provenance (needs a font) live in
:func:`anchorsfactory.explain_document`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .apply import (_remove_targets, _resolve_items, _resolve_vars_in_spec,
                    selector_matches)
from .dsl import _RULE_RE, _parse_selector, _split_items
from .model import Document, Op, Rule, Selector


def parse_selectors(line: str) -> list[Selector]:
    """The selector(s) on a rule *line* (its left-hand side), for the reverse
    direction — a rule under the cursor → the glyphs it matches.

    Accepts a bare selector (``"A"``, ``"{Lu}"``, ``"*.sc"``, ``"U+0410"``) or a
    full rule line (``"C, O = top (...)"``); a comma list yields one
    :data:`~anchorsfactory.model.Selector` each. Raises
    :class:`~anchorsfactory.dsl.DSLError` on an unparseable selector.
    """
    m = _RULE_RE.match(line.strip())
    lhs = m.group(1).strip() if m else line.strip()
    return [_parse_selector(tok) for tok in _split_items(lhs) if tok.strip()]


def glyphs_for_selector(selector, glyphs: Iterable) -> list[str]:
    """Names in *glyphs* (an iterable of ``(name, unicodes)`` pairs) that
    *selector* matches, in input order."""
    return [name for name, unicodes in glyphs
            if selector_matches(selector, name, unicodes)]


def rules_for_glyph(doc: Document, name: str, unicodes) -> list[Rule]:
    """The document's rules matching glyph *name*, in document order (each
    carries its ``.op`` and ``.source``).

    This is the raw grid→editor mapping — every rule that *touches* the glyph. It
    does not resolve which anchors ultimately survive later ``=``/``-=`` rules;
    for the accumulation trace use :func:`explain_glyph`.
    """
    return [r for r in doc.rules if selector_matches(r.selector, name, unicodes)]


@dataclass
class RuleTrace:
    """One step of a glyph's accumulation: the matching *rule* and the anchor
    specs the accumulator held right after it ran."""
    rule: Rule
    accumulator: list


@dataclass
class Explanation:
    """A glyph's ordered accumulation trace. *steps* are per matching rule (with
    the accumulator snapshot after each); *final* is the resulting spec list —
    equal to :func:`anchorsfactory.accumulate` for the same inputs."""
    glyph: str
    steps: list
    final: list


def explain_glyph(doc: Document, name: str, unicodes, *, seed=()) -> Explanation:
    """Trace how glyph *name* accumulates its anchors, rule by rule.

    Mirrors :func:`anchorsfactory.accumulate` step for step (labels and
    ``&``-variables resolved late, as at apply time), recording the accumulator
    after each matching rule — so ``explain_glyph(...).final == accumulate(...)``.
    Doc-level: no coordinates; use :func:`anchorsfactory.explain_document` for
    placed coordinates + provenance. *seed* seeds the accumulator like
    :func:`~anchorsfactory.accumulate` (propagated component anchors).
    """
    acc: list = list(seed)
    steps: list[RuleTrace] = []
    for rule in doc.rules:
        if not selector_matches(rule.selector, name, unicodes):
            continue
        if rule.op is Op.REMOVE:
            drop = _remove_targets(rule.items, doc.labels)
            acc = [s for s in acc if s.name not in drop]
        else:
            specs = _resolve_items(rule.items, doc.labels)
            if doc.variables:
                specs = [_resolve_vars_in_spec(s, doc.variables) for s in specs]
            acc = specs if rule.op is Op.REPLACE else acc + specs
        steps.append(RuleTrace(rule, list(acc)))
    return Explanation(name, steps, list(acc))
