#!/usr/bin/env python
"""Dev launcher for the Studio: start the server and open it in a
Playwright-driven Chromium window in one command.

The server runs in-process (a daemon thread), so there is no port to clean up:
closing the browser window — or pressing Ctrl-C in the terminal — stops
everything. Playwright + its Chromium are dev-only (``make browsers``); the
shipped package never depends on them.

    python scripts/studio_dev.py                 # demo font, default rules
    python scripts/studio_dev.py MyFont.ufo      # debug a UFO
    python scripts/studio_dev.py -r my.af --port 8770
    python scripts/studio_dev.py --headless      # no window (smoke check)

Or via make:  make studio  ARGS="MyFont.ufo -r my.af"
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from functools import partial
from http.server import ThreadingHTTPServer


def _build_studio(args):
    from anchorsfactory.studio.demo import build_demo_font
    from anchorsfactory.studio.server import Studio, _seed_rules

    rules_text = _seed_rules(args.rules)
    if args.ufo:
        from fontParts.world import OpenFont
        font = OpenFont(args.ufo)
        name = getattr(font.info, "familyName", None) or args.ufo
    else:
        font = build_demo_font()
        name = "demo"
    return Studio(font, rules_text, name), name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="studio_dev", description="Launch Studio and open it in a browser window.")
    ap.add_argument("ufo", nargs="?", help="a .ufo to debug; omitted → built-in demo font")
    ap.add_argument("-r", "--rules", default="default",
                    help="preset name or .af path to open with (default: 'default')")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--headless", action="store_true",
                    help="run Chromium headless (no window) — e.g. a launch smoke check")
    args = ap.parse_args(argv)

    from anchorsfactory.studio.server import _Handler

    studio, name = _build_studio(args)
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), partial(_Handler, studio=studio))
    except OSError as exc:                       # port already bound, usually
        print(f"cannot serve on {args.host}:{args.port} ({exc}); try --port <n>", file=sys.stderr)
        return 1
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://{args.host}:{args.port}/"
    print(f"studio → {url}  (font: {name})")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        httpd.shutdown()
        print("playwright is not installed — run `make browsers` (or `make venv`)", file=sys.stderr)
        return 1

    with sync_playwright() as p:
        # A sized, resizable window; headless has no window so it keeps a fixed
        # viewport (deterministic for a smoke check / screenshots).
        launch_kw = {} if args.headless else {"args": ["--window-size=1440,960"]}
        try:
            browser = p.chromium.launch(headless=args.headless, **launch_kw)
        except Exception as exc:                 # chromium not downloaded / no display
            httpd.shutdown()
            print(f"could not launch Chromium ({exc}); run `make browsers`", file=sys.stderr)
            return 1
        # no_viewport → the page tracks the real window size, so resizing reflows
        # the layout (a fixed viewport would lock it regardless of the window).
        page = (browser.new_page(viewport={"width": 1440, "height": 900}) if args.headless
                else browser.new_page(no_viewport=True))
        page.goto(url, wait_until="domcontentloaded")
        if args.headless:
            print("headless: server up and page loaded OK.")
        else:
            print("opened — close the window (or press Ctrl-C here) to stop.")
            try:
                while browser.is_connected() and not page.is_closed():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        try:
            browser.close()
        except Exception:
            pass

    httpd.shutdown()
    print("stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
