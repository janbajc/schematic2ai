"""JSON exporter — emits a deterministic, schema-stable JSON document."""

from __future__ import annotations

import json
from pathlib import Path

from ..ir import Schematic


def export_json(schematic: Schematic, out_path: Path) -> Path:
    """Write *schematic* as JSON to *out_path* and return the path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "schematic": schematic.to_dict(),
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
