"""
SPICE-style netlist parser (.net, .cir, .sp).

Handles the standard SPICE element line format::

    R1   N1  N2   10k
    C2   VCC GND  100n
    Q3   C  B  E  2N3904
    U1   in out vcc gnd MODELNAME PARAM=value

Each token after the refdes (except the model name / value) is treated as a
node name. Connections are built per net.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ..ir import Schematic, Component, Net, Connection, Pin
from .base import BaseParser


_NUMVAL_RE = re.compile(r"^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?[a-zA-Zµ]*$")

# Semantic pin names for common SPICE element types.
_PIN_NAMES: dict[str, list[str]] = {
    "R": ["1", "2"],
    "C": ["1", "2"],
    "L": ["1", "2"],
    "D": ["anode", "cathode"],
    "V": ["pos", "neg"],
    "I": ["pos", "neg"],
    "Q": ["collector", "base", "emitter"],
    "M": ["drain", "gate", "source", "bulk"],
    "J": ["drain", "gate", "source"],
}


class SpiceParser(BaseParser):
    format_name = "spice"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        return path.suffix.lower() in {".cir", ".sp", ".spice"} or (
            path.suffix.lower() == ".net" and not _looks_like_eagle_or_pads(path)
        )

    def parse(self, path: Path, output_dir=None) -> Schematic:
        sch = Schematic(source_file=str(path), source_format=self.format_name)
        sch.title = path.stem

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if lines:
            # First non-empty line of a SPICE netlist is the title by convention.
            for line in lines:
                if line.strip():
                    title = line.strip()
                    # Strip SPICE comment marker if present.
                    if title.startswith("*"):
                        title = title.lstrip("* ").strip()
                    sch.title = title or path.stem
                    break

        net_to_pins: dict[str, list[str]] = defaultdict(list)

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("*") or line.startswith(".") or line.startswith(";"):
                continue
            tokens = line.split()
            if len(tokens) < 3:
                continue
            ref = tokens[0]
            # Heuristic: nodes are the tokens until we hit a numeric value or a model name.
            # For passives (R/L/C) the last token is the value.
            kind = ref[0].upper()
            if kind in {"R", "L", "C"} and len(tokens) >= 4:
                nodes = tokens[1:-1]
                value = tokens[-1]
            elif kind in {"V", "I"} and len(tokens) >= 4:
                nodes = tokens[1:3]
                value = " ".join(tokens[3:])
            elif kind in {"D"} and len(tokens) >= 4:
                nodes = tokens[1:3]
                value = " ".join(tokens[3:])
            elif kind in {"Q", "M", "J"} and len(tokens) >= 5:
                nodes = tokens[1:4]
                value = " ".join(tokens[4:])
            elif kind == "X":
                # Subcircuit call: Xname n1 n2 ... subcktname [params]
                # The last token that is NOT a node is the subckt name; we treat
                # the trailing alpha token as the model.
                nodes = []
                value_parts = []
                hit_model = False
                for t in tokens[1:]:
                    if hit_model or "=" in t:
                        value_parts.append(t)
                    elif t.isidentifier() and not _NUMVAL_RE.match(t) and len(value_parts) == 0:
                        # ambiguous — assume nodes can be identifiers too.
                        nodes.append(t)
                    else:
                        nodes.append(t)
                # Move the last node to value (best-effort subckt name).
                if nodes:
                    value_parts.insert(0, nodes.pop())
                value = " ".join(value_parts)
            else:
                nodes = tokens[1:]
                value = ""

            comp = Component(reference=ref, value=value)
            pin_names = _PIN_NAMES.get(kind, [])
            for i, node in enumerate(nodes, start=1):
                name = pin_names[i - 1] if i - 1 < len(pin_names) else ""
                comp.pins.append(Pin(number=str(i), name=name, net=node))
                net_to_pins[node].append(f"{ref}.{i}")
            sch.components.append(comp)

        for name, pin_refs in net_to_pins.items():
            net = Net(name=name, nodes=pin_refs)
            n = name.upper()
            if n in {"0", "GND", "VSS", "AGND", "DGND"}:
                net.is_ground = True
            if n.startswith(("V", "+")) or "VCC" in n or "VDD" in n:
                net.is_power = True
            sch.nets.append(net)
            if len(pin_refs) >= 2:
                anchor = pin_refs[0]
                for other in pin_refs[1:]:
                    sch.connections.append(
                        Connection(from_ref=anchor, to_ref=other, net=name)
                    )

        return sch


def _looks_like_eagle_or_pads(path: Path) -> bool:
    try:
        head = path.read_text(errors="ignore")[:256].lower()
    except OSError:
        return False
    return "<?xml" in head or head.startswith("!pads")
