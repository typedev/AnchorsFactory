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

from fontParts.world import OpenFont

from . import presets
from .apply import apply_document
from .dsl import parse_dsl, parse_dsl_file
from .model import Document
from .parser import parse_file

log = logging.getLogger(__name__)

ANCHORED_SUFFIX = "_anchored.ufo"


def _merge(base: Document, child: Document) -> Document:
    """Layer *child* on top of *base*: child labels win, rules concatenate."""
    return Document(
        labels={**base.labels, **child.labels},
        rules=base.rules + child.rules,
        shift_x=child.shift_x or base.shift_x,
        suffixes=list(dict.fromkeys(base.suffixes + child.suffixes)),
    )


def _load(ref: str, base_dir, seen: tuple) -> Document:
    if presets.is_preset(ref):
        ident, this_dir = f"preset:{ref}", None
        doc = parse_dsl(presets.preset_text(ref).splitlines())
    else:
        path = ref if os.path.isabs(ref) else os.path.join(base_dir or "", ref)
        ident = os.path.abspath(path)
        this_dir = os.path.dirname(ident)
        doc = parse_dsl_file(path) if path.endswith((".af", ".dsl")) else parse_file(path)

    if ident in seen:
        raise ValueError(f"!extends cycle at {ref}")
    seen = seen + (ident,)

    if not doc.extends:
        return doc
    merged = Document()
    for base_ref in doc.extends:        # bases first, in order...
        merged = _merge(merged, _load(base_ref, this_dir, seen))
    return _merge(merged, doc)          # ...then this file on top


def load_document(rules: str) -> Document:
    """Resolve a rules reference (preset name or file path) to a Document,
    inheriting any ``!extends`` bases. Legacy ``.txt`` files have no inheritance.
    """
    return _load(rules, base_dir=None, seen=())


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
) -> str:
    """Apply rules to *ufo_path* and save. Returns the saved path.

    Pass a pre-loaded *document* to skip loading (e.g. when processing many
    fonts with the same rules); otherwise *rules_path* is loaded.
    """
    font = OpenFont(ufo_path)
    doc = document if document is not None else load_document(rules_path)
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
