"""KiCad s-expression netlist parser (.net).

Parses the default output of `kicad-cli sch export netlist` (kicadsexpr)::

    (export (version "E")
      (design ...)
      (components (comp (ref "R1") (value "R") ...))
      (nets (net (code "1") (name "/3v3")
              (node (ref "C1") (pin "2") (pintype "passive")) ...)))

Unlike the SPICE export, this format carries every symbol (including
connectors and unmodelled ICs) with full pin-level connectivity, plus pin
names via `pinfunction` (e.g. GPIO4_5, BAT+_7).
"""

from __future__ import annotations

from pathlib import Path

import sexpdata

from ..ir import Schematic, Component, Net, Connection, Pin
from .base import BaseParser


def _is_tag(node, tag: str) -> bool:
    return (
        isinstance(node, (list, tuple))
        and len(node) > 0
        and isinstance(node[0], sexpdata.Symbol)
        and node[0].value() == tag
    )


def _child(tree, tag: str):
    for item in tree:
        if _is_tag(item, tag):
            return item
    return None


def _children(tree, tag: str) -> list:
    return [item for item in tree if _is_tag(item, tag)]


def _child_value(tree, tag: str) -> str:
    """First atom after (tag ...), e.g. (ref "R1") -> "R1". "" if absent."""
    node = _child(tree, tag)
    if node is None or len(node) < 2:
        return ""
    item = node[1]
    return item.value() if isinstance(item, sexpdata.Symbol) else str(item)


class KicadNetlistParser(BaseParser):
    format_name = "kicad_netlist"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        if path.suffix.lower() != ".net":
            return False
        try:
            head = path.read_text(encoding="utf-8", errors="ignore")[:256]
        except OSError:
            return False
        return head.lstrip().startswith("(export")

    def parse(self, path: Path, output_dir=None) -> Schematic:
        sch = Schematic(source_file=str(path), source_format=self.format_name)
        sch.title = path.stem

        tree = sexpdata.loads(path.read_text(encoding="utf-8", errors="ignore"))

        by_ref: dict[str, Component] = {}
        for comp_node in _children(_child(tree, "components") or [], "comp"):
            comp = Component(
                reference=_child_value(comp_node, "ref"),
                value=_child_value(comp_node, "value"),
                footprint=_child_value(comp_node, "footprint"),
                description=_child_value(comp_node, "description"),
            )
            sch.components.append(comp)
            by_ref[comp.reference] = comp

        for net_node in _children(_child(tree, "nets") or [], "net"):
            name = _child_value(net_node, "name")
            pin_refs: list[str] = []
            for node in _children(net_node, "node"):
                ref = _child_value(node, "ref")
                pin = _child_value(node, "pin")
                pin_refs.append(f"{ref}.{pin}")
                comp = by_ref.get(ref)
                if comp is not None:
                    comp.pins.append(
                        Pin(number=pin, name=_child_value(node, "pinfunction"), net=name)
                    )

            net = Net(name=name, nodes=pin_refs)
            upper = name.upper()
            if upper in {"0", "GND", "VSS", "AGND", "DGND"} or "GND" in upper:
                net.is_ground = True
            if upper.startswith("+") or any(p in upper for p in ("VCC", "VDD", "3V3", "5V")):
                net.is_power = True
            sch.nets.append(net)

            if len(pin_refs) >= 2:
                anchor = pin_refs[0]
                for other in pin_refs[1:]:
                    sch.connections.append(
                        Connection(from_ref=anchor, to_ref=other, net=name)
                    )

        return sch
