# AnchorsFactory — dev / build / publish tasks (uv-based).
#
# Publishing is intentionally manual and not wired to CI: the rules still need
# tuning against GlyphConstruction before a real release. `make build` produces
# the artifacts; `make release` tags a version and CI publishes it.

PY := .venv/bin/python

.PHONY: help venv browsers studio studio-save test build check release web-dev web-build clean

help:
	@echo "venv         create .venv and install the package (editable) + dev deps + browsers"
	@echo "browsers     download the Playwright chromium used by the studio UI test"
	@echo "studio       launch Studio + open it in a browser window (ARGS='<ufo> -r <rules>')"
	@echo "studio-save  like studio, but seed from the default rule set + autosave edits to a file (default dev/studio-rules.anchors)"
	@echo "test         run the test suite"
	@echo "build        build sdist + wheel into dist/"
	@echo "check        build, then validate the artifacts (twine check)"
	@echo "release      bump minor, promote CHANGELOG [Unreleased], check build, tag + push (CI publishes to PyPI)"
	@echo "web-dev      run the web Studio (Pyodide, web/) on a Vite dev server"
	@echo "web-build    build the web Studio into web/dist (what GitHub Pages serves)"
	@echo "clean        remove build artifacts and caches"

venv:
	uv venv
	VIRTUAL_ENV="$(CURDIR)/.venv" uv pip install -e ".[dev]"
	$(MAKE) browsers

# The web Studio (web/): the Studio's page with Python in a Pyodide worker.
# Needs Node; the pinned wheels are fetched once into web/public/wheels.
web/public/wheels/manifest.json: web/wheels.txt
	python3 scripts/fetch_web_wheels.py

web/node_modules: web/package-lock.json
	cd web && npm ci --ignore-scripts

web-dev: web/public/wheels/manifest.json web/node_modules
	cd web && npm run dev

web-build: web/public/wheels/manifest.json web/node_modules
	cd web && npm run build

# The studio UI test drives a headless chromium via Playwright; the test skips
# cleanly if it's missing, so this is only needed to actually run that test.
browsers:
	$(PY) -m playwright install chromium

# Launch Studio and open it in a Playwright Chromium window. Pass a font/rules
# via ARGS, e.g.  make studio ARGS="MyFont.ufo -r my.anchors"
# Bare set names (-r default, !extends default) resolve against examples/rules/,
# the repository's samples — no rule sets ship with the package.
studio:
	$(PY) scripts/studio_dev.py $(ARGS)

# Like studio, but seeded from the `default` sample set and autosaving every valid
# edit to a file (dev/studio-rules.anchors by default; override with ARGS="-f my.anchors").
# Subsequent runs resume from that file. Good for an iterative rules session.
studio-save:
	$(PY) scripts/studio_save.py $(ARGS)

test:
	$(PY) -m pytest

build: clean
	uv build

# Sanity-check the built artifacts (long_description renders, metadata valid).
check: build
	uvx twine check dist/*

# Upload. Authenticate with a token, e.g.:
#   export UV_PUBLISH_TOKEN=pypi-...        (PyPI)
# or pass --token on the command line.
# Release: bump minor, promote CHANGELOG, check the build, tag, push. The tag
# starts .github/workflows/release.yml, which publishes to PyPI by trusted
# publishing (no token). Pass extra flags via ARGS, e.g.  make release ARGS=--no-bump
release:
	$(PY) scripts/release.py $(ARGS)

clean:
	rm -rf dist build *.egg-info anchorsfactory.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
