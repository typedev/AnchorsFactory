# AnchorsFactory — dev / build / publish tasks (uv-based).
#
# Publishing is intentionally manual and not wired to CI: the rules still need
# tuning against GlyphConstruction before a real release. `make build` produces
# the artifacts; `make publish` uploads them when you're ready (set a token —
# see publish target).

PY := .venv/bin/python

.PHONY: help venv browsers studio studio-save test build check publish-test publish release release-test clean

help:
	@echo "venv         create .venv and install the package (editable) + dev deps + browsers"
	@echo "browsers     download the Playwright chromium used by the studio UI test"
	@echo "studio       launch Studio + open it in a browser window (ARGS='<ufo> -r <rules>')"
	@echo "studio-save  like studio, but seed from the default rule set + autosave edits to a file (default dev/studio-rules.anchors)"
	@echo "test         run the test suite"
	@echo "build        build sdist + wheel into dist/"
	@echo "check        build, then validate the artifacts (twine check)"
	@echo "publish-test upload to TestPyPI"
	@echo "publish      upload to PyPI"
	@echo "release      bump minor, promote CHANGELOG [Unreleased], build, upload to PyPI, tag + push"
	@echo "release-test same as release, but upload to TestPyPI (token from .env or prompt)"
	@echo "clean        remove build artifacts and caches"

venv:
	uv venv
	VIRTUAL_ENV="$(CURDIR)/.venv" uv pip install -e ".[dev]"
	$(MAKE) browsers

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
publish-test: build
	uv publish --publish-url https://test.pypi.org/legacy/ dist/*

publish: build
	uv publish dist/*

# One-shot release: bump minor, build CHANGELOG, build, upload, tag, push.
# Needs a token, e.g.  export UV_PUBLISH_TOKEN=pypi-...
# Pass extra flags via ARGS, e.g.  make release ARGS=--no-bump
release:
	$(PY) scripts/release.py $(ARGS)

release-test:
	$(PY) scripts/release.py --test $(ARGS)

clean:
	rm -rf dist build *.egg-info anchorsfactory.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
