"""AnchorsFactory — rule-driven anchor placement for UFO fonts."""

from .apply import apply_document
from .parser import parse_document, parse_file, ParseError
from .runner import process_ufo

__all__ = [
    "apply_document",
    "parse_document",
    "parse_file",
    "ParseError",
    "process_ufo",
]
