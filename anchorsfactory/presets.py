"""Access to the rule presets bundled with the package (``anchorsfactory/rules``).

Bundled as package data and read via :mod:`importlib.resources`, so they work
from any install location (wheel, zip, editable). Referenced by bare name in
``!extends`` / ``--rules`` (e.g. ``default``, ``default-italics``).
"""

from __future__ import annotations

from importlib.resources import files

_RULES = "anchorsfactory.rules"
_EXT = ".anchors"
# Extensions that mark a `--rules`/`!extends` reference as a *file path* (DSL),
# not a bare preset name. `.anchors` is canonical; `.af`/`.dsl` stay recognised
# so pre-existing rule files keep working.
_PATH_EXTS = (".anchors", ".af", ".dsl")


def list_presets() -> list[str]:
    """Names of the bundled rule presets (without extension)."""
    out = []
    for entry in files(_RULES).iterdir():
        if entry.name.endswith(_EXT):
            out.append(entry.name[: -len(_EXT)])
    return sorted(out)


def is_preset(name: str) -> bool:
    """A bare name (no path separator / extension) that names a bundled preset."""
    if "/" in name or "\\" in name or name.endswith(_PATH_EXTS):
        return False
    return (files(_RULES) / f"{name}{_EXT}").is_file()


def preset_text(name: str) -> str:
    """Return the DSL text of a bundled preset, or raise KeyError."""
    res = files(_RULES) / f"{name}{_EXT}"
    if not res.is_file():
        raise KeyError(f"unknown preset {name!r}; available: {', '.join(list_presets())}")
    return res.read_text(encoding="utf-8")
