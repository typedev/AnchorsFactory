"""Suite-wide setup.

The package ships no rule sets, so the suite plays the part of a host: it points
the process-wide search path at the repository's sample sets, exactly as the
Studio or a downstream editor does at startup. Tests that care about resolution
itself pass ``search_paths=`` explicitly, which overrides this.
"""

import pytest

from anchorsfactory import presets
from rulesets import SEARCH_PATHS


@pytest.fixture(autouse=True)
def rule_search_path():
    """Configure (and restore) the process-wide rule search path."""
    before = presets.search_paths()
    presets.set_search_paths(SEARCH_PATHS)
    yield
    presets.set_search_paths(before)
