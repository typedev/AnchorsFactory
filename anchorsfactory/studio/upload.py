"""Reconstruct a dropped UFO on the server side.

A UFO is a *directory* (a bundle of plists + one ``.glif`` per glyph), so the
browser sends every file with its relative path; here we write them back into a
fresh temp dir, expand any dropped ``.zip``/``.ufoz``, locate the ``.ufo`` root,
and open it. Everything stays local — the temp dir lives only for the session
and is replaced on the next drop.

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


def load_uploaded_font(files, name: str = "font"):
    """Rebuild and open a UFO from browser-uploaded *files*.

    *files* is a list of ``{"path": <relative path>, "data": <base64>}``. Returns
    ``(font, family_name, tmpdir)``; the caller owns *tmpdir* and should remove it
    when the font is replaced. Raises ``ValueError`` on an empty / malformed /
    non-UFO upload (the temp dir is cleaned up first).
    """
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
        _expand_archives(tmp)
        ufo = _find_ufo(tmp)
        if ufo is None:
            raise ValueError("no .ufo found — drop a .ufo folder or a .zip containing one")
        # defcon/fontParts keys a UFO by its .ufo extension; give the fallback one.
        if not ufo.lower().endswith(".ufo"):
            renamed = ufo + ".ufo"
            os.rename(ufo, renamed)
            ufo = renamed
        font = OpenFont(ufo)
        family = getattr(font.info, "familyName", None) or os.path.basename(ufo)
        return font, family, tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
