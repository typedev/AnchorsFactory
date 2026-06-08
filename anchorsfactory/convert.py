"""Convert a legacy ``.txt`` rule file to the new DSL (docs/anchor-rules.md).

Reuses the IR as the bridge: parse the legacy file to a :class:`Document`
(via :mod:`anchorsfactory.parser`), then render that Document back out in the
new surface syntax. Rendering relies on the model's ``__str__``, which already
emits canonical new-syntax tokens.

Note: rule lines come out with anchors inlined (the legacy parser expands
label references), so the result is faithful but not re-compressed — you can
hand-edit it to use labels / ranges afterwards.
"""

from __future__ import annotations

from .dsl import parse_dsl
from .model import resolve_suffixes
from .parser import parse_file


def render_selector(sel) -> str:
    return str(sel)


def render_document(doc) -> str:
    lines: list[str] = []
    if doc.shift_x:
        lines.append(f"!shiftx = {doc.shift_x}")
    spec = resolve_suffixes(doc.suffix_ops)
    if spec.all:
        line = "!suffixes = all"
        if spec.deny:
            line += " except " + ", ".join(spec.deny)
        lines.append(line)
    else:
        suffixes = [s for s in spec.items if s]
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


def verify_conversion(legacy_path: str) -> list[str]:
    """Round-trip check: legacy -> new text -> IR must equal the legacy IR.

    Returns a list of human-readable mismatches (empty = lossless). Guarantees
    the conversion preserved every rule, label and directive.
    """
    legacy = parse_file(legacy_path)
    roundtrip = parse_dsl(render_document(legacy).splitlines())
    problems = []
    if roundtrip.rules != legacy.rules:
        problems.append("rules differ after round-trip")
    if roundtrip.labels != legacy.labels:
        problems.append("labels differ after round-trip")
    if roundtrip.shift_x != legacy.shift_x:
        problems.append("shift_x differs after round-trip")
    if resolve_suffixes(roundtrip.suffix_ops) != resolve_suffixes(legacy.suffix_ops):
        problems.append("suffixes differ after round-trip")
    return problems


def main(argv=None) -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(
        prog="anchorsfactory-convert",
        description="Convert a legacy .txt rule file to the new DSL.",
    )
    p.add_argument("legacy", help="path to the legacy .txt rule file")
    p.add_argument("-o", "--output", help="write here instead of stdout")
    p.add_argument("--no-verify", action="store_true",
                   help="skip the lossless round-trip check")
    args = p.parse_args(argv)

    text = convert_file(args.legacy)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)

    if not args.no_verify:
        problems = verify_conversion(args.legacy)
        if problems:
            for msg in problems:
                print(f"verify: {msg}", file=sys.stderr)
            return 1
        print("verify: round-trip OK — conversion is lossless", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
