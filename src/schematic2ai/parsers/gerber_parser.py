"""
Gerber (RS-274X) parser — summary-level.

Gerber files describe *PCB layers*, not schematics. We don't recover a netlist
from them; instead we summarize: layer type, aperture list, draw/flash counts,
and bounding extents. That summary is what we hand to the AI.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..ir import Schematic
from .base import BaseParser


_APERTURE_RE = re.compile(r"%ADD(\d+)([A-Z])[,]?([^*]*)\*%")
_FILEFUNC_RE = re.compile(r"%TF\.FileFunction,([^*]+)\*%")
_DRAW_RE = re.compile(r"D0?[12]\*$", re.MULTILINE)


class GerberParser(BaseParser):
    format_name = "gerber"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        suf = path.suffix.lower()
        if suf in {".gbr", ".gerber", ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gko", ".drl"}:
            return True
        if suf == ".g":
            return True
        return False

    def parse(self, path: Path, output_dir=None) -> Schematic:
        sch = Schematic(source_file=str(path), source_format=self.format_name)
        sch.title = path.name

        text = path.read_text(encoding="utf-8", errors="ignore")

        file_func_match = _FILEFUNC_RE.search(text)
        if file_func_match:
            sch.metadata["file_function"] = file_func_match.group(1).strip()

        apertures = []
        for m in _APERTURE_RE.finditer(text):
            apertures.append({
                "dcode": int(m.group(1)),
                "shape": m.group(2),
                "params": m.group(3).strip(),
            })
        sch.metadata["apertures"] = apertures
        sch.metadata["aperture_count"] = len(apertures)
        sch.metadata["draw_operations"] = len(_DRAW_RE.findall(text))
        sch.metadata["line_count"] = text.count("\n")

        sch.notes = (
            "Gerber describes a PCB layer, not a schematic. "
            "Apertures and draw counts are reported as a summary; for net "
            "extraction use the corresponding schematic file."
        )
        sch.add_warning(
            "Gerber → IR is summary-only. No components or nets can be recovered."
        )
        return sch
