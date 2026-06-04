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

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


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
    footprint: str = ""        # PCB footprint, if known
    description: str = ""      # human-readable description
    pins: list[Pin] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["pins"] = [p.to_dict() for p in self.pins]
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
    source_format: str = ""    # "pdf" | "image" | "kicad" | "altium" | "eagle" | "spice" | "gerber"
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
            "components": [c.to_dict() for c in self.components],
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
