"""Smoke tests for SPICE parser and exporter round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from schematic2ai.parsers import parse, detect_parser
from schematic2ai.parsers.spice_parser import SpiceParser
from schematic2ai.exporters import export_json, export_markdown


EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "amplifier.cir"


def test_detect_parser_spice():
    assert detect_parser(EXAMPLE) is SpiceParser


def test_parse_spice_components():
    sch = parse(EXAMPLE)
    refs = {c.reference for c in sch.components}
    assert "R1" in refs
    assert "Q1" in refs
    assert "VCC" in refs
    assert len(sch.components) == 10


def test_parse_spice_title_strips_comment():
    sch = parse(EXAMPLE)
    assert not sch.title.startswith("*"), "Title should not start with SPICE comment marker"
    assert "amplifier" in sch.title.lower()


def test_parse_spice_nets():
    sch = parse(EXAMPLE)
    net_names = {n.name for n in sch.nets}
    assert "VCC" in net_names
    assert "0" in net_names
    assert "B" in net_names

    # Check power/ground flags
    gnd_net = next(n for n in sch.nets if n.name == "0")
    assert gnd_net.is_ground

    vcc_net = next(n for n in sch.nets if n.name == "VCC")
    assert vcc_net.is_power


def test_parse_spice_connections():
    sch = parse(EXAMPLE)
    assert len(sch.connections) > 0
    # All connections should have from/to refs
    for c in sch.connections:
        assert c.from_ref
        assert c.to_ref


def test_parse_spice_pin_names():
    """Transistor pins should have semantic names."""
    sch = parse(EXAMPLE)
    q1 = next(c for c in sch.components if c.reference == "Q1")
    pin_names = [p.name for p in q1.pins]
    assert "collector" in pin_names
    assert "base" in pin_names
    assert "emitter" in pin_names


def test_parse_spice_diode_pin_names():
    """Diode pins (if present) should have anode/cathode names."""
    # Create a minimal SPICE netlist with a diode
    import tempfile
    content = "Diode test\nD1 anode cathode 1N4148\n.end\n"
    with tempfile.NamedTemporaryFile(suffix=".cir", mode="w", delete=False) as f:
        f.write(content)
        f.flush()
        sch = parse(Path(f.name))
    d1 = next(c for c in sch.components if c.reference == "D1")
    assert d1.pins[0].name == "anode"
    assert d1.pins[1].name == "cathode"


def test_export_json_roundtrip(tmp_path):
    sch = parse(EXAMPLE)
    out = export_json(sch, tmp_path / "test.json")
    assert out.exists()
    import json
    data = json.loads(out.read_text())
    assert data["schema_version"] == "1.0"
    assert len(data["schematic"]["components"]) == 10


def test_export_markdown_roundtrip(tmp_path):
    sch = parse(EXAMPLE)
    out = export_markdown(sch, tmp_path / "test.md")
    assert out.exists()
    text = out.read_text()
    assert "## Components" in text
    assert "## Nets" in text
    assert "## Analysis hints" in text
    assert "R1" in text
    assert "Q1" in text
