"""Access to the sample rule sets in ``examples/rules/``.

The package deliberately ships no rule files (see :mod:`anchorsfactory.presets`),
so the suite reads them from the repository the same way any host would — by
pointing a search path at a directory of its own.
"""

from __future__ import annotations

from pathlib import Path

from anchorsfactory import load_document
from anchorsfactory.presets import construction_text, preset_text

RULES_DIR = Path(__file__).resolve().parent.parent / "examples" / "rules"

#: Ready to hand to anything taking ``search_paths``.
SEARCH_PATHS = [str(RULES_DIR)]


def rules_text(name: str = "default") -> str:
    """The DSL text of a sample rule set."""
    return preset_text(name, search_paths=SEARCH_PATHS)


def gc_text(name: str = "default") -> str:
    """The GlyphConstruction half of a sample rule set."""
    return construction_text(name, search_paths=SEARCH_PATHS)


def rules_doc(name: str = "default"):
    """A sample rule set loaded as a Document (``!extends`` resolved)."""
    return load_document(name, search_paths=SEARCH_PATHS)


def rule_set_names() -> list[str]:
    """Every sample set in ``examples/rules/``."""
    return sorted(p.stem for p in RULES_DIR.glob("*.anchors"))
