"""Reconstruct a dropped font on the server side.

A UFO is a *directory* (a bundle of plists + one ``.glif`` per glyph), so the
browser sends every file with its relative path; here we write them back into a
fresh temp dir, expand any dropped ``.zip``/``.ufoz``, then open either one
UFO or the sources of a ``.designspace`` found in the tree. Everything stays
local; the temp dir lives as long as a font opened from it.

Paths coming from the browser are untrusted, so every write and every zip member
is confined to the temp dir (no ``..`` escape / zip-slip).
"""

from __future__ import annotations

import base64
import os
import shutil
import tempfile
import zipfile

from fontParts.world import OpenFont


def _safe_join(root: str, rel: str) -> str:
    """Join *rel* under *root*, rejecting anything that escapes the tree."""
    dest = os.path.normpath(os.path.join(root, rel))
    if dest != root and not dest.startswith(root + os.sep):
        raise ValueError(f"unsafe path in upload: {rel!r}")
    return dest


def _expand_archives(root: str) -> None:
    """Unzip any ``.zip``/``.ufoz`` written under *root*, in place (zip-slip safe)."""
    for dirpath, _dirs, files in list(os.walk(root)):
        for fn in files:
            if not fn.lower().endswith((".zip", ".ufoz")):
                continue
            path = os.path.join(dirpath, fn)
            with zipfile.ZipFile(path) as z:
                for member in z.namelist():
                    _safe_join(dirpath, member)          # validate before extracting
                z.extractall(dirpath)


def _find_ufo(root: str) -> str | None:
    """The ``.ufo`` directory in the reconstructed tree, if any (a dir named
    ``*.ufo``, else a dir holding ``metainfo.plist``)."""
    fallback = None
    for dirpath, _dirs, files in os.walk(root):
        if dirpath.lower().endswith(".ufo"):
            return dirpath
        if "metainfo.plist" in files and fallback is None:
            fallback = dirpath
    return fallback


def write_upload(files) -> str:
    """Write browser-uploaded *files* (``{"path": <relative path>, "data":
    <base64>}``) into a fresh temp dir and return it. The caller owns the dir.
    Raises ``ValueError`` on an empty upload or a path that escapes the dir
    (the dir is removed first)."""
    if not files:
        raise ValueError("no files received")
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="afstudio-"))
    try:
        for entry in files:
            rel = (entry.get("path") or "").lstrip("/")
            if not rel or rel.endswith("/"):
                continue
            dest = _safe_join(tmp, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(base64.b64decode(entry["data"]))
        return tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def load_uploaded_font(files, name: str = "font"):
    """Rebuild and open a UFO from browser-uploaded *files* (see
    :func:`write_upload`). Returns ``(font, family_name, tmpdir)``; the caller
    owns *tmpdir*. Raises ``ValueError`` on an empty / malformed / non-UFO
    upload (the temp dir is cleaned up first)."""
    tmp = write_upload(files)
    try:
        font, family = open_font_tree(tmp)
        return font, family, tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def find_designspaces(root: str) -> list:
    """The ``.designspace`` files under *root* (archives expanded first), as
    sorted paths relative to *root*. Dot-directories are skipped."""
    _expand_archives(root)
    found = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not d.lower().endswith(".ufo"))
        found += [os.path.relpath(os.path.join(dirpath, f), root)
                  for f in files if f.lower().endswith(".designspace")]
    return sorted(found)


def open_designspace(path: str):
    """Open every source UFO of the designspace at *path* as a master.

    Returns ``(masters, problems)``: ``masters`` is ``[(font, name, context)]``
    in source order, ``name`` being ``"<family> <style>"``; ``problems`` says
    which sources could not be opened (missing from the drop, or unreadable).
    Sparse-layer sources are skipped (see :func:`contexts_from_designspace`).
    """
    from ..conditions import contexts_from_designspace
    try:
        contexts = contexts_from_designspace(path)
    except Exception as exc:
        raise ValueError(f"cannot read {os.path.basename(path)}: {exc}") from exc
    masters, problems = [], []
    base = os.path.dirname(os.path.abspath(path))
    for ufo, context in contexts.items():
        rel = os.path.relpath(ufo, base)
        if not os.path.isdir(ufo):
            problems.append(f"{rel}: not found next to the designspace")
            continue
        try:
            font = OpenFont(ufo)
        except Exception as exc:
            problems.append(f"{rel}: could not open ({exc})")
            continue
        family = getattr(font.info, "familyName", None) or os.path.splitext(os.path.basename(ufo))[0]
        style = context.style_name or getattr(font.info, "styleName", None) or ""
        masters.append((font, f"{family} {style}".strip(), context))
    return masters, problems


def open_font_tree(root: str):
    """Open the UFO in the file tree under *root*, expanding any ``.zip`` /
    ``.ufoz`` there first. Returns ``(font, family_name)``; raises
    ``ValueError`` when there is no UFO. (The web Studio writes the dropped
    files under *root* itself and calls this directly.)"""
    _expand_archives(root)
    ufo = _find_ufo(root)
    if ufo is None:
        raise ValueError("no .ufo found — drop a .ufo folder or a .zip containing one")
    # defcon/fontParts keys a UFO by its .ufo extension; give the fallback one.
    if not ufo.lower().endswith(".ufo"):
        renamed = ufo + ".ufo"
        os.rename(ufo, renamed)
        ufo = renamed
    font = OpenFont(ufo)
    family = getattr(font.info, "familyName", None) or os.path.basename(ufo)
    return font, family
