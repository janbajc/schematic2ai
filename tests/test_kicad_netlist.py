from pathlib import Path

from schematic2ai.parsers import parse
from schematic2ai.parsers.kicad_netlist_parser import KicadNetlistParser

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_detects_kicad_sexpr_netlist():
    assert KicadNetlistParser.can_parse(EXAMPLES / "kicad_mini.net")


def test_parses_components_nets_connections():
    sch = parse(EXAMPLES / "kicad_mini.net")
    assert sch.source_format == "kicad_netlist"
    assert {c.reference for c in sch.components} == {"R1", "U1"}

    r1 = next(c for c in sch.components if c.reference == "R1")
    assert r1.value == "10k"
    assert r1.footprint == "Resistor_SMD:R_0603"

    nets = {n.name: n for n in sch.nets}
    assert set(nets) == {"GND", "/3v3"}
    assert nets["GND"].is_ground
    assert nets["/3v3"].is_power
    assert nets["/3v3"].nodes == ["R1.1", "U1.6"]
    assert len(sch.connections) == 2

    u1 = next(c for c in sch.components if c.reference == "U1")
    assert u1.footprint == ""  # KiCad writes "~" for blank fields
    assert any(
        p.number == "7" and p.name == "GND_7" and p.net == "GND"
        and p.direction == "power"  # pintype power_in
        for p in u1.pins
    )
    assert next(p for p in u1.pins if p.number == "6").direction == "power"  # power_out
