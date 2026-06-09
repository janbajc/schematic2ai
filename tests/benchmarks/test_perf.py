"""Performance benchmarks for schematic2ai.

These use the optional ``pytest-benchmark`` plugin. Run them explicitly with::

    pytest tests/benchmarks --benchmark-only

They are skipped automatically when the plugin is not installed, and are also
excluded from the default test run via the ``benchmark`` marker (see
``pyproject.toml``) so the normal suite stays fast.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schematic2ai.parsers import parse
from schematic2ai.exporters import export_json, export_markdown

pytest.importorskip("pytest_benchmark", reason="pytest-benchmark not installed")

pytestmark = pytest.mark.benchmark

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
CIR_FILES = sorted(EXAMPLES.glob("*.cir"))


@pytest.mark.parametrize("cir", CIR_FILES, ids=lambda p: p.name)
def test_parse_throughput(benchmark, cir):
    """Measure parse latency for each SPICE example."""
    result = benchmark(parse, cir)
    assert result.components, f"no components parsed from {cir.name}"


def test_parse_all_examples(benchmark):
    """Aggregate parse latency across every example at once."""
    def _parse_all():
        return [parse(f) for f in CIR_FILES]

    results = benchmark(_parse_all)
    assert len(results) == len(CIR_FILES)


def test_export_roundtrip(benchmark, tmp_path):
    """Measure full parse + JSON + Markdown export for the largest example."""
    cir = max(CIR_FILES, key=lambda p: p.stat().st_size)

    def _roundtrip():
        sch = parse(cir)
        export_json(sch, tmp_path / "out.json")
        export_markdown(sch, tmp_path / "out.md")
        return sch

    sch = benchmark(_roundtrip)
    assert sch.components
