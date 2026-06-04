"""
Markdown exporter for `SchematicDiff`.

Layout is optimised for LLM ingestion:

  1. One-line summary counts (model reads this first).
  2. Added / removed / changed components — the highest-signal sections.
  3. Likely renames (with confidence + reason — model can weigh them).
  4. Net-level diff (only populated for KiCad/EAGLE/SPICE inputs).
  5. Value-token diff (catches part-number / footprint changes missed by
     the heuristic component extractor).
  6. Image bundles, side by side, so multimodal models can render both.
  7. Warnings.

We deliberately do NOT include the full raw text of either schematic —
that's redundant when the goal is to describe the *delta*.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..diff import SchematicDiff


_REF_SPLIT_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def _ref_key(ref: str) -> tuple[str, int]:
    m = _REF_SPLIT_RE.match(ref or "")
    if not m:
        return (ref or "", 0)
    return (m.group(1), int(m.group(2)))


def _esc(v: str) -> str:
    return (v or "").replace("|", "\\|").replace("\n", " ")


def export_diff_markdown(d: SchematicDiff, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render(d), encoding="utf-8")
    return out_path


def _render(d: SchematicDiff) -> str:
    lines: list[str] = []
    lines.append(f"# Schematic diff: {d.old_title} → {d.new_title}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Old:** `{d.old_source}`")
    lines.append(f"- **New:** `{d.new_source}`")
    lines.append(f"- **Components added:** {len(d.components_added)}")
    lines.append(f"- **Components removed:** {len(d.components_removed)}")
    lines.append(f"- **Components changed:** {len(d.components_changed)}")
    lines.append(f"- **Likely renames:** {len(d.likely_renames)}")
    lines.append(f"- **Nets added:** {len(d.nets_added)}")
    lines.append(f"- **Nets removed:** {len(d.nets_removed)}")
    lines.append(f"- **Value tokens added:** {len(d.value_tokens_added)}")
    lines.append(f"- **Value tokens removed:** {len(d.value_tokens_removed)}")
    lines.append("")

    # ---------------------------------------------------------------- components
    if d.components_added:
        lines.append("## Components added")
        lines.append("")
        lines.append("| Ref | Value | Footprint | Description |")
        lines.append("|-----|-------|-----------|-------------|")
        for c in sorted(d.components_added, key=lambda x: _ref_key(x.reference)):
            lines.append(
                f"| `{c.reference}` | {_esc(c.value)} | {_esc(c.footprint)} | {_esc(c.description)} |"
            )
        lines.append("")

    if d.components_removed:
        lines.append("## Components removed")
        lines.append("")
        lines.append("| Ref | Value | Footprint | Description |")
        lines.append("|-----|-------|-----------|-------------|")
        for c in sorted(d.components_removed, key=lambda x: _ref_key(x.reference)):
            lines.append(
                f"| `{c.reference}` | {_esc(c.value)} | {_esc(c.footprint)} | {_esc(c.description)} |"
            )
        lines.append("")

    if d.components_changed:
        lines.append("## Components changed")
        lines.append("")
        lines.append("| Ref | Field | Old | New |")
        lines.append("|-----|-------|-----|-----|")
        for c in d.components_changed:
            lines.append(
                f"| `{c.reference}` | {c.field} | {_esc(c.old)} | {_esc(c.new)} |"
            )
        lines.append("")

    # ---------------------------------------------------------------- renames
    if d.likely_renames:
        lines.append("## Likely renames (heuristic)")
        lines.append("")
        lines.append("| Old | New | Confidence | Reason |")
        lines.append("|-----|-----|-----------:|--------|")
        for r in d.likely_renames:
            lines.append(
                f"| `{r.old}` | `{r.new}` | {r.confidence:.2f} | {_esc(r.reason)} |"
            )
        lines.append("")

    # ---------------------------------------------------------------- nets
    if d.nets_added or d.nets_removed:
        lines.append("## Nets")
        lines.append("")
        if d.nets_added:
            lines.append("**Added:** " + ", ".join(f"`{n}`" for n in d.nets_added))
            lines.append("")
        if d.nets_removed:
            lines.append("**Removed:** " + ", ".join(f"`{n}`" for n in d.nets_removed))
            lines.append("")

    # ---------------------------------------------------------------- value tokens
    if d.value_tokens_added or d.value_tokens_removed:
        lines.append("## Value / footprint / part-number tokens")
        lines.append("")
        lines.append(
            "Tokens extracted from recovered raw text. Useful when the "
            "heuristic component table missed a value change."
        )
        lines.append("")
        if d.value_tokens_added:
            lines.append("**Added:**")
            lines.append("")
            for t in d.value_tokens_added:
                lines.append(f"- `{t}`")
            lines.append("")
        if d.value_tokens_removed:
            lines.append("**Removed:**")
            lines.append("")
            for t in d.value_tokens_removed:
                lines.append(f"- `{t}`")
            lines.append("")

    # ---------------------------------------------------------------- images
    if d.old_images or d.new_images:
        lines.append("## Bundled page images")
        lines.append("")
        lines.append(
            "Attach matching pages from both sides to a multimodal model "
            "for wire-level visual diff."
        )
        lines.append("")
        if d.old_images:
            lines.append("**Old:**")
            lines.append("")
            for p in d.old_images:
                lines.append(f"- `{p}`")
            lines.append("")
        if d.new_images:
            lines.append("**New:**")
            lines.append("")
            for p in d.new_images:
                lines.append(f"- `{p}`")
            lines.append("")

    # ---------------------------------------------------------------- warnings
    if d.warnings:
        lines.append("## ⚠ Warnings")
        lines.append("")
        for w in d.warnings:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)
