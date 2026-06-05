"""AnchorsFactory — rule-driven anchor placement for UFO fonts."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("anchorsfactory")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"

from .apply import apply_document, compute_document, accumulate, validate_document
from .geometry import resolve
from .parser import parse_document, parse_file, ParseError
from .dsl import parse_dsl, parse_dsl_file, DSLError
from .convert import convert_file, render_document, verify_conversion
from .presets import list_presets, preset_text, is_preset
from .runner import process_ufo, load_document

__all__ = [
    "__version__",
    "apply_document",
    "compute_document",
    "resolve",
    "accumulate",
    "validate_document",
    "parse_document",
    "parse_file",
    "ParseError",
    "parse_dsl",
    "parse_dsl_file",
    "DSLError",
    "convert_file",
    "render_document",
    "verify_conversion",
    "list_presets",
    "preset_text",
    "is_preset",
    "process_ufo",
    "load_document",
]
