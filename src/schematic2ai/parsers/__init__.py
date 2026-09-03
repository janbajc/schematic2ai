"""Parsers convert source schematic files into the IR (`Schematic`)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..ir import Schematic
from .base import BaseParser
from .pdf_parser import PdfParser
from .image_parser import ImageParser
from .kicad_parser import KiCadParser
from .altium_parser import AltiumParser
from .eagle_parser import EagleParser
from .spice_parser import SpiceParser
from .gerber_parser import GerberParser
from .kicad_netlist_parser import KicadNetlistParser


# Order matters: most specific first.
_PARSERS: list[type[BaseParser]] = [
    KicadNetlistParser,
    KiCadParser,
    AltiumParser,
    EagleParser,
    SpiceParser,
    GerberParser,
    PdfParser,
    ImageParser,
]


def detect_parser(path: Path) -> Optional[type[BaseParser]]:
    """Pick the parser whose `can_parse` returns True for *path*."""
    for parser_cls in _PARSERS:
        if parser_cls.can_parse(path):
            return parser_cls
    return None


def parse(path: Path, output_dir: Optional[Path] = None) -> Schematic:
    """Parse *path* and return the IR. Raises ValueError if unsupported.

    *output_dir*, when provided, is forwarded to parsers that emit auxiliary
    artifacts (e.g. rendered PDF page PNGs) so they land next to the JSON/MD.
    """
    parser_cls = detect_parser(path)
    if parser_cls is None:
        raise ValueError(
            f"No parser found for {path}. "
            f"Supported: .pdf, .png/.jpg, .kicad_sch, .sch (KiCad/EAGLE/Altium), "
            f".SchDoc, .net (SPICE or KiCad netlist), .cir/.sp (SPICE), .gbr/.gerber."
        )
    parser = parser_cls()
    return parser.parse(path, output_dir=output_dir)


__all__ = ["parse", "detect_parser", "BaseParser"]
