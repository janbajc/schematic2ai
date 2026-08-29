"""
Intermediate Representation (IR) for schematics.

Every parser converts its source format into a `Schematic` object, and every
exporter consumes `Schematic`. This is the canonical AI-readable model.

Design goals:
  * Lossless enough to be useful (components, nets, connections, metadata).
  * Tolerant of partial extraction (image/PDF OCR may yield text-only).
  * Easy to serialize to JSON.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Component classification
# ---------------------------------------------------------------------------

# Maps a reference-designator prefix to a human-readable component category.
# Based on the common IEEE 315 / IPC reference-designator conventions, plus a
# few SPICE-specific element letters. The longest matching prefix wins so that
# e.g. "RV" (potentiometer) beats "R" (resistor).
_REFDES_KINDS: dict[str, str] = {
    "ANT": "antenna",
    "BT": "battery",
    "BR": "bridge rectifier",
    "C": "capacitor",
    "CN": "connector",
    "D": "diode",
    "DZ": "zener diode",
    "F": "fuse",
    "FB": "ferrite bead",
    "FET": "transistor (FET)",
    "J": "connector",
    "JP": "jumper",
    "K": "relay",
    "L": "inductor",
    "LED": "LED",
    "M": "motor",
    "MOSFET": "transistor (MOSFET)",
    "P": "connector",
    "Q": "transistor",
    "R": "resistor",
    "RN": "resistor network",
    "RV": "potentiometer",
    "SW": "switch",
    "T": "transformer",
    "TP": "test point",
    "U": "integrated circuit",
    "VR": "voltage regulator",
    "X": "subcircuit",
    "XTAL": "crystal",
    "Y": "crystal/oscillator",
}

# SPICE single-letter element types (used when the refdes is a raw netlist
# element rather than a board-level designator).
_SPICE_KINDS: dict[str, str] = {
    "R": "resistor",
    "C": "capacitor",
    "L": "inductor",
    "D": "diode",
    "Q": "transistor (BJT)",
    "M": "transistor (MOSFET)",
    "J": "transistor (JFET)",
    "V": "voltage source",
    "I": "current source",
    "E": "VCVS",
    "F": "CCCS",
    "G": "VCCS",
    "H": "CCVS",
    "K": "coupled inductor",
    "S": "voltage-controlled switch",
    "W": "current-controlled switch",
    "X": "subcircuit",
    "B": "behavioral source",
    "T": "transmission line",
}


def classify_reference(reference: str, source_format: str = "") -> str:
    """Infer a human-readable component category from its reference designator.

    For SPICE netlists the single leading letter is authoritative (``Q1`` is a
    BJT). For board formats the alphabetic prefix is matched against common
    reference-designator conventions, preferring the longest match.

    Returns an empty string when the reference cannot be classified.
    """
    if not reference:
        return ""
    m = re.match(r"^([A-Za-z]+)", reference.strip())
    if not m:
        return ""
    prefix = m.group(1).upper()

    if source_format == "spice":
        return _SPICE_KINDS.get(prefix[0], "")

    # Longest-prefix match (so "MOSFET" / "LED" / "RV" beat "M" / "L" / "R").
    for length in range(len(prefix), 0, -1):
        kind = _REFDES_KINDS.get(prefix[:length])
        if kind:
            return kind
    return ""


@dataclass
class Pin:
    """A pin / terminal on a component."""
    number: str = ""           # "1", "A2", "VCC" ...
    name: str = ""             # functional name, e.g. "GND", "CLK"
    net: str = ""              # name of the net this pin is connected to
    direction: str = ""        # "input" | "output" | "bidir" | "power" | ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Component:
    """A schematic component / part."""
    reference: str = ""        # e.g. "R1", "U3", "C12"
    value: str = ""            # e.g. "10k", "100nF", "ATmega328P"
    kind: str = ""             # inferred category, e.g. "resistor", "transistor (BJT)"
    footprint: str = ""        # PCB footprint, if known
    description: str = ""      # human-readable description
    pins: list[Pin] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)

    def classified_kind(self, source_format: str = "") -> str:
        """Return ``kind`` if set, otherwise infer it from the reference."""
        return self.kind or classify_reference(self.reference, source_format)

    def to_dict(self, source_format: str = "") -> dict[str, Any]:
        d = asdict(self)
        d["pins"] = [p.to_dict() for p in self.pins]
        d["kind"] = self.classified_kind(source_format)
        return d


@dataclass
class Connection:
    """A point-to-point connection between two pins (component.pin)."""
    from_ref: str = ""         # "R1.2"
    to_ref: str = ""           # "U1.14"
    net: str = ""              # net name carrying this connection


@dataclass
class Net:
    """An electrical net (named wire)."""
    name: str = ""
    nodes: list[str] = field(default_factory=list)  # ["R1.2", "U1.14", ...]
    is_power: bool = False
    is_ground: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Schematic:
    """The canonical schematic representation."""
    source_file: str = ""
    source_format: str = ""    # "pdf" | "image" | "kicad" | "altium" | "eagle" | "spice" | "gerber" | "kicad_netlist"
    title: str = ""
    revision: str = ""
    author: str = ""
    notes: str = ""
    # Optional raw text recovered from the source (OCR / PDF text / titleblock).
    raw_text: str = ""

    components: list[Component] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)

    # Bag of extra metadata (parser-specific).
    metadata: dict[str, Any] = field(default_factory=dict)
    # Warnings / partial-extraction notes (helps AI know what is uncertain).
    warnings: list[str] = field(default_factory=list)
    # Paths of any images extracted (page renders, embedded figures).
    images: list[str] = field(default_factory=list)
    # Paths of any overlapping tile crops produced for vision-LLM "zoom-in".
    # Each entry is a dict: {"page": "page_001.png", "tiles": ["r0c0.png", ...]}
    image_tiles: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "source_format": self.source_format,
            "title": self.title,
            "revision": self.revision,
            "author": self.author,
            "notes": self.notes,
            "raw_text": self.raw_text,
            "components": [c.to_dict(self.source_format) for c in self.components],
            "nets": [n.to_dict() for n in self.nets],
            "connections": [asdict(c) for c in self.connections],
            "metadata": self.metadata,
            "warnings": self.warnings,
            "images": self.images,
            "image_tiles": self.image_tiles,
        }

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def summary(self) -> str:
        return (
            f"{self.source_format.upper()} schematic '{self.title or self.source_file}': "
            f"{len(self.components)} components, {len(self.nets)} nets, "
            f"{len(self.connections)} connections."
        )
