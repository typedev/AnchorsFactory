"""Command-line interface for AnchorsFactory.

Replaces the legacy module-level script and batch.py. Accepts one or more
UFO paths (a directory expands to its ``*.ufo`` files), applies a rule file,
and saves — safely by default (never overwriting the source unless asked).

Logging is configured here, at the application entry point — never via
``logging.basicConfig`` inside the library — so batch runs get a clean,
per-font log file instead of everything landing in the first font's log.
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import sys
from datetime import datetime

from .apply import validate_document
from .runner import load_document, process_ufo

log = logging.getLogger("anchorsfactory")


def _expand_inputs(paths: list[str]) -> list[str]:
    ufos: list[str] = []
    for p in paths:
        if os.path.isdir(p) and not p.lower().endswith(".ufo"):
            ufos.extend(sorted(glob.glob(os.path.join(p, "*.ufo"))))
        else:
            ufos.append(p)
    return ufos


def _setup_console_logging(verbose: bool) -> None:
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    log.addHandler(handler)


def _font_log_handler(log_dir: str, ufo_path: str) -> logging.Handler:
    os.makedirs(log_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(ufo_path.rstrip(os.sep)))[0]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    handler = logging.FileHandler(os.path.join(log_dir, f"{ts}_{stem}.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    return handler


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="anchorsfactory",
        description="Place anchors in UFO fonts from a rule file.",
    )
    p.add_argument("ufo", nargs="+", help="UFO file(s) or a directory of UFOs")
    p.add_argument("-r", "--rules", required=True,
                   help="anchor rules: a file path, or a bare set name looked up "
                        "in --rules-path")
    p.add_argument("--rules-path", action="append", metavar="DIR", default=None,
                   help="directory to resolve bare rule-set names in (repeatable; "
                        "defaults to $ANCHORSFACTORY_RULES_PATH). No rule sets ship "
                        "with the package — see examples/rules/ in the repository")
    out = p.add_mutually_exclusive_group()
    out.add_argument("-o", "--output", help="output UFO path (single input only)")
    out.add_argument("--in-place", action="store_true", help="overwrite the source UFO")
    p.add_argument("--backup-dir", help="dump existing anchors here before applying")
    p.add_argument("--keep-existing", action="store_true",
                   help="do not clear existing anchors before applying")
    p.add_argument("--no-round", action="store_true", help="keep fractional anchor coordinates")
    p.add_argument("--log-dir", help="write a per-font log file into this directory")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_console_logging(args.verbose)

    inputs = _expand_inputs(args.ufo)
    if not inputs:
        log.error("no UFO inputs found")
        return 2
    if args.output and len(inputs) > 1:
        log.error("--output cannot be used with multiple inputs; use --in-place or default naming")
        return 2

    # Load + validate the rules once, up front: fail fast on rule errors before
    # touching any font.
    try:
        document = load_document(args.rules, search_paths=args.rules_path)
    except Exception as e:  # noqa: BLE001 — surface a clean message, not a traceback
        log.error("cannot load rules %s: %s", args.rules, e)
        return 2
    problems = validate_document(document)
    if problems:
        for msg in problems:
            log.error("rules: %s", msg)
        return 2

    failures = 0
    for ufo in inputs:
        fh = _font_log_handler(args.log_dir, ufo) if args.log_dir else None
        if fh:
            log.addHandler(fh)
        try:
            process_ufo(
                ufo, args.rules,
                output=args.output,
                in_place=args.in_place,
                backup_dir=args.backup_dir,
                clear=not args.keep_existing,
                round_coords=not args.no_round,
                document=document,
            )
        except Exception as e:  # noqa: BLE001 — report per-font, continue the batch
            log.error("Failed on %s: %s", ufo, e)
            failures += 1
        finally:
            if fh:
                log.removeHandler(fh)
                fh.close()

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
