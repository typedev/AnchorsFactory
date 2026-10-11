"""Opt-in speedups for third-party font objects.

fontParts' default environment (``fontshell``, backed by defcon) answers
``name in font`` and ``font[name]`` by rebuilding the tuple of **every**
normalized glyph name on each call. ``font[name]`` does that twice: once on the
font and once on its default layer. Component drawing goes through the same
path. On a font of a few thousand glyphs that is most of the time the engine
spends: the Studio's view of a 3060-glyph font drops from about 1.0 s to
0.4 s with the check below.

:func:`enable` answers membership from the defcon object directly (a dict
lookup). The result is identical, since fontParts has already normalized the
name by then. Nothing is patched unless the fontshell classes still inherit
fontParts' generic implementation, so a fontParts release that fixes this
itself is left alone. This is a process-wide change to a library we do not
own, so it is **never applied on import**. The applications in this package
(the CLI, the Studio) call it, and a host can call it once at startup.
"""

from __future__ import annotations

_applied = False


def _defcon_contains(self, name, **kwargs):
    return name in self.naked()


def enable() -> bool:
    """Make ``name in font`` / ``font[name]`` O(1) for fontParts' fontshell
    objects. Returns whether the patch is in effect (idempotent; ``False``
    when fontParts is missing or already overrides the lookup itself)."""
    global _applied
    if _applied:
        return True
    try:
        from fontParts.fontshell.font import RFont
        from fontParts.fontshell.layer import RLayer
    except ImportError:
        return False
    targets = [cls for cls in (RFont, RLayer) if "_contains" not in vars(cls)]
    if len(targets) != 2:
        return False                   # fontParts provides its own: leave it
    for cls in targets:
        cls._contains = _defcon_contains
    _applied = True
    return True
