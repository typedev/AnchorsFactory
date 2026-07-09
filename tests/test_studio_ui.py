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
        pg.wait_for_selector(".thumb", timeout=8000)   # grid rendered → first compute done
        yield pg
        browser.close()


def test_invalid_rule_reports_in_output_without_500(page):
    # An undefined-label rule parses but fails accumulation — it must come back as
    # an Output problem (HTTP 200), not a server exception that freezes the UI.
    statuses: list[int] = []
    page.on("response",
            lambda r: statuses.append(r.status) if "/api/compute" in r.url else None)

    ta = page.locator("#anchorEditors .lhost.active textarea")
    ta.click()
    with page.expect_response(lambda r: "/api/compute" in r.url, timeout=8000):
        ta.fill("H = @missing")
    page.wait_for_timeout(300)

    assert statuses and all(s == 200 for s in statuses)     # never a 500
    out = page.inner_text("#output")
    assert "undefined label @missing" in out
    assert "OUTPUT" in out.upper()                          # the panel has a header


def test_output_sleeps_when_clean_and_wakes_on_problems(page):
    # Clean rules → the Output panel sleeps (collapsed, not "bad").
    _set_rules(page, "H = top (box.center capHeight)")
    assert "open" not in (page.get_attribute("#output", "class") or "")
    # A broken rule → it auto-opens, reddens, and shows the problem.
    ta = page.locator("#anchorEditors .lhost.active textarea"); ta.click()
    with page.expect_response(lambda r: "/api/compute" in r.url, timeout=8000):
        ta.fill("H = @missing")
    page.wait_for_timeout(300)
    cls = page.get_attribute("#output", "class") or ""
    assert "open" in cls and "bad" in cls
    assert "undefined label @missing" in page.inner_text("#output")


def _set_rules(page, text):
    ta = page.locator("#anchorEditors .lhost.active textarea"); ta.click()
    with page.expect_response(lambda r: "/api/compute" in r.url, timeout=8000):
        ta.fill(text)
    page.wait_for_timeout(250)


def _names(page):
    return {b.inner_text() for b in page.query_selector_all(".thumb .cap b")}


def test_all_glyphs_tab_lists_every_glyph(page):
    # a single-glyph rule → only H is affected; the "all glyphs" tab shows the rest.
    _set_rules(page, "H = top (box.center capHeight)")
    assert _names(page) == {"H"}                          # default "anchored" tab

    with page.expect_response(lambda r: "/api/allglyphs" in r.url, timeout=8000):
        page.locator("#gridtabs .tab", has_text="all glyphs").click()
    page.wait_for_timeout(250)
    allnames = _names(page)
    assert "H" in allnames and "acute" in allnames        # anchored + untouched together
    assert len(allnames) >= 10
    assert page.inner_text("#count").startswith("all ·")


def test_show_unused_reveals_untouched_glyphs(page):
    _set_rules(page, "H = top (box.center capHeight)")
    assert _names(page) == {"H"}                            # anchored tab: only the touched glyph
    # "show unused" (on the anchored tab) reveals the rest alongside H (drawn dimmed)
    with page.expect_response(lambda r: "/api/allglyphs" in r.url, timeout=8000):
        page.check("#unusedcb")
    page.wait_for_timeout(250)
    names = _names(page)
    assert "H" in names                                    # the anchored glyph stays
    assert "acute" in names                                # untouched glyphs now shown
    assert page.inner_text("#count").startswith("anchored + unused ·")


def test_selecting_unaffected_glyph_inspects_it(page):
    _set_rules(page, "H = top (box.center capHeight)")
    with page.expect_response(lambda r: "/api/allglyphs" in r.url, timeout=8000):
        page.locator("#gridtabs .tab", has_text="all glyphs").click()
    page.wait_for_timeout(200)
    page.locator(".thumb .cap b", has_text="O").first.click()   # O is unaffected here
    page.wait_for_timeout(200)
    assert page.locator("#readout h3").inner_text() == "O"
    assert page.locator("#readout .anchor-card").count() == 0   # no anchors, still inspectable
    assert page.locator("#canvas svg").count() == 1            # outline drawn
