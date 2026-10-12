"""The Studio's API: the session state and one call per endpoint, as plain
JSON-ready dicts.

Two transports use it unchanged. The local server (:mod:`.server`) maps
``POST /api/<method>`` onto :meth:`Studio.dispatch`. The web Studio runs the
same module in Pyodide inside a Web Worker and calls :meth:`Studio.dispatch`
directly, so the browser app and the local app cannot drift apart.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from dataclasses import replace
from pathlib import Path

from .. import __version__, presets, vocabulary
from ..conditions import RuleContext
from ..presets import is_preset, list_presets, preset_text
from .compose import GC_LABEL, build_composite_view, gc_inactive_lines, masters_report
from .demo import font_metrics
from .render import all_glyph_geometry, build_view

log = logging.getLogger("anchorsfactory.studio")

# Seed for the GC-constructions editor: a couple of composites the demo font can
# assemble, so the "composites" tab has something to show on first open.
_DEFAULT_GC = (
    "# GlyphConstruction — assemble composites from the anchors above.\n"
    "#   composite = base + mark@anchor\n"
    "aacute = a + acute@top\n"
    "odieresis = o + dieresis@top\n"
)

# Seed for the rules editor when `-r` names a set the search path can't answer
# (the out-of-the-box case: nothing is bundled). Enough to show the pipeline
# working on the demo font, and to be edited over.
_DEFAULT_RULES = (
    "# Anchor rules — `name ( X Y )`, one line per selector.\n"
    "#   no rule sets ship with the package; point --rules-path at your own\n"
    "#   (the samples live in examples/rules/ in the repository).\n"
    "@ = top (box.center capHeight), bottom (box.center 0)\n"
    "@mark = _top (outline.centroid 0), _bottom (outline.centroid capHeight)\n"
    "{Lu} = @\n"
    "{Ll} = top (box.center xHeight), bottom (box.center 0)\n"
    "{Mn} = @mark\n"
    "{Sk} = @mark                      # legacy spacing accents (acute, dieresis)\n"
)


def _seed_rules(rules: str) -> str:
    """The editable rule text to open with: a named set's source, or a file's.

    No rule sets ship with the package, so the default ``-r default`` resolves to
    nothing until a search path is configured — that opens on a small built-in
    seed rather than failing, the same way the constructions editor does.
    """
    if is_preset(rules):
        return preset_text(rules)
    if presets.is_name(rules):                  # a name nothing on the path answers
        log.warning("no rule set %r on the search path (%s); opening a built-in seed. "
                    "Point --rules-path at a directory of .anchors files — the "
                    "samples are in examples/rules/ in the repository.",
                    rules, ", ".join(presets.search_paths()) or "empty")
        return _DEFAULT_RULES
    with open(rules, encoding="utf-8") as fh:
        return fh.read()


def _base_layer_text(rules) -> str:
    """The base (bottom) layer's source from a compute payload — a layer stack
    ``[{name,text}, ...]`` bottom→top, or a bare rules string (single layer)."""
    if isinstance(rules, str):
        return rules
    if rules:
        first = rules[0]
        return first.get("text", "") if isinstance(first, dict) else str(first)
    return ""


def _font_state(font, name: str) -> dict:
    """The font-dependent slice of the client state (the *active* font)."""
    return {
        "font": name,
        "unitsPerEm": float(getattr(font.info, "unitsPerEm", 1000) or 1000),
        "italicAngle": float(font.info.italicAngle or 0),
        "metrics": font_metrics(font),
    }


_LOC_TERM = re.compile(r"([A-Za-z_]\w*)\.(xvalue|uservalue)\s*=\s*(-?\d+(?:\.\d+)?|-?\.\d+)")


def parse_location_text(text: str) -> tuple[dict, dict]:
    """``"ital.xvalue=1, wght.uservalue = 700"`` -> ``(xvalues, uservalues)``.

    Terms are separated by commas, semicolons or whitespace; anything else is a
    ``ValueError`` naming the bad part, shown under the font card."""
    xvalues, uservalues = {}, {}
    pos, text = 0, text or ""
    for m in _LOC_TERM.finditer(text):
        gap = text[pos:m.start()]
        if gap.strip(" \t\n,;"):
            raise ValueError(f"cannot read {gap.strip()!r}; write AXIS.xvalue=N "
                             f"or AXIS.uservalue=N")
        axis, kind, value = m.groups()
        (xvalues if kind == "xvalue" else uservalues)[axis] = float(value)
        pos = m.end()
    if text[pos:].strip(" \t\n,;"):
        raise ValueError(f"cannot read {text[pos:].strip()!r}; write AXIS.xvalue=N "
                         f"or AXIS.uservalue=N")
    return xvalues, uservalues


def _fmt(v: float) -> str:
    return f"{v:g}"


def location_text(context: RuleContext) -> str:
    """A context's location in the form :func:`parse_location_text` reads."""
    terms = [f"{a}.xvalue={_fmt(v)}" for a, v in context.xvalues.items()]
    terms += [f"{a}.uservalue={_fmt(v)}" for a, v in context.uservalues.items()]
    return ", ".join(terms)


def entry_context(entry: dict) -> RuleContext:
    """The master a loaded font stands for: its base context (a designspace
    source's, or an empty one), with the location and style name typed into
    the font card layered on top. A missing style name is filled from the font
    at compute time (fontinfo, else "")."""
    ctx = entry.get("base") or RuleContext()
    if entry.get("location") is not None:
        xvalues, uservalues = parse_location_text(entry["location"])
        ctx = replace(ctx, xvalues=xvalues, uservalues=uservalues)
    if entry.get("styleName") is not None:
        ctx = replace(ctx, style_name=entry["styleName"])
    return ctx


def _font_card(font, name: str, entry: dict | None = None) -> dict:
    """One entry of the loaded-font list (same as ``_font_state`` but keyed by
    ``name`` instead of ``font``), plus the master it stands for: ``location``
    (as typed, or the designspace's), ``styleName`` (the override, or the
    designspace source's; ``None`` → fontinfo) and ``fontStyleName``."""
    s = _font_state(font, name)
    s["name"] = s.pop("font")
    entry = entry or {}
    base = entry.get("base") or RuleContext()
    s["location"] = (entry["location"] if entry.get("location") is not None
                     else location_text(base))
    s["styleName"] = (entry["styleName"] if entry.get("styleName") is not None
                      else base.style_name)
    s["fontStyleName"] = getattr(font.info, "styleName", None) or ""
    s["designspace"] = entry.get("base") is not None
    return s


class Studio:
    """Holds the loaded fonts and the state a session starts from.

    ``fonts`` is a list of ``{name, font, tmpdir, allglyphs}`` and ``active`` an
    index into it; the *active* font drives compute and the grid. ``lock``
    serialises the shared fonts across the threaded server (compute reads,
    add/activate/remove mutate); :meth:`dispatch` takes it, and so must any
    other caller. ``font`` is a property onto the active entry.
    """

    def __init__(self, font, rules_text: str, font_name: str, save_path=None,
                 gc_text: str | None = None, context: RuleContext | None = None):
        self.fonts = [{"name": font_name, "font": font, "tmpdir": None, "allglyphs": None,
                       "base": context, "location": None, "styleName": None, "paths": {}}]
        self.active = 0
        self.pending = None           # a drop with several designspaces, until one is chosen
        self.save_plan = None         # what anchors/plan computed, until commit
        # draw every outline of a newly loaded font during the load (the web
        # worker sets this: the load already shows progress, a compute does not)
        self.warm_on_load = False
        self.rules_text = rules_text
        self.lock = threading.Lock()
        # When set (--save PATH), the base layer is written back here on every
        # valid compute, so edits survive across sessions and browsers.
        self.save_path = Path(save_path) if save_path else None
        self.state = {
            **_font_state(font, font_name),
            "fonts": [_font_card(font, font_name, self.fonts[0])],
            "active": 0,
            "presets": list_presets(),
            "presetTexts": {name: preset_text(name) for name in list_presets()},
            "rules": rules_text,
            "gc": gc_text or _DEFAULT_GC,
            # The DSL's surface words, straight from the library, so the editor's
            # completion/highlight tables cannot drift from the parser.
            "vocabulary": vocabulary.as_dict(),
            "save": str(self.save_path) if self.save_path else None,
            "version": __version__,
        }

    @property
    def font(self):
        return self.fonts[self.active]["font"]

    @property
    def paths(self) -> dict:
        """The active font's ``{glyph: svg path}`` cache (outlines never change
        during a session, whatever the rules)."""
        return self.fonts[self.active].setdefault("paths", {})

    @property
    def context(self) -> RuleContext:
        """The master the active font stands for (see :func:`entry_context`).
        A location that does not parse is treated as none here; it is reported
        when it is set (:meth:`set_context`)."""
        try:
            return entry_context(self.fonts[self.active])
        except ValueError:
            return self.fonts[self.active].get("base") or RuleContext()

    def set_context(self, i: int, location, style_name):
        """Set font *i*'s location text and style-name override (``None`` keeps
        the designspace's / fontinfo's). Raises ``ValueError`` on a location
        that does not parse, leaving the font unchanged."""
        if not (0 <= i < len(self.fonts)):
            raise ValueError(f"no font {i}")
        entry = dict(self.fonts[i], location=location, styleName=style_name)
        entry_context(entry)                       # validate before storing
        self.fonts[i] = entry
        self._sync_active()

    def master_entries(self) -> list:
        """``[(name, font, RuleContext), ...]`` for every loaded font."""
        out = []
        for e in self.fonts:
            try:
                ctx = entry_context(e)
            except ValueError:
                ctx = e.get("base") or RuleContext()
            out.append((e["name"], e["font"], ctx))
        return out

    def _sync_active(self):
        """Refresh the active-font slice + the font list in ``state``."""
        e = self.fonts[self.active]
        self.state.update(_font_state(e["font"], e["name"]))
        self.state["fonts"] = [_font_card(x["font"], x["name"], x) for x in self.fonts]
        self.state["active"] = self.active

    def add_font(self, font, name: str, tmpdir=None, context: RuleContext | None = None):
        """Append a font and make it active."""
        self.fonts.append({"name": name, "font": font, "tmpdir": tmpdir, "allglyphs": None,
                           "base": context, "location": None, "styleName": None,
                           "paths": {}})
        self.active = len(self.fonts) - 1
        self._sync_active()

    def activate(self, i: int):
        if 0 <= i < len(self.fonts):
            self.active = i
            self._sync_active()

    def remove_font(self, i: int):
        """Drop a loaded font (never the last one), returning its tmpdir to clean
        up outside the lock, unless another loaded font still reads from it (the
        masters of one dropped designspace share it, and defcon loads glyphs
        lazily)."""
        if not (0 <= i < len(self.fonts)) or len(self.fonts) <= 1:
            return None
        entry = self.fonts.pop(i)
        if self.active >= len(self.fonts):
            self.active = len(self.fonts) - 1
        elif self.active > i:
            self.active -= 1
        self._sync_active()
        tmp = entry.get("tmpdir")
        return None if any(e.get("tmpdir") == tmp for e in self.fonts) else tmp

    def autosave(self, base_text: str) -> None:
        """Persist the base-layer rules to ``save_path`` (a no-op if unset).

        Only called for rules that resolved cleanly, so the file always stays
        loadable via ``-r <path>``. A write failure is logged, not fatal — a
        debugging session shouldn't die because the disk hiccuped."""
        if not self.save_path:
            return
        try:
            self.save_path.write_text(base_text, encoding="utf-8")
        except OSError as exc:
            log.warning("could not autosave rules to %s: %s", self.save_path, exc)

    def all_glyphs(self) -> list:
        """All-glyph geometry for the active font, computed once and cached on its
        entry (caller holds the lock)."""
        e = self.fonts[self.active]
        if e["allglyphs"] is None:
            e["allglyphs"] = all_glyph_geometry(e["font"], e.setdefault("paths", {}))
        return e["allglyphs"]

    # ------------------------------------------------------------------ #
    #  The API: one call per endpoint, ``(status, JSON-ready dict)``
    # ------------------------------------------------------------------ #

    def dispatch(self, method: str, body=None) -> tuple[int, dict]:
        """Run API *method* (``"state"``, ``"compute"``, ``"font/activate"``,
        ...) with the decoded JSON *body*. The status is an HTTP code: the
        server sends it as is, the web worker passes it to the page."""
        handler = _METHODS.get(method)
        if handler is None:
            return 404, {"error": "not found"}
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return 400, _malformed(method)
        return handler(self, body)

    def _api_state(self, body):
        return 200, self.state

    def _api_allglyphs(self, body):
        with self.lock:
            return 200, {"glyphs": self.all_glyphs()}

    def _api_compute(self, body):
        # a layer stack (bottom → top) or, for back-compat, a single rules string
        rules = body.get("layers") if isinstance(body.get("layers"), list) else body.get("rules", "")
        gc_text = body.get("gc", "") or ""
        with self.lock:
            # the master the active font stands for: what `!if` blocks see
            context = self.context.for_font(self.font)
            view = build_view(self.font, rules, context, self.paths)
            view["gcInactive"] = gc_inactive_lines(gc_text, context)
            view["gcLabel"] = GC_LABEL
            # GlyphConstruction preview: composites from the anchors just computed
            if view.get("ok") and isinstance(rules, list) and gc_text.strip():
                comp = build_composite_view(self.font, rules, gc_text, context, self.paths)
                view["composites"] = comp["composites"]
                view["uncovered"] = comp.get("uncovered", [])
                if comp["problems"]:
                    view["problems"] = view.get("problems", []) + comp["problems"]
        # Autosave the base (bottom) layer only, and only when the rules are
        # valid, so the saved file is always reloadable.
        if view.get("ok"):
            self.autosave(_base_layer_text(rules))
        return 200, view

    def _api_font(self, body):
        """Add a dropped font (its files, base64, as the browser sent them):
        one UFO, or the masters of a designspace (see :meth:`_open_tree`)."""
        from .upload import write_upload
        try:
            root = write_upload(body.get("files", []))
        except ValueError as exc:                       # empty / unsafe paths
            return 400, {"ok": False, "error": str(exc)}
        return self._open_tree(root)

    def open_font_tree(self, root: str) -> tuple[int, dict]:
        """Add the font(s) dropped under directory *root*. Not an HTTP
        endpoint: the web worker writes the dropped files into its own file
        system and calls this."""
        return self._open_tree(root)

    def _open_tree(self, root: str) -> tuple[int, dict]:
        """Open what was dropped under *root* (which the session then owns).

        A tree with one ``.designspace`` opens all its sources as masters, each
        with its location and style name for ``!if`` blocks. With several, the
        answer is ``{"ok": True, "choose": [paths]}`` and the tree waits in
        ``pending`` for ``font/designspace``. Without one, the first UFO opens
        as before."""
        from .upload import find_designspaces, open_font_tree
        try:
            designspaces = find_designspaces(root)
            if len(designspaces) > 1:
                with self.lock:
                    self._drop_pending()
                    self.pending = {"root": root, "choices": designspaces}
                return 200, {"ok": True, "choose": designspaces, "state": self.state}
            if designspaces:
                return self._add_designspace(root, designspaces[0])
            font, name = open_font_tree(root)
        except ValueError as exc:                       # no UFO / unreadable designspace
            shutil.rmtree(root, ignore_errors=True)
            return 400, {"ok": False, "error": str(exc)}
        except Exception as exc:                        # OpenFont / IO failure
            log.warning("font upload failed: %s", exc)
            shutil.rmtree(root, ignore_errors=True)
            return 400, {"ok": False, "error": f"could not open font: {exc}"}
        with self.lock:
            self.add_font(font, name, root)
            if self.warm_on_load:
                self.all_glyphs()
        return 200, {"ok": True, "state": self.state, "drop": os.path.basename(root)}

    def _add_designspace(self, root: str, rel: str) -> tuple[int, dict]:
        """Add every source of designspace *rel* (under *root*) as a master;
        the first becomes active. Sources that cannot be opened are listed in
        ``problems`` without failing the rest."""
        from .upload import open_designspace
        masters, problems = open_designspace(os.path.join(root, rel))
        if not masters:
            shutil.rmtree(root, ignore_errors=True)
            detail = "; ".join(problems) or "it has no sources"
            return 400, {"ok": False, "error": f"{rel}: no master could be opened: {detail}"}
        with self.lock:
            first = len(self.fonts)
            for font, name, context in masters:
                self.add_font(font, name, root, context=context)
            self.activate(first)
            if self.warm_on_load:
                self.all_glyphs()
        return 200, {"ok": True, "state": self.state, "designspace": rel,
                     "masters": len(masters), "problems": problems, "drop": os.path.basename(root)}

    def _api_designspace(self, body):
        """Answer a ``choose``: open designspace ``path`` from the pending drop,
        or (``path`` null) discard the drop."""
        with self.lock:
            pending, self.pending = self.pending, None
        if pending is None:
            return 400, {"ok": False, "error": "no dropped folder is waiting for a choice"}
        rel = body.get("path")
        if rel is None:
            shutil.rmtree(pending["root"], ignore_errors=True)
            return 200, {"ok": True, "state": self.state}
        if rel not in pending["choices"]:
            with self.lock:
                self.pending = pending                  # still waiting
            return 400, {"ok": False, "error": f"{rel!r} is not one of the dropped designspaces"}
        return self._add_designspace(pending["root"], rel)

    def _drop_pending(self):
        """Discard a drop still waiting for a designspace choice (lock held)."""
        if self.pending:
            shutil.rmtree(self.pending["root"], ignore_errors=True)
            self.pending = None

    def _api_activate(self, body):
        with self.lock:
            self.activate(int(body.get("index", 0)))
        return 200, {"ok": True, "state": self.state}

    def _api_remove(self, body):
        with self.lock:
            tmp = self.remove_font(int(body.get("index", 0)))
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        return 200, {"ok": True, "state": self.state}

    def _api_context(self, body):
        """Set a font's master location / style name (from its card)."""
        location, style = body.get("location"), body.get("styleName")
        try:
            with self.lock:
                self.set_context(int(body.get("index", 0)),
                                 location if isinstance(location, str) else None,
                                 style if isinstance(style, str) else None)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "state": self.state}

    def _api_masters(self, body):
        """Compare every loaded master's anchors/composites (on demand: it
        computes the whole stack once per font)."""
        layers = body.get("layers") if isinstance(body.get("layers"), list) else []
        with self.lock:
            return 200, masters_report(self.master_entries(), layers, body.get("gc", "") or "")

    # ------------------------------------------------------------------ #
    #  Writing anchors into the fonts (see save.py)
    # ------------------------------------------------------------------ #

    def _api_anchors_plan(self, body):
        """What writing the rules' anchors into every loaded master changes: per
        master the changed glyphs, plus the new (normalized) ``.glif`` texts the
        page writes. The plan is kept for ``anchors/commit`` / ``anchors/zip``."""
        from .save import plan_master
        layers = body.get("layers") if isinstance(body.get("layers"), list) else []
        masters, page_files, plan = [], [], []
        with self.lock:
            for i, entry in enumerate(self.fonts):
                target = _save_target(entry)
                if target is None:
                    continue
                mode, where = target
                card = {"index": i, "name": entry["name"], "mode": mode,
                        "ufo": where if mode == "page" else os.path.basename(where)}
                try:
                    ctx = entry_context(entry)
                except ValueError:
                    ctx = entry.get("base") or RuleContext()
                try:
                    result = plan_master(entry["font"], layers, ctx)
                except (ValueError, RuntimeError) as exc:
                    masters.append({**card, "glyphs": [], "problems": [str(exc)], "error": True})
                    continue
                masters.append({**card, "glyphs": result["glyphs"], "problems": result["problems"]})
                plan.append((i, mode, where, result["files"]))
                if mode == "page":
                    # `drop` names the dropped folder (the session directory the
                    # page wrote it under), so the page picks that folder's handle
                    drop = os.path.basename(entry["tmpdir"])
                    page_files += [{"drop": drop, "path": f"{where}/{f['file']}", "text": f["text"],
                                    "original": f["original"]} for f in result["files"]]
            self.save_plan = plan
        errors = [m for m in masters if m.get("error")]
        return 200, {"ok": not errors, "masters": masters, "files": page_files,
                     "python": sum(len(files) for _, mode, _, files in plan if mode == "python"),
                     "total": sum(len(files) for *_, files in plan)}

    def _api_anchors_commit(self, body):
        """The planned files are written (by the page): apply the anchors to the
        fonts in memory and their session copies; write the fonts opened from a
        path (local server) into their UFOs."""
        from .save import commit_master
        with self.lock:
            plan, self.save_plan = self.save_plan, None
            if not plan:
                return 400, {"ok": False, "error": "nothing planned: ask anchors/plan first"}
            written = 0
            for i, mode, _where, files in plan:
                if i < len(self.fonts):
                    commit_master(self.fonts[i]["font"], files, write_ufo=True)
                    written += len(files)
        return 200, {"ok": True, "written": written}


    def _api_anchors_zip(self, body):
        """The planned page files as a zip (for a browser that cannot write into
        the folder), paths as in the dropped folder."""
        import base64
        from .save import zip_files
        plan = self.save_plan
        if not plan:
            return 400, {"ok": False, "error": "nothing planned: ask anchors/plan first"}
        files = [(f"{where}/{f['file']}", f["text"]) for _, mode, where, fs in plan if mode == "page" for f in fs]
        return 200, {"ok": True, "data": base64.b64encode(zip_files(files)).decode("ascii")}


def _save_target(entry: dict) -> tuple[str, str] | None:
    """How a loaded font's files are written: ``("page", path under the drop)``
    for a dropped font (the page writes into the folder it opened), ``("python",
    ufo path)`` for one opened from a path (the local server writes it), or
    None for a font with no files (the placeholder demo)."""
    path = getattr(entry["font"], "path", None)
    if not path or not os.path.isdir(path):
        return None
    if entry.get("tmpdir"):
        return "page", os.path.relpath(path, entry["tmpdir"]).replace(os.sep, "/")
    return "python", path


def _malformed(method: str) -> dict:
    if method == "compute":
        return {"ok": False, "problems": ["malformed request body"],
                "diagnostics": [], "glyphs": {}}
    return {"ok": False, "error": "malformed request body"}


# method -> handler; the HTTP routes and the worker's calls are these names
_METHODS = {
    "state": Studio._api_state,
    "allglyphs": Studio._api_allglyphs,
    "compute": Studio._api_compute,
    "font": Studio._api_font,
    "font/designspace": Studio._api_designspace,
    "font/activate": Studio._api_activate,
    "font/remove": Studio._api_remove,
    "font/context": Studio._api_context,
    "masters": Studio._api_masters,
    "anchors/plan": Studio._api_anchors_plan,
    "anchors/commit": Studio._api_anchors_commit,
    "anchors/zip": Studio._api_anchors_zip,
}
METHODS = tuple(_METHODS)
