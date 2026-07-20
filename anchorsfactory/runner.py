"""High-level orchestration: open a UFO, apply rules, save safely.

Owns the file-IO policy that the CLI exposes. Key change from the legacy
tool: the default never overwrites the source UFO — output goes to a separate
``*_anchored.ufo`` unless ``--in-place`` is requested. Anchor backups, when
asked for, are written next to the font (or a chosen directory), never the
current working directory.
"""

from __future__ import annotations

import logging
import os
from dataclasses import replace

from fontParts.world import OpenFont

from . import presets
from .apply import apply_document
from .dsl import parse_dsl, parse_dsl_file
from .model import Document, RuleSource
from .parser import parse_file

log = logging.getLogger(__name__)

ANCHORED_SUFFIX = "_anchored.ufo"


def _restamp(doc: Document, **changes) -> Document:
    """Return *doc* with every rule's :class:`RuleSource` updated by *changes*
    (a fresh ``RuleSource`` is created for rules that carry none)."""
    rules = [replace(r, source=replace(r.source or RuleSource(), **changes))
             for r in doc.rules]
    return replace(doc, rules=rules)


def _merge(base: Document, child: Document) -> Document:
    """Layer *child* on top of *base*: child labels/variables win, rules concatenate.

    *base*'s rules are marked ``inherited=True`` — from *child*'s vantage point
    they come from a base (via ``!extends``), so an editor can tell inherited
    rules from the ones authored in the top document. *child*'s rules keep their
    own provenance (their ``inherited`` flag is left as-is)."""
    base = _restamp(base, inherited=True)
    return Document(
        labels={**base.labels, **child.labels},
        variables={**base.variables, **child.variables},
        rules=base.rules + child.rules,
        shift_x=child.shift_x or base.shift_x,
        # replay base directives then the child's: `=` in the child resets, while
        # `+=`/`-=` build on the inherited set (resolve_suffixes does the replay).
        suffix_ops=base.suffix_ops + child.suffix_ops,
        # last non-default wins, so a child can override an inherited !propagate.
        propagate=child.propagate if child.propagate != "none" else base.propagate,
    )


def merge_documents(base: Document, child: Document) -> Document:
    """Layer *child* on top of *base* (child labels/variables/rules win), the
    public form of the ``!extends`` merge.

    *base*'s rules are marked ``inherited=True`` so an editor can tell inherited
    rules from the ones authored in *child*; provenance (:class:`RuleSource`) is
    preserved on both sides. Lets a consumer build a layered document without
    reaching into private helpers.
    """
    return _merge(base, child)


def _abs(ref: str, base_dir) -> str:
    path = ref if os.path.isabs(ref) else os.path.join(base_dir or "", ref)
    return os.path.abspath(path)


def resolve_ref(ref: str, *, base_dir=None, search_paths=None) -> str | None:
    """The file *ref* would load from, or ``None`` if nothing answers it.

    The public form of the decision :func:`load_document` makes internally — a
    host that lets a user *edit* an inherited rule set needs the very path the
    engine read, not a re-implementation of the search order. It is also what
    lands in ``RuleSource.origin``, so the two can be compared directly.

    A ref with a path separator or an extension is a **path**, resolved against
    *base_dir*; a bare name is looked up on the search path (see
    :mod:`anchorsfactory.presets`). Returns an absolute path; the file exists.
    """
    named = presets.resolve(ref, search_paths=search_paths, base_dir=base_dir)
    if named is not None:
        return os.path.abspath(named)
    path = _abs(ref, base_dir)              # a path ref, or a name with no set behind it
    return path if os.path.isfile(path) else None


def _load(ref: str, base_dir, seen: tuple, search_paths=None) -> Document:
    path = resolve_ref(ref, base_dir=base_dir, search_paths=search_paths)
    if path is None and presets.is_name(ref):
        # A name nothing answers: say where we looked, and raise the type that
        # tells a host "configuration", not "bad rule text" / "bad path".
        raise presets._missing(ref, presets._EXT, search_paths, base_dir)
    if path is None:                        # a path ref that isn't there — let open() say so
        path = _abs(ref, base_dir)
    # The resolved file's own directory becomes the base for anything *it*
    # references, so a set can sit anywhere and still reach its neighbours.
    ident, this_dir = path, os.path.dirname(path)
    doc = parse_dsl_file(path) if path.endswith(presets._PATH_EXTS) else parse_file(path)

    # Tag this document's own rules with where they came from, so an editor can
    # route a rule back to its file/preset (and `_merge` flips base rules to
    # inherited from there).
    doc = _restamp(doc, origin=ident)

    if ident in seen:
        raise ValueError(f"!extends cycle at {ref}")
    seen = seen + (ident,)

    if not doc.extends:
        return doc
    merged = Document()
    for base_ref in doc.extends:        # bases first, in order...
        merged = _merge(merged, _load(base_ref, this_dir, seen, search_paths))
    return _merge(merged, doc)          # ...then this file on top


def load_document(rules: str, base_dir: str | None = None,
                  search_paths=None) -> Document:
    """Resolve a rules reference (a bare set name or a file path) to a Document,
    inheriting any ``!extends`` bases. Legacy ``.txt`` files have no inheritance.

    *base_dir* anchors a relative *rules* path and relative top-level ``!extends``
    refs; each base then anchors its **own** nested relative ``!extends`` to its
    own directory (the chain is threaded through). Absolute paths ignore it.
    Defaults to the process cwd (``None``). A host editing rules in a buffer
    should pass the rules file's directory so relative refs resolve as they would
    on disk.

    *search_paths* are the directories a **bare name** is looked up in — the
    package bundles no rule sets, so a host supplies its own library here (or
    process-wide via :func:`anchorsfactory.presets.set_search_paths` /
    ``$ANCHORSFACTORY_RULES_PATH``). A name is tried in *base_dir* first, so a
    set can ``!extends`` a neighbour with no configuration at all.
    """
    return _load(rules, base_dir=base_dir, seen=(), search_paths=search_paths)


def dump_existing_anchors(font) -> str:
    """Serialise a font's current anchors to a restorable text block.

    Format mirrors the legacy backup: ``glyph=name:x:y,name:x:y`` per line.
    """
    lines = []
    for glyph in font:
        if glyph.anchors:
            parts = [f"{a.name}:{int(round(a.x))}:{int(round(a.y))}" for a in glyph.anchors]
            lines.append(f"{glyph.name}=" + ",".join(parts))
    return "\n".join(lines)


def _output_path(source: str, output: str | None, in_place: bool) -> str | None:
    if in_place:
        return None                                   # font.save() overwrites source
    if output:
        return output
    root = source[:-1] if source.endswith(os.sep) else source
    stem = root[:-4] if root.lower().endswith(".ufo") else root
    return stem + ANCHORED_SUFFIX


def process_ufo(
    ufo_path: str,
    rules_path: str,
    *,
    output: str | None = None,
    in_place: bool = False,
    backup_dir: str | None = None,
    clear: bool = True,
    replace: bool = True,
    round_coords: bool = True,
    document=None,
    search_paths=None,
) -> str:
    """Apply rules to *ufo_path* and save. Returns the saved path.

    Pass a pre-loaded *document* to skip loading (e.g. when processing many
    fonts with the same rules); otherwise *rules_path* is loaded, with
    *search_paths* resolving it if it is a bare set name.
    """
    font = OpenFont(ufo_path)
    doc = (document if document is not None
           else load_document(rules_path, search_paths=search_paths))
    log.info("%s %s", font.info.familyName, font.info.styleName)

    if backup_dir is not None:
        os.makedirs(backup_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(ufo_path.rstrip(os.sep)))[0]
        backup_path = os.path.join(backup_dir, f"{stem}.anchors-backup.txt")
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(dump_existing_anchors(font))
        log.info("Backed up existing anchors to %s", backup_path)

    apply_document(font, doc, clear=clear, replace=replace, round_coords=round_coords)

    out = _output_path(ufo_path, output, in_place)
    if out is None:
        font.save()
        out = font.path
    else:
        font.save(out)
    log.info("Saved %s", out)
    return out
