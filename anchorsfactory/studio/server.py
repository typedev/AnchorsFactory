"""The Studio server: a dependency-free stdlib HTTP server that serves the
single-page UI and two JSON endpoints (``/api/state``, ``/api/compute``).

The font is opened once and kept in memory; rule text is sent from the browser
on every edit, so the server is otherwise stateless — unless ``--save PATH`` is
given, in which case each valid edit's base layer is written back to PATH. No
font bytes ever leave the machine.
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import shutil
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from .. import vocabulary
from ..presets import (construction_text, has_construction, is_preset,
                       list_presets, preset_text)
from .compose import build_composite_view
from .demo import build_demo_font, font_metrics
from .render import all_glyph_geometry, build_view
from .upload import load_uploaded_font

log = logging.getLogger("anchorsfactory.studio")

_STATIC = files("anchorsfactory.studio").joinpath("static")

# Seed for the GC-constructions editor: a couple of composites the demo font can
# assemble, so the "composites" tab has something to show on first open.
_DEFAULT_GC = (
    "# GlyphConstruction — assemble composites from the anchors above.\n"
    "#   composite = base + mark@anchor\n"
    "aacute = a + acute@top\n"
    "odieresis = o + dieresis@top\n"
)


def _seed_rules(rules: str) -> str:
    """The editable rule text to open with: a preset's source, or a file's."""
    if is_preset(rules):
        return preset_text(rules)
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


def _font_card(font, name: str) -> dict:
    """One entry of the loaded-font list (same as ``_font_state`` but keyed by
    ``name`` instead of ``font``)."""
    s = _font_state(font, name)
    s["name"] = s.pop("font")
    return s


class Studio:
    """Holds the loaded fonts and the state a session starts from.

    ``fonts`` is a list of ``{name, font, tmpdir, allglyphs}`` and ``active`` an
    index into it; the *active* font drives compute and the grid. ``lock``
    serialises the shared fonts across the threaded server (compute reads,
    add/activate/remove mutate), so every access takes it. ``font`` is a property
    onto the active entry so ``_compute``/``build_composite_view``/``all_glyphs`` need
    no change.
    """

    def __init__(self, font, rules_text: str, font_name: str, save_path=None,
                 gc_text: str | None = None):
        self.fonts = [{"name": font_name, "font": font, "tmpdir": None, "allglyphs": None}]
        self.active = 0
        self.rules_text = rules_text
        self.lock = threading.Lock()
        # When set (--save PATH), the base layer is written back here on every
        # valid compute, so edits survive across sessions and browsers.
        self.save_path = Path(save_path) if save_path else None
        self.state = {
            **_font_state(font, font_name),
            "fonts": [_font_card(font, font_name)],
            "active": 0,
            "presets": list_presets(),
            "presetTexts": {name: preset_text(name) for name in list_presets()},
            "rules": rules_text,
            "gc": gc_text or _DEFAULT_GC,
            # The DSL's surface words, straight from the library, so the editor's
            # completion/highlight tables cannot drift from the parser.
            "vocabulary": vocabulary.as_dict(),
            "save": str(self.save_path) if self.save_path else None,
        }

    @property
    def font(self):
        return self.fonts[self.active]["font"]

    def _sync_active(self):
        """Refresh the active-font slice + the font list in ``state``."""
        e = self.fonts[self.active]
        self.state.update(_font_state(e["font"], e["name"]))
        self.state["fonts"] = [_font_card(x["font"], x["name"]) for x in self.fonts]
        self.state["active"] = self.active

    def add_font(self, font, name: str, tmpdir=None):
        """Append a font and make it active."""
        self.fonts.append({"name": name, "font": font, "tmpdir": tmpdir, "allglyphs": None})
        self.active = len(self.fonts) - 1
        self._sync_active()

    def activate(self, i: int):
        if 0 <= i < len(self.fonts):
            self.active = i
            self._sync_active()

    def remove_font(self, i: int):
        """Drop a loaded font (never the last one), returning its tmpdir to clean
        up outside the lock."""
        if not (0 <= i < len(self.fonts)) or len(self.fonts) <= 1:
            return None
        entry = self.fonts.pop(i)
        if self.active >= len(self.fonts):
            self.active = len(self.fonts) - 1
        elif self.active > i:
            self.active -= 1
        self._sync_active()
        return entry.get("tmpdir")

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
            e["allglyphs"] = all_glyph_geometry(e["font"])
        return e["allglyphs"]


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, studio: Studio, **kwargs):
        self.studio = studio
        super().__init__(*args, **kwargs)

    # Quieter, single-line logging via our logger instead of stderr prints.
    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_static("index.html", "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._send_json(self.studio.state)
        elif self.path == "/api/allglyphs":
            with self.studio.lock:
                glyphs = self.studio.all_glyphs()
            self._send_json({"glyphs": glyphs})
        elif self.path.startswith("/static/"):
            rel = self.path[len("/static/"):].split("?", 1)[0]
            ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            self._send_static(rel, ctype)
        else:
            self._send_json({"error": "not found"}, status=404)

    def _send_static(self, rel, ctype):
        """Serve a file from the package's ``static/`` dir (traversal-safe)."""
        node = _STATIC
        for part in rel.split("/"):
            if part in ("", ".", ".."):
                self._send_json({"error": "not found"}, status=404)
                return
            node = node.joinpath(part)
        try:
            body = node.read_bytes()
        except (FileNotFoundError, IsADirectoryError, OSError):
            self._send_json({"error": "not found"}, status=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # served fresh each request → never let a browser cache a stale UI.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def do_POST(self):
        if self.path == "/api/compute":
            self._compute()
        elif self.path == "/api/font":
            self._load_font()
        elif self.path == "/api/font/activate":
            self._font_op(lambda body: self.studio.activate(int(body.get("index", 0))))
        elif self.path == "/api/font/remove":
            self._remove_font()
        else:
            self._send_json({"error": "not found"}, status=404)

    def _compute(self):
        try:
            body = self._read_json()
        except (ValueError, AttributeError):
            self._send_json({"ok": False, "problems": ["malformed request body"],
                             "diagnostics": [], "glyphs": {}}, status=400)
            return
        # a layer stack (bottom → top) or, for back-compat, a single rules string
        rules = body.get("layers") if isinstance(body.get("layers"), list) else body.get("rules", "")
        gc_text = body.get("gc", "")
        with self.studio.lock:
            view = build_view(self.studio.font, rules)
            # GlyphConstruction preview: assemble composites from the anchors just
            # computed (on a copy of the font — see compose.build_composite_view).
            if view.get("ok") and isinstance(rules, list) and gc_text.strip():
                comp = build_composite_view(self.studio.font, rules, gc_text)
                view["composites"] = comp["composites"]
                view["uncovered"] = comp.get("uncovered", [])
                if comp["problems"]:
                    view["problems"] = view.get("problems", []) + comp["problems"]
        # Autosave the base (bottom) layer only, and only when the rules are
        # valid — so the saved file is always reloadable.
        if view.get("ok"):
            self.studio.autosave(_base_layer_text(rules))
        self._send_json(view)

    def _load_font(self):
        """Accept a dropped UFO (files reconstructed from the browser) and ADD it
        as a new active font (previously loaded fonts are kept)."""
        try:
            payload = self._read_json()
            font, name, tmp = load_uploaded_font(payload.get("files", []),
                                                 payload.get("name", "font"))
        except ValueError as exc:                       # empty / non-UFO / malformed
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        except Exception as exc:                        # OpenFont / IO failure
            log.warning("font upload failed: %s", exc)
            self._send_json({"ok": False, "error": f"could not open font: {exc}"},
                            status=400)
            return
        with self.studio.lock:
            self.studio.add_font(font, name, tmp)
        self._send_json({"ok": True, "state": self.studio.state})

    def _font_op(self, op):
        """Run a font-list mutation under the lock and return the fresh state."""
        try:
            body = self._read_json()
        except (ValueError, AttributeError):
            self._send_json({"ok": False, "error": "malformed request body"}, status=400)
            return
        with self.studio.lock:
            op(body)
        self._send_json({"ok": True, "state": self.studio.state})

    def _remove_font(self):
        try:
            body = self._read_json()
        except (ValueError, AttributeError):
            self._send_json({"ok": False, "error": "malformed request body"}, status=400)
            return
        with self.studio.lock:
            tmp = self.studio.remove_font(int(body.get("index", 0)))
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        self._send_json({"ok": True, "state": self.studio.state})


def serve(studio: Studio, host: str, port: int):
    handler = partial(_Handler, studio=studio)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print(f"anchorsfactory studio → {url}  (font: {studio.state['font']}, Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="anchorsfactory-studio",
        description="Visual debugger for anchor rules (opens a local web UI).",
    )
    p.add_argument("ufo", nargs="*",
                   help="one or more .ufo to debug (e.g. a Regular + Italic pair); "
                        "omitted → built-in demo font")
    p.add_argument("-r", "--rules", default="default",
                   help="preset name or .anchors path to open with (default: 'default')")
    p.add_argument("--save", metavar="PATH",
                   help="autosave the (valid) base-layer rules to PATH on every edit; "
                        "reopen with -r PATH to resume")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    rules_text = _seed_rules(args.rules)
    # A preset's own composites, when it ships them: on a real font that fills
    # the constructions editor with the pipeline's second half. The demo font
    # has a handful of glyphs, so it keeps its own small seed.
    gc_text = (construction_text(args.rules)
               if is_preset(args.rules) and has_construction(args.rules) else None)
    if args.ufo:
        from fontParts.world import OpenFont
        studio = None
        for path in args.ufo:
            font = OpenFont(path)
            family = getattr(font.info, "familyName", None)
            style = getattr(font.info, "styleName", None)
            name = f"{family} {style}".strip() if (family and style) else (family or Path(path).stem)
            if studio is None:
                studio = Studio(font, rules_text, name, save_path=args.save,
                                gc_text=gc_text)
            else:
                studio.add_font(font, name)
    else:
        studio = Studio(build_demo_font(), rules_text, "demo", save_path=args.save)
    serve(studio, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
