"""The Studio server: a dependency-free stdlib HTTP server that serves the
single-page UI and maps ``/api/<method>`` onto :meth:`.api.Studio.dispatch`.

The fonts are opened once and kept in memory; rule text is sent from the
browser on every edit, so the server is otherwise stateless, unless ``--save
PATH`` is given, in which case each valid edit's base layer is written back to
PATH. No font bytes ever leave the machine. The web Studio runs the same
:mod:`.api` in the browser instead (``web/``).
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from .. import speedups
from ..conditions import contexts_from_designspace
from ..presets import construction_text, has_construction, is_preset, set_search_paths
# re-exported: the session and its helpers lived here before api.py
from .api import (  # noqa: F401
    METHODS, Studio, _base_layer_text, _font_card, _font_state, _seed_rules,
    entry_context, location_text, parse_location_text,
)
from .demo import build_demo_font

log = logging.getLogger("anchorsfactory.studio")

_STATIC = files("anchorsfactory.studio").joinpath("static")

# read-only methods answer GET; everything else is a POST with a JSON body
_GET = {"state", "allglyphs"}


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

    def _method(self) -> str | None:
        """``/api/font/activate`` -> ``"font/activate"`` (None if not an API path)."""
        if not self.path.startswith("/api/"):
            return None
        method = self.path[len("/api/"):].split("?", 1)[0]
        return method if method in METHODS else None

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_static("index.html", "text/html; charset=utf-8")
        elif self.path.startswith("/static/"):
            rel = self.path[len("/static/"):].split("?", 1)[0]
            ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            self._send_static(rel, ctype)
        elif self._method() in _GET:
            self._send_json(*reversed(self.studio.dispatch(self._method())))
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        method = self._method()
        if method is None or method in _GET:
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) if length else b"{}")
        except ValueError:
            body = []                      # not an object: dispatch answers 400
        status, out = self.studio.dispatch(method, body)
        self._send_json(out, status)

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
                   help="rule set to open with: a .anchors path, or a bare name "
                        "resolved on --rules-path (default: 'default'; falls back "
                        "to a built-in seed when it resolves to nothing)")
    p.add_argument("--rules-path", action="append", metavar="DIR", default=None,
                   help="directory to resolve bare rule-set names in (repeatable; "
                        "defaults to $ANCHORSFACTORY_RULES_PATH). No rule sets ship "
                        "with the package — the samples are in examples/rules/")
    p.add_argument("--designspace", metavar="PATH",
                   help="open every source of this designspace as a master, each "
                        "with its location and style name for !if blocks")
    p.add_argument("--save", metavar="PATH",
                   help="autosave the (valid) base-layer rules to PATH on every edit; "
                        "reopen with -r PATH to resume")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    speedups.enable()                     # O(1) glyph lookups in fontParts (see speedups)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # The studio is a single-process app, so the rule search path is configured
    # once, here, and `is_preset`/`load_document` pick it up process-wide (that
    # includes `!extends <name>` inside an edited layer).
    if args.rules_path:
        set_search_paths(args.rules_path)
    rules_text = _seed_rules(args.rules)
    # A set's own composites, when it ships them: on a real font that fills
    # the constructions editor with the pipeline's second half. The demo font
    # has a handful of glyphs, so it keeps its own small seed.
    gc_text = (construction_text(args.rules)
               if is_preset(args.rules) and has_construction(args.rules) else None)
    contexts = contexts_from_designspace(args.designspace) if args.designspace else {}
    paths = list(args.ufo) or list(contexts)
    if paths:
        from fontParts.world import OpenFont
        studio = None
        for path in paths:
            font = OpenFont(path)
            family = getattr(font.info, "familyName", None)
            style = getattr(font.info, "styleName", None)
            name = f"{family} {style}".strip() if (family and style) else (family or Path(path).stem)
            context = contexts.get(os.path.abspath(path.rstrip(os.sep)))
            if contexts and context is None:
                raise SystemExit(f"{path} is not a source of {args.designspace}")
            if studio is None:
                studio = Studio(font, rules_text, name, save_path=args.save,
                                gc_text=gc_text, context=context)
            else:
                studio.add_font(font, name, context=context)
        if contexts:                                # a designspace opens on its first source
            studio.activate(0)
    else:
        studio = Studio(build_demo_font(), rules_text, "demo", save_path=args.save)
    serve(studio, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
