"""Base class for parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..ir import Schematic


class BaseParser(ABC):
    """Common interface every parser implements."""

    #: short name, e.g. "pdf", "kicad". Set by subclass.
    format_name: str = ""

    @classmethod
    @abstractmethod
    def can_parse(cls, path: Path) -> bool:
        """Return True if this parser can handle *path*."""

    @abstractmethod
    def parse(self, path: Path, output_dir: Optional[Path] = None) -> Schematic:
        """Parse the file and return the IR.

        Parsers that emit auxiliary artifacts (e.g. rendered page PNGs from
        a PDF) should write them under *output_dir* when provided so they
        live next to the JSON/Markdown the CLI writes. When *output_dir* is
        None, parsers fall back to a sibling directory of the input file.
        """
