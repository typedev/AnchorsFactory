"""AnchorsFactory — rule-driven anchor placement for UFO fonts."""

from .apply import apply_document, accumulate
from .parser import parse_document, parse_file, ParseError
from .dsl import parse_dsl, parse_dsl_file, DSLError
from .convert import convert_file, render_document
from .runner import process_ufo, load_document

__all__ = [
    "apply_document",
    "accumulate",
    "parse_document",
    "parse_file",
    "ParseError",
    "parse_dsl",
    "parse_dsl_file",
    "DSLError",
    "convert_file",
    "render_document",
    "process_ufo",
    "load_document",
]
