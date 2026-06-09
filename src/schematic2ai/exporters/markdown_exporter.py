"""
Markdown exporter — produces a narrative description of the schematic that
is optimal for LLM ingestion.

The layout is intentionally LLM-friendly:
  1. A short header with the most important facts (the model reads this first).
  2. Components table.
  3. Nets / connections list.
  4. Warnings (so the model knows what is uncertain).
  5. Raw recovered text appendix (last — least token-efficient).
  6. List of bundled images (paths only; the caller decides what to upload).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..ir import Schematic


def export_markdown(schematic: Schematic, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render(schematic), encoding="utf-8")
    return out_path


def _render(s: Schematic) -> str:
    lines: list[str] = []
    lines.append(f"# Schematic: {s.title or s.source_file}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Source file:** `{s.source_file}`")
    lines.append(f"- **Source format:** `{s.source_format}`")
    if s.revision:
        lines.append(f"- **Revision:** {s.revision}")
    if s.author:
        lines.append(f"- **Author / Company:** {s.author}")
    lines.append(f"- **Components:** {len(s.components)}")
    lines.append(f"- **Nets:** {len(s.nets)}")
    lines.append(f"- **Connections:** {len(s.connections)}")
    lines.append("")

    if s.notes:
        lines.append("## Notes")
        lines.append("")
        lines.append(s.notes)
        lines.append("")

    # Title-block metadata, if extracted.
    tb = (s.metadata or {}).get("title_block")
    if tb:
        lines.append("## Title block")
        lines.append("")
        for k in ("title", "company", "sheet", "date"):
            v = tb.get(k)
            if v:
                lines.append(f"- **{k.capitalize()}:** {v}")
        lines.append("")

    # ------------------------------------------------------------------ components
    if s.components:
        lines.append("## Components")
        lines.append("")
        lines.append("| Ref | Kind | Value | Footprint | Description |")
        lines.append("|-----|------|-------|-----------|-------------|")
        for c in sorted(s.components, key=lambda x: _ref_key(x.reference)):
            kind = c.classified_kind(s.source_format)
            lines.append(
                f"| `{c.reference}` | {_esc(kind)} | {_esc(c.value)} | "
                f"{_esc(c.footprint)} | {_esc(c.description)} |"
            )
        lines.append("")

        # Quick breakdown by category — helps the model grasp the design at a glance.
        counts: dict[str, int] = {}
        for c in s.components:
            kind = c.classified_kind(s.source_format) or "unclassified"
            counts[kind] = counts.get(kind, 0) + 1
        if counts:
            breakdown = ", ".join(
                f"{n}× {k}" for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            )
            lines.append(f"**Breakdown:** {breakdown}")
            lines.append("")

    # ------------------------------------------------------------------ nets
    if s.nets:
        lines.append("## Nets")
        lines.append("")
        for n in sorted(s.nets, key=lambda x: x.name):
            tag = []
            if n.is_power:
                tag.append("power")
            if n.is_ground:
                tag.append("ground")
            tag_str = f" _{', '.join(tag)}_" if tag else ""
            nodes_str = ", ".join(f"`{x}`" for x in n.nodes) if n.nodes else "(no nodes resolved)"
            lines.append(f"- **`{n.name}`**{tag_str} — {nodes_str}")
        lines.append("")

    # ------------------------------------------------------------------ connections
    if s.connections:
        lines.append("## Connections")
        lines.append("")
        lines.append("| From | To | Net |")
        lines.append("|------|----|-----|")
        for c in s.connections:
            lines.append(f"| `{c.from_ref}` | `{c.to_ref}` | `{c.net}` |")
        lines.append("")

    # ------------------------------------------------------------------ warnings
    if s.warnings:
        lines.append("## ⚠ Extraction warnings")
        lines.append("")
        for w in s.warnings:
            lines.append(f"- {w}")
        lines.append("")

    # ------------------------------------------------------------------ images
    if s.images:
        lines.append("## Bundled images")
        lines.append("")
        lines.append("Pass these to a multimodal model for visual analysis:")
        lines.append("")
        for img in s.images:
            lines.append(f"- `{img}`")
        lines.append("")

    if s.image_tiles:
        lines.append("## Image tiles (zoom-in regions)")
        lines.append("")
        lines.append(
            "For each page, the renderer also produced overlapping tiles. "
            "Vision models can load just the tile(s) covering a region of "
            "interest instead of the whole sheet."
        )
        lines.append("")
        for entry in s.image_tiles:
            lines.append(f"- Page `{entry.get('page','')}`")
            for t in entry.get("tiles", []):
                lines.append(f"  - `{t}`")
        lines.append("")

    # ------------------------------------------------------------------ raw text
    if s.raw_text.strip():
        lines.append("## Recovered raw text")
        lines.append("")
        lines.append("```text")
        lines.append(s.raw_text.strip())
        lines.append("```")
        lines.append("")

    # ------------------------------------------------------------------ metadata
    if s.metadata:
        lines.append("## Metadata")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(s.metadata, indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")

    # ------------------------------------------------------------------ AI hints
    lines.append("## Analysis hints")
    lines.append("")
    lines.append(
        "This schematic was machine-extracted. When analysing it, consider:"
    )
    lines.append("")
    lines.append("1. **Identify the circuit topology** — what is the overall function "
                 "(power supply, amplifier, filter, digital logic, mixed-signal, etc.)?")
    lines.append("2. **Trace signal paths** — follow connections from inputs to outputs "
                 "through the net/connection tables.")
    lines.append("3. **Check power rails** — nets tagged as *power* or *ground* show "
                 "the supply architecture.")
    lines.append("4. **Note extraction warnings** — some connections may be missing "
                 "(especially from PDF/image sources). Cross-reference with bundled "
                 "images if available.")
    lines.append("5. **Component values drive behaviour** — passive values (R/C/L) "
                 "determine gain, frequency response, time constants, and bias points.")
    lines.append("")

    return "\n".join(lines)


def _esc(v: str) -> str:
    return (v or "").replace("|", "\\|").replace("\n", " ")


def _ref_key(ref: str) -> tuple[str, int]:
    """Sort R1, R2, R10 naturally."""
    m = re.match(r"([A-Za-z]+)(\d+)", ref or "")
    if not m:
        return (ref or "", 0)
    return (m.group(1), int(m.group(2)))
