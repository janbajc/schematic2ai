"""
Altium Designer schematic (.SchDoc) parser — best effort.

`.SchDoc` is a proprietary OLE compound binary. Full parsing requires Altium
or the `pyaltium` reverse-engineered library. Here we:

  * Detect the format,
  * Extract readable ASCII strings to capture refdes/values/text,
  * Emit a clear warning so the AI knows the extraction is approximate.

For best results, export `.SchDoc` to PDF from Altium and feed the PDF instead.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..ir import Schematic, Component
from .base import BaseParser


_REF_RE = re.compile(
    r"\b(R|C|L|D|Q|U|IC|J|JP|K|F|FB|TP|SW|S|BT|Y|X|RV|RN|LED|MOV|CN|P)(\d{1,4})\b"
)
_STRING_RE = re.compile(rb"[\x20-\x7E]{4,}")


class AltiumParser(BaseParser):
    format_name = "altium"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        return path.suffix.lower() in {".schdoc", ".schlib"}

    def parse(self, path: Path, output_dir=None) -> Schematic:
        sch = Schematic(source_file=str(path), source_format=self.format_name)
        sch.title = path.stem

        try:
            raw = path.read_bytes()
        except OSError as e:
            sch.add_warning(f"Cannot read file: {e}")
            return sch

        strings = [s.decode("ascii", errors="ignore") for s in _STRING_RE.findall(raw)]
        sch.raw_text = "\n".join(strings)

        seen: set[str] = set()
        for prefix, num in _REF_RE.findall(sch.raw_text):
            ref = f"{prefix}{num}"
            if ref in seen:
                continue
            seen.add(ref)
            sch.components.append(Component(reference=ref))

        sch.add_warning(
            "Altium .SchDoc is a proprietary binary — only ASCII strings were "
            "recovered. For lossless extraction, export the schematic to PDF "
            "from Altium Designer and re-run schematic2ai on the PDF."
        )
        return sch
