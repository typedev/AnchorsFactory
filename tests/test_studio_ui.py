"""End-to-end UI test for the studio, driven by a headless Playwright chromium.

Skips cleanly when Playwright (or its browser) isn't installed, so the public
suite stays green — run ``make browsers`` once to enable it locally. It starts
the real studio server (demo font, in a background thread on an ephemeral port)
and drives the actual page, guarding against the class of bug where an invalid
rule 500s the compute endpoint and silently freezes the UI.
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

pytest.importorskip("fontParts.world")
sync_api = pytest.importorskip("playwright.sync_api")

from anchorsfactory.presets import preset_text
from anchorsfactory.studio.demo import build_demo_font
from anchorsfactory.studio.server import Studio, _Handler


@pytest.fixture
def studio_url():
    """Run the studio server on an ephemeral port for the duration of a test."""
    studio = Studio(build_demo_font(), preset_text("default"), "demo")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Handler, studio=studio))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)


@pytest.fixture
def page(studio_url):
    """A chromium page pointed at a fresh (empty-localStorage) studio session."""
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:                      # browser not downloaded
            pytest.skip(f"playwright chromium unavailable ({exc}); run 'make browsers'")
        pg = browser.new_page(viewport={"width": 1400, "height": 900})
        pg.add_init_script("try{localStorage.clear()}catch(e){}")
        pg.goto(studio_url, wait_until="networkidle")
        pg.wait_for_selector("#problems .row", timeout=8000)
        yield pg
        browser.close()


def test_invalid_rule_reports_in_output_without_500(page):
    # An undefined-label rule parses but fails accumulation — it must come back as
    # an Output problem (HTTP 200), not a server exception that freezes the UI.
    statuses: list[int] = []
    page.on("response",
            lambda r: statuses.append(r.status) if "/api/compute" in r.url else None)

    ta = page.locator("#edBase textarea")
    ta.click()
    with page.expect_response(lambda r: "/api/compute" in r.url, timeout=8000):
        ta.fill("H = @missing")
    page.wait_for_timeout(300)

    assert statuses and all(s == 200 for s in statuses)     # never a 500
    out = page.inner_text("#output")
    assert "undefined label @missing" in out
    assert "OUTPUT" in out.upper()                          # the panel has a header


def test_output_panel_has_resizable_splitter(page):
    # The Output panel exists with a working splitter (the missing-splitter gripe).
    assert page.locator('.split[data-t="probh"]').count() == 1
    before = page.eval_on_selector(
        ".editor", "el => getComputedStyle(el).getPropertyValue('--probh')")
    box = page.locator('.split[data-t="probh"]').bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] - 60)   # drag up → taller
    page.mouse.up()
    after = page.eval_on_selector(
        ".editor", "el => getComputedStyle(el).getPropertyValue('--probh')")
    assert float(before[:-2]) < float(after[:-2])                 # panel grew
