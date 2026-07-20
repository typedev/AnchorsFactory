"""Resolving a rule set referenced by **bare name** against a search path.

The package ships no rule files. Rules are data, not code: bundling them made
``list_presets()`` answer differently from a wheel than from a source checkout,
put the default set somewhere a user could not edit it, and let a change of
*data* ride out on a version of *code*. So the library carries the engine and
this resolver, and the **host carries the rules** — an editor points at its own
library, a user edits it freely, and upgrading AnchorsFactory never touches it.

A reference is a *name* when it has no path separator and no rule-file extension
(``default``); anything else is a path (``rules/default.anchors``, ``./x.af``).
A name is looked up in, in order:

1. *base_dir* — the directory of the file doing the referencing, so a set can
   ``!extends default`` its neighbour with no configuration at all;
2. the *search_paths* passed to the call;
3. the process-wide list, seeded from ``$ANCHORSFACTORY_RULES_PATH``
   (``os.pathsep``-separated) and settable with :func:`set_search_paths`.

The sample sets that used to ship in the wheel now live in the repository under
``examples/rules/`` — copy them and make them yours.
"""

from __future__ import annotations

import os

_EXT = ".anchors"
_GC_EXT = ".glyphsConstruction"
# Extensions that mark a `--rules`/`!extends` reference as a *file path* (DSL),
# not a bare rule-set name. `.anchors` is canonical; `.af`/`.dsl` stay recognised
# so pre-existing rule files keep working.
_PATH_EXTS = (".anchors", ".af", ".dsl")

_ENV_VAR = "ANCHORSFACTORY_RULES_PATH"

_search_paths: tuple[str, ...] | None = None


def search_paths() -> tuple[str, ...]:
    """The process-wide directories searched for a rule set named by bare name.

    Seeded from ``$ANCHORSFACTORY_RULES_PATH`` on first use; a host that would
    rather configure this in code calls :func:`set_search_paths`.
    """
    global _search_paths
    if _search_paths is None:
        raw = os.environ.get(_ENV_VAR, "")
        _search_paths = tuple(p for p in raw.split(os.pathsep) if p)
    return _search_paths


def set_search_paths(paths) -> None:
    """Replace the process-wide search path list."""
    global _search_paths
    _search_paths = tuple(os.fspath(p) for p in paths)


def add_search_path(path) -> None:
    """Append one directory to the process-wide search path list."""
    set_search_paths(search_paths() + (os.fspath(path),))


def _candidate_dirs(search_paths_arg, base_dir) -> tuple[str, ...]:
    """The directories to search, nearest first, without duplicates.

    An explicit *search_paths_arg* **replaces** the process-wide list rather than
    extending it, so a caller can pass ``[]`` to mean "nowhere but *base_dir*".
    """
    dirs: list[str] = []
    if base_dir:
        dirs.append(os.fspath(base_dir))
    dirs.extend(os.fspath(p) for p in
                (search_paths_arg if search_paths_arg is not None else search_paths()))
    seen, out = set(), []
    for d in dirs:
        key = os.path.abspath(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return tuple(out)


def is_name(ref: str) -> bool:
    """Whether *ref* is a bare rule-set name rather than a file path.

    A name has no path separator and no extension: ``default`` is a name,
    ``default.anchors``, ``old-rules.txt`` and ``rules/default`` are paths.
    Purely syntactic — it says nothing about whether the set can be found.
    """
    return not ("/" in ref or "\\" in ref or os.path.splitext(ref)[1])


def _find(name: str, ext: str, search_paths_arg, base_dir) -> str | None:
    if not is_name(name):
        return None
    for d in _candidate_dirs(search_paths_arg, base_dir):
        path = os.path.join(d, f"{name}{ext}")
        if os.path.isfile(path):
            return path
    return None


def resolve(name: str, *, search_paths=None, base_dir=None) -> str | None:
    """The file a bare rule-set *name* resolves to, or ``None``."""
    return _find(name, _EXT, search_paths, base_dir)


def is_preset(name: str, *, search_paths=None, base_dir=None) -> bool:
    """Whether *name* is a bare name that resolves to a rule set on the path."""
    return resolve(name, search_paths=search_paths, base_dir=base_dir) is not None


def list_presets(search_paths=None, base_dir=None) -> list[str]:
    """Names of the rule sets found on the search path."""
    out: set[str] = set()
    for d in _candidate_dirs(search_paths, base_dir):
        try:
            entries = os.listdir(d)
        except OSError:                      # missing / unreadable dir — skip it
            continue
        out.update(e[: -len(_EXT)] for e in entries if e.endswith(_EXT))
    return sorted(out)


def _missing(name: str, ext: str, search_paths_arg, base_dir) -> KeyError:
    dirs = _candidate_dirs(search_paths_arg, base_dir)
    where = ", ".join(dirs) if dirs else "(no rule search paths configured)"
    found = ", ".join(list_presets(search_paths_arg, base_dir)) or "none"
    return KeyError(
        f"no rule set {name!r} ({name}{ext}) on the search path; searched: {where}; "
        f"found there: {found}. Rule sets are not bundled with the package — pass a "
        f"path, set ${_ENV_VAR}, or configure search_paths."
    )


def preset_text(name: str, *, search_paths=None, base_dir=None) -> str:
    """The DSL text of a named rule set, or raise KeyError."""
    path = resolve(name, search_paths=search_paths, base_dir=base_dir)
    if path is None:
        raise _missing(name, _EXT, search_paths, base_dir)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def has_construction(name: str, *, search_paths=None, base_dir=None) -> bool:
    """Whether the named set ships a matching GlyphConstruction file — the other
    half of the pipeline (AnchorsFactory places the anchors, GlyphConstruction
    assembles the composites that hang off them)."""
    return _find(name, _GC_EXT, search_paths, base_dir) is not None


def construction_text(name: str, *, search_paths=None, base_dir=None) -> str:
    """The named set's GlyphConstruction text, or raise KeyError."""
    path = _find(name, _GC_EXT, search_paths, base_dir)
    if path is None:
        raise _missing(name, _GC_EXT, search_paths, base_dir)
    with open(path, encoding="utf-8") as fh:
        return fh.read()
