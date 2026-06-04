"""
Autodesk EAGLE schematic parser.

Modern EAGLE `.sch` files (v6+) are XML. We pull <part>, <net>, and <segment>
elements which give us components, nets, and the (approximate) connections.
"""

from __future__ import annotations

from pathlib import Path

from ..ir import Schematic, Component, Net, Connection
from .base import BaseParser


class EagleParser(BaseParser):
    format_name = "eagle"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        if path.suffix.lower() != ".sch":
            return False
        try:
            head = path.read_text(errors="ignore")[:512]
        except OSError:
            return False
        return "<?xml" in head and ("eagle" in head.lower() or "<eagle" in head.lower())

    def parse(self, path: Path, output_dir=None) -> Schematic:
        sch = Schematic(source_file=str(path), source_format=self.format_name)
        sch.title = path.stem

        try:
            from lxml import etree  # type: ignore
        except ImportError:
            sch.add_warning("lxml not installed — EAGLE parser disabled.")
            return sch

        try:
            tree = etree.parse(str(path))
        except Exception as e:  # noqa: BLE001
            sch.add_warning(f"XML parse failed: {e}")
            return sch

        root = tree.getroot()

        # Components: <parts><part name="R1" value="10k" library="..." device="..."/>
        for part in root.iter("part"):
            comp = Component(
                reference=part.get("name", ""),
                value=part.get("value", ""),
                description=f"{part.get('library', '')}/{part.get('device', '')}".strip("/"),
            )
            for k in ("library", "deviceset", "device", "package"):
                v = part.get(k)
                if v:
                    comp.properties[k] = v
            if comp.reference:
                sch.components.append(comp)

        # Nets: <net name="VCC" class="0"><segment><pinref part="U1" pin="VCC"/>...</segment></net>
        for net_el in root.iter("net"):
            name = net_el.get("name", "")
            net = Net(name=name)
            n = name.upper()
            if n in {"GND", "VSS", "AGND", "DGND"}:
                net.is_ground = True
            if n.startswith(("V", "+")) or "VCC" in n or "VDD" in n:
                net.is_power = True

            pin_refs: list[str] = []
            for pinref in net_el.iter("pinref"):
                part = pinref.get("part", "")
                pin = pinref.get("pin", "")
                if part and pin:
                    pin_refs.append(f"{part}.{pin}")
            net.nodes = pin_refs

            # Build pairwise connections within the net (star to first node).
            if len(pin_refs) >= 2:
                anchor = pin_refs[0]
                for other in pin_refs[1:]:
                    sch.connections.append(
                        Connection(from_ref=anchor, to_ref=other, net=name)
                    )
            sch.nets.append(net)

        return sch
