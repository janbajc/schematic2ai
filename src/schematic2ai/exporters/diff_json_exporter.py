"""JSON exporter for `SchematicDiff` — deterministic, schema-stable."""

from __future__ import annotations

import json
from pathlib import Path

from ..diff import SchematicDiff


def export_diff_json(d: SchematicDiff, out_path: Path) -> Path:
    """Write *d* as JSON to *out_path* and return the path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "kind": "schematic_diff",
        "diff": d.to_dict(),
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_path
