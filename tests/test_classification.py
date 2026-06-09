"""Tests for component classification (the inferred `kind` field)."""

from __future__ import annotations

from pathlib import Path

import pytest

from schematic2ai.ir import Schematic, Component, classify_reference
from schematic2ai.exporters.markdown_exporter import _render
from schematic2ai.parsers import parse

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class TestClassifyReference:
    def test_spice_single_letter_is_authoritative(self):
        assert classify_reference("Q1", "spice") == "transistor (BJT)"
        assert classify_reference("M3", "spice") == "transistor (MOSFET)"
        assert classify_reference("R10", "spice") == "resistor"
        assert classify_reference("C2", "spice") == "capacitor"
        assert classify_reference("VCC", "spice") == "voltage source"
        assert classify_reference("ITAIL", "spice") == "current source"
        assert classify_reference("X1", "spice") == "subcircuit"

    def test_board_longest_prefix_wins(self):
        # "LED" must beat "L", "RV" must beat "R", "MOSFET" must beat "M".
        assert classify_reference("LED1", "kicad") == "LED"
        assert classify_reference("RV2", "kicad") == "potentiometer"
        assert classify_reference("RN1", "kicad") == "resistor network"
        assert classify_reference("R5", "kicad") == "resistor"

    def test_common_board_designators(self):
        assert classify_reference("U7", "eagle") == "integrated circuit"
        assert classify_reference("C12", "eagle") == "capacitor"
        assert classify_reference("J3", "eagle") == "connector"
        assert classify_reference("SW1", "eagle") == "switch"

    def test_unknown_and_empty(self):
        assert classify_reference("", "spice") == ""
        assert classify_reference("123", "spice") == ""
        assert classify_reference("ZZZ9", "kicad") == ""


class TestComponentKind:
    def test_explicit_kind_takes_precedence(self):
        c = Component(reference="R1", kind="custom-thing")
        assert c.classified_kind("spice") == "custom-thing"

    def test_inferred_when_unset(self):
        c = Component(reference="Q2")
        assert c.classified_kind("spice") == "transistor (BJT)"

    def test_to_dict_includes_kind(self):
        c = Component(reference="C1", value="100nF")
        d = c.to_dict("spice")
        assert d["kind"] == "capacitor"

    def test_schematic_to_dict_is_format_aware(self):
        s = Schematic(source_format="spice", components=[Component(reference="M1")])
        d = s.to_dict()
        assert d["components"][0]["kind"] == "transistor (MOSFET)"


class TestMarkdownKindColumn:
    def test_diff_pair_markdown_has_kind_and_breakdown(self):
        sch = parse(EXAMPLES / "diff_pair.cir")
        md = _render(sch)
        assert "| Ref | Kind | Value | Footprint | Description |" in md
        assert "transistor (BJT)" in md
        assert "**Breakdown:**" in md
        # Two 2N3904 BJTs in the differential pair.
        assert "2× transistor (BJT)" in md
