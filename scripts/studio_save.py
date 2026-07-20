#!/usr/bin/env python
"""Dev launcher: Studio seeded from the ``default`` preset, autosaving to a file.

A thin wrapper over ``studio_dev`` that wires up ``--save`` so a debugging
session persists to a local file across restarts *and* browsers (unlike the
browser-only ``localStorage`` that plain ``make studio`` relies on):

  - first run  → the ``default`` preset seeds the base layer;
  - every valid edit → written back to the save file;
  - later runs → resume from that file (its evolved copy of ``default``).

The save file defaults to ``dev/studio-rules.anchors`` (``dev/`` is gitignored — a
natural home for a local working copy). Override it with ``-f/--file``; a
``.ufo`` and the usual ``studio_dev`` flags (``--port``/``--host``/``--headless``)
pass straight through.

    python scripts/studio_save.py                       # dev/studio-rules.anchors
    python scripts/studio_save.py MyFont.ufo            # + a real UFO
    python scripts/studio_save.py -f my.anchors --port 8770  # a file of your choice

Or via make:  make studio-save  [ARGS="..."]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import the sibling launcher whether run as a script or a module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_dev  # noqa: E402

DEFAULT_SAVE = Path("dev/studio-rules.anchors")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="studio_save",
        description="Launch Studio from the default rule set, autosaving edits to a file.")
    ap.add_argument("-f", "--file", default=str(DEFAULT_SAVE), metavar="PATH",
                    help=f"file to autosave the base rules to and resume from "
                         f"(default: {DEFAULT_SAVE})")
    # Everything else (a ufo positional, --port/--host/--headless) is forwarded
    # to studio_dev untouched; we only own -r/--save here.
    args, passthrough = ap.parse_known_args(argv)

    save = Path(args.file)
    save.parent.mkdir(parents=True, exist_ok=True)
    # Resume from the file once it exists; until then, seed from the `default` set.
    seed = str(save) if save.exists() else "default"

    return studio_dev.main([*passthrough, "-r", seed, "--save", str(save)])


if __name__ == "__main__":
    raise SystemExit(main())
