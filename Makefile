# AnchorsFactory — dev / build / publish tasks (uv-based).
#
# Publishing is intentionally manual and not wired to CI: the rules still need
# tuning against GlyphConstruction before a real release. `make build` produces
# the artifacts; `make publish` uploads them when you're ready (set a token —
# see publish target).

PY := .venv/bin/python

.PHONY: help venv test build check publish-test publish release release-test clean

help:
	@echo "venv         create .venv and install the package (editable) + dev deps"
	@echo "test         run the test suite"
	@echo "build        build sdist + wheel into dist/"
	@echo "check        build, then validate the artifacts (twine check)"
	@echo "publish-test upload to TestPyPI"
	@echo "publish      upload to PyPI"
	@echo "release      bump minor, changelog, build, upload to PyPI, tag + push"
	@echo "release-test same as release, but upload to TestPyPI"
	@echo "clean        remove build artifacts and caches"

venv:
	uv venv
	VIRTUAL_ENV="$(CURDIR)/.venv" uv pip install -e ".[dev]"

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
