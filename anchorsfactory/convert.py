"""Convert a legacy ``.txt`` rule file to the new DSL (docs/DSL.md).

Reuses the IR as the bridge: parse the legacy file to a :class:`Document`
(via :mod:`anchorsfactory.parser`), then render that Document back out in the
new surface syntax. Rendering relies on the model's ``__str__``, which already
emits canonical new-syntax tokens.

Note: rule lines come out with anchors inlined (the legacy parser expands
label references), so the result is faithful but not re-compressed — you can
hand-edit it to use labels / ranges afterwards.
"""

from __future__ import annotations

from .model import GlyphName, Unicode, UnicodeRange, Glob, Category
from .parser import parse_file


def render_selector(sel) -> str:
    if isinstance(sel, GlyphName):
        return sel.name
    if isinstance(sel, Unicode):
        return f"U+{sel.codepoint:04X}"
    if isinstance(sel, UnicodeRange):
        return f"U+{sel.start:04X}..U+{sel.end:04X}"
    if isinstance(sel, Glob):
        return sel.pattern
    if isinstance(sel, Category):
        return f"{{{sel.value}}}"
    raise TypeError(f"unknown selector {sel!r}")


def render_document(doc) -> str:
    lines: list[str] = []
    if doc.shift_x:
        lines.append(f"!shiftx = {doc.shift_x}")
    suffixes = [s for s in doc.suffixes if s]
    if suffixes:
        lines.append("!suffixes = " + ", ".join(suffixes))
    if lines:
        lines.append("")

    if doc.labels:
        lines.append("# labels")
        for name, specs in doc.labels.items():
            lines.append(f"{name} = " + ", ".join(str(s) for s in specs))
        lines.append("")

    lines.append("# rules")
    for sel, op, specs in doc.rules:
        lines.append(f"{render_selector(sel)} {op.value} " + ", ".join(str(s) for s in specs))
    return "\n".join(lines) + "\n"


def convert_file(legacy_path: str) -> str:
    """Return the new-DSL text for a legacy rule file."""
    return render_document(parse_file(legacy_path))


def main(argv=None) -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(
        prog="anchorsfactory-convert",
        description="Convert a legacy .txt rule file to the new DSL.",
    )
    p.add_argument("legacy", help="path to the legacy .txt rule file")
    p.add_argument("-o", "--output", help="write here instead of stdout")
    args = p.parse_args(argv)

    text = convert_file(args.legacy)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
