"""How the CLI addresses a rule set.

No rule sets ship with the package, so ``--rules default`` only means something
once a search path is configured — by ``--rules-path`` or the environment. These
tests drive :func:`anchorsfactory.cli.main` far enough to see the rules load
(exit 2 = the rules could not be loaded; exit 1 = they did, and the *font* was
the problem, which is all we need here — no UFO fixture required).
"""

from __future__ import annotations

import pytest

from anchorsfactory import presets
from anchorsfactory.cli import build_parser, main
from rulesets import RULES_DIR, SEARCH_PATHS

RULES_LOADED = 1        # rules fine, the bogus font failed
RULES_FAILED = 2        # rules could not be loaded at all


@pytest.fixture(autouse=True)
def no_configured_paths():
    """Start each test from an unconfigured process, like a fresh install."""
    before = presets.search_paths()
    presets.set_search_paths([])
    yield
    presets.set_search_paths(before)


def _run(*argv):
    return main(["nosuch.ufo", *argv])


def test_bare_name_without_a_search_path_fails_with_a_diagnostic(caplog):
    assert _run("-r", "default") == RULES_FAILED
    assert "not bundled" in caplog.text and "ANCHORSFACTORY_RULES_PATH" in caplog.text


def test_bare_name_resolves_via_rules_path():
    assert _run("-r", "default", "--rules-path", str(RULES_DIR)) == RULES_LOADED


def test_bare_name_resolves_via_the_environment(monkeypatch):
    monkeypatch.setenv("ANCHORSFACTORY_RULES_PATH", str(RULES_DIR))
    monkeypatch.setattr(presets, "_search_paths", None)      # re-read the env
    assert _run("-r", "default") == RULES_LOADED


def test_a_path_needs_no_configuration():
    assert _run("-r", str(RULES_DIR / "default.anchors")) == RULES_LOADED


def test_extends_a_neighbour_from_a_path(tmp_path):
    """`!extends default` in a file next to `default.anchors` resolves with no
    search path at all — the referring file's directory is tried first."""
    (tmp_path / "default.anchors").write_text("U+0041 = top (box.center 0)\n")
    mine = tmp_path / "mine.anchors"
    mine.write_text("!extends default\nU+0042 += b (box.center 0)\n")
    assert _run("-r", str(mine)) == RULES_LOADED


def test_rules_path_is_repeatable():
    args = build_parser().parse_args(
        ["f.ufo", "-r", "default", "--rules-path", "a", "--rules-path", "b"])
    assert args.rules_path == ["a", "b"]
