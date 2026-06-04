"""
KiCad schematic parser.

Supports:
  * KiCad 6/7/8 `.kicad_sch` (s-expression). Parsed with `sexpdata`.
  * Legacy KiCad 5 `.sch` (Eeschema text format). Best-effort regex parse.

We extract: components (symbols), their value/footprint/reference, and nets
inferred from labels and wire endpoints (the latter is approximate — full
ERC-grade net resolution needs the full KiCad engine).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..ir import Schematic, Component, Net, Pin
from .base import BaseParser


class KiCadParser(BaseParser):
    format_name = "kicad"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        suf = path.suffix.lower()
        if suf == ".kicad_sch":
            return True
        if suf == ".sch":
            # Could be KiCad legacy OR EAGLE. Sniff content.
            try:
                head = path.read_text(errors="ignore")[:512]
            except OSError:
                return False
            return "EESchema" in head or "LIBS:" in head
        return False

    def parse(self, path: Path, output_dir=None) -> Schematic:
        sch = Schematic(source_file=str(path), source_format=self.format_name)
        sch.title = path.stem

        if path.suffix.lower() == ".kicad_sch":
            self._parse_modern(path, sch)
        else:
            self._parse_legacy(path, sch)
        return sch

    # ------------------------------------------------------------------ modern
    def _parse_modern(self, path: Path, sch: Schematic) -> None:
        try:
            import sexpdata  # type: ignore
        except ImportError:
            sch.add_warning("sexpdata not installed — KiCad parser disabled.")
            return

        try:
            data = sexpdata.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:  # noqa: BLE001
            sch.add_warning(f"sexpdata failed: {e}")
            return

        labels: list[str] = []

        def sym(x: Any) -> str:
            return x.value() if hasattr(x, "value") else str(x)

        def walk(node: Any) -> None:
            if not isinstance(node, list) or not node:
                return
            head = sym(node[0])

            if head == "symbol":
                comp = Component()
                for child in node[1:]:
                    if isinstance(child, list) and child:
                        chead = sym(child[0])
                        if chead == "property" and len(child) >= 3:
                            pname = str(child[1]).strip('"')
                            pval = str(child[2]).strip('"')
                            if pname == "Reference":
                                comp.reference = pval
                            elif pname == "Value":
                                comp.value = pval
                            elif pname == "Footprint":
                                comp.footprint = pval
                            elif pname == "Description":
                                comp.description = pval
                            else:
                                comp.properties[pname] = pval
                if comp.reference:
                    sch.components.append(comp)

            elif head in ("label", "global_label", "hierarchical_label"):
                # (label "NET_NAME" (at x y) ...)
                if len(node) >= 2:
                    labels.append(str(node[1]).strip('"'))

            elif head in ("title_block",):
                for child in node[1:]:
                    if isinstance(child, list) and len(child) >= 2:
                        key = sym(child[0])
                        val = str(child[1]).strip('"')
                        if key == "title":
                            sch.title = val
                        elif key == "rev":
                            sch.revision = val
                        elif key == "company":
                            sch.author = val

            for child in node[1:]:
                walk(child)

        walk(data)

        for name in sorted(set(labels)):
            net = Net(name=name)
            n = name.upper()
            if n in {"GND", "VSS", "AGND", "DGND"}:
                net.is_ground = True
            if n.startswith("V") or n.startswith("+") or "VCC" in n or "VDD" in n:
                net.is_power = True
            sch.nets.append(net)

        sch.add_warning(
            "Wire-level net resolution is approximate — only named labels are "
            "promoted to nets. For full netlist, export from KiCad with `kicad-cli sch export netlist`."
        )

    # ------------------------------------------------------------------ legacy
    _LEGACY_COMP = re.compile(
        r"^\$Comp\s*\nL\s+(?P<lib>\S+)\s+(?P<ref>\S+)\s*\n.*?\$EndComp",
        re.DOTALL | re.MULTILINE,
    )
    _LEGACY_F = re.compile(r'^F\s+(?P<idx>\d+)\s+"(?P<val>[^"]*)"', re.MULTILINE)

    def _parse_legacy(self, path: Path, sch: Schematic) -> None:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in self._LEGACY_COMP.finditer(text):
            block = m.group(0)
            comp = Component(reference=m.group("ref"))
            for fm in self._LEGACY_F.finditer(block):
                idx = int(fm.group("idx"))
                val = fm.group("val")
                if idx == 0:
                    comp.reference = val
                elif idx == 1:
                    comp.value = val
                elif idx == 2:
                    comp.footprint = val
            if comp.reference:
                sch.components.append(comp)

        for lab in re.findall(r'Text\s+(?:Label|GLabel|HLabel)\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s*\n(\S+)', text):
            sch.nets.append(Net(name=lab))

        sch.add_warning("Legacy KiCad parser is best-effort — connections not extracted.")
