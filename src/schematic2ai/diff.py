"""
Schematic diff engine.

Compares two `Schematic` objects (old / new) and produces a `SchematicDiff`
whose JSON serialization is the canonical AI-readable diff artifact.

Design goals (the consumer is an LLM, not a human):

- **Deterministic**: every list is sorted with a stable key so identical
  inputs always produce byte-identical output.
- **Schema-stable**: top-level keys are always present, even when empty,
  so prompt templates don't break.
- **Token-frugal**: do not duplicate full schematic dumps. Emit only the
  delta. The Markdown writer keeps the high-signal sections first.
- **Honest about uncertainty**: heuristics (e.g. rename detection) carry a
  ``confidence`` score and a short ``reason`` string the model can weigh.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

from .ir import Schematic, Component


# ---------------------------------------------------------------------------
# Diff IR
# ---------------------------------------------------------------------------


@dataclass
class ComponentChange:
    """A component whose ``reference`` exists in both sides but differs."""

    reference: str = ""
    field: str = ""        # "value" | "footprint" | "description"
    old: str = ""
    new: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LikelyRename:
    """Heuristic pairing of a removed ref with an added ref."""

    old: str = ""
    new: str = ""
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SchematicDiff:
    """Canonical, AI-readable diff between two schematics."""

    old_source: str = ""
    new_source: str = ""
    old_title: str = ""
    new_title: str = ""

    # Component-level changes.
    components_added: list[Component] = field(default_factory=list)
    components_removed: list[Component] = field(default_factory=list)
    components_changed: list[ComponentChange] = field(default_factory=list)
    likely_renames: list[LikelyRename] = field(default_factory=list)

    # Net-level changes (best-effort; only meaningful for formats that
    # actually extract nets — KiCad, EAGLE, SPICE).
    nets_added: list[str] = field(default_factory=list)
    nets_removed: list[str] = field(default_factory=list)

    # Token-level diff over recovered raw text (catches value / footprint /
    # part-number changes that the heuristic component extractor missed).
    value_tokens_added: list[str] = field(default_factory=list)
    value_tokens_removed: list[str] = field(default_factory=list)

    # Image bundles from each side — handed through so multimodal models can
    # render both pages side by side.
    old_images: list[str] = field(default_factory=list)
    new_images: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "old_source": self.old_source,
            "new_source": self.new_source,
            "old_title": self.old_title,
            "new_title": self.new_title,
            "components": {
                "added":   [c.to_dict() for c in self.components_added],
                "removed": [c.to_dict() for c in self.components_removed],
                "changed": [c.to_dict() for c in self.components_changed],
                "likely_renames": [r.to_dict() for r in self.likely_renames],
            },
            "nets": {
                "added":   list(self.nets_added),
                "removed": list(self.nets_removed),
            },
            "value_tokens": {
                "added":   list(self.value_tokens_added),
                "removed": list(self.value_tokens_removed),
            },
            "images": {
                "old": list(self.old_images),
                "new": list(self.new_images),
            },
            "warnings": list(self.warnings),
        }

    def summary(self) -> str:
        return (
            f"diff '{self.old_title}' → '{self.new_title}': "
            f"+{len(self.components_added)} / -{len(self.components_removed)} components, "
            f"{len(self.components_changed)} changed, "
            f"{len(self.likely_renames)} likely rename(s), "
            f"+{len(self.nets_added)} / -{len(self.nets_removed)} nets."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_REF_SPLIT_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def _ref_key(ref: str) -> tuple[str, int, str]:
    """Stable natural sort key for reference designators (R1, R2, R10)."""
    m = _REF_SPLIT_RE.match(ref or "")
    if not m:
        return (ref or "", 0, "")
    return (m.group(1), int(m.group(2)), "")


def _ref_prefix(ref: str) -> str:
    m = _REF_SPLIT_RE.match(ref or "")
    return m.group(1) if m else (ref or "")


_VALUE_TOKEN_PATTERNS = [
    # Part-number-ish all-caps identifiers (SY8120B, AT25QF641, W25Q80DVUX, ...).
    re.compile(r"\b[A-Z]{2,}\d{3,}[A-Z0-9_-]*\b"),
    # Footprint strings (C0402_100nF_16V_X7R, L0603_68nH, R0402_10k_5%, ...).
    re.compile(r"\b[CRLD]\d{3,4}_[A-Za-z0-9._%+\-]+\b"),
    # Bare engineering values (4.7uF, 10nH, 100nF, 39MHz, 32.768kHz, ...).
    re.compile(r"\b\d+(?:\.\d+)?(?:uF|nF|pF|mF|nH|uH|mH|MHz|kHz|GHz|kohm|kOhm|Kohms|kohms|ohm|Ohms|mA|A|V|kV)\b"),
]


def _value_tokens(text: str) -> set[str]:
    out: set[str] = set()
    if not text:
        return out
    for pat in _VALUE_TOKEN_PATTERNS:
        out.update(pat.findall(text))
    return out


def _index_components(sch: Schematic) -> dict[str, Component]:
    """Map reference → Component, last-write-wins on duplicates."""
    return {c.reference: c for c in sch.components if c.reference}


def _detect_renames(
    removed: list[Component],
    added: list[Component],
    old_text: str,
    new_text: str,
) -> list[LikelyRename]:
    """
    Pair removed/added components that share a refdes prefix and appear in
    similar neighborhoods of the recovered raw text.

    Heuristic — we don't have schematic topology for PDFs/images, so we rely
    on (a) prefix equality (``U1`` and ``U9`` are both ICs, ``L0`` and ``L2``
    are both inductors) and (b) overlap of nearby raw-text tokens. Each pair
    carries a ``confidence`` in [0, 1] and a short ``reason``.
    """
    if not removed or not added:
        return []

    # Pre-compute a neighborhood (~120 chars window) of each ref in each
    # raw_text blob. This is cheap and works on the PDF parser's output.
    def _neighborhood(text: str, ref: str) -> set[str]:
        if not text or not ref:
            return set()
        ctx: set[str] = set()
        for m in re.finditer(rf"\b{re.escape(ref)}\b", text):
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            window = text[start:end]
            for tok in re.findall(r"\b[A-Za-z][A-Za-z0-9_+\-/]{2,}\b", window):
                if tok != ref:
                    ctx.add(tok)
        return ctx

    old_ctx = {c.reference: _neighborhood(old_text, c.reference) for c in removed}
    new_ctx = {c.reference: _neighborhood(new_text, c.reference) for c in added}

    pairs: list[tuple[float, LikelyRename]] = []
    for r in removed:
        rp = _ref_prefix(r.reference)
        for a in added:
            if _ref_prefix(a.reference) != rp:
                continue
            o, n = old_ctx[r.reference], new_ctx[a.reference]
            if not o or not n:
                # Same-prefix match with no context is weak but still useful
                # when only one candidate exists (handled below).
                conf = 0.3
                reason = "same reference-designator prefix"
            else:
                shared = o & n
                union = o | n
                jacc = len(shared) / len(union) if union else 0.0
                conf = round(0.5 + 0.5 * jacc, 3)  # floor at 0.5 for same prefix
                reason = (
                    f"same prefix '{rp}'; "
                    f"{len(shared)} shared neighborhood tokens "
                    f"(Jaccard {jacc:.2f})"
                )
            pairs.append((conf, LikelyRename(
                old=r.reference, new=a.reference,
                confidence=conf, reason=reason,
            )))

    # Greedy matching: highest-confidence pair first; each ref used at most once.
    pairs.sort(key=lambda p: (-p[0], p[1].old, p[1].new))
    used_old: set[str] = set()
    used_new: set[str] = set()
    out: list[LikelyRename] = []
    for conf, pair in pairs:
        if pair.old in used_old or pair.new in used_new:
            continue
        if conf < 0.3:
            continue
        used_old.add(pair.old)
        used_new.add(pair.new)
        out.append(pair)

    # Deterministic output ordering: by old refdes natural key.
    out.sort(key=lambda r: _ref_key(r.old))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diff_schematics(old: Schematic, new: Schematic) -> SchematicDiff:
    """Compute the canonical diff between *old* and *new* schematics."""
    d = SchematicDiff(
        old_source=old.source_file,
        new_source=new.source_file,
        old_title=old.title or old.source_file,
        new_title=new.title or new.source_file,
        old_images=list(old.images),
        new_images=list(new.images),
    )

    old_idx = _index_components(old)
    new_idx = _index_components(new)

    old_refs = set(old_idx)
    new_refs = set(new_idx)

    added_refs = sorted(new_refs - old_refs, key=_ref_key)
    removed_refs = sorted(old_refs - new_refs, key=_ref_key)
    common_refs = sorted(old_refs & new_refs, key=_ref_key)

    d.components_added = [new_idx[r] for r in added_refs]
    d.components_removed = [old_idx[r] for r in removed_refs]

    for ref in common_refs:
        a, b = old_idx[ref], new_idx[ref]
        for field_name in ("value", "footprint", "description"):
            ov = getattr(a, field_name) or ""
            nv = getattr(b, field_name) or ""
            if ov != nv:
                d.components_changed.append(ComponentChange(
                    reference=ref, field=field_name, old=ov, new=nv,
                ))
    d.components_changed.sort(key=lambda c: (_ref_key(c.reference), c.field))

    # Rename detection.
    d.likely_renames = _detect_renames(
        d.components_removed, d.components_added,
        old.raw_text or "", new.raw_text or "",
    )

    # Net-level diff (only useful for parsers that produce nets).
    old_nets = {n.name for n in old.nets if n.name}
    new_nets = {n.name for n in new.nets if n.name}
    d.nets_added = sorted(new_nets - old_nets)
    d.nets_removed = sorted(old_nets - new_nets)

    # Value/footprint/part-number token diff over recovered raw text.
    ot = _value_tokens(old.raw_text or "")
    nt = _value_tokens(new.raw_text or "")
    d.value_tokens_added = sorted(nt - ot)
    d.value_tokens_removed = sorted(ot - nt)

    # Warnings worth surfacing to the model.
    if old.source_format != new.source_format:
        d.warnings.append(
            f"Comparing different source formats: '{old.source_format}' vs "
            f"'{new.source_format}'. Extraction quality may differ."
        )
    if old.source_format in {"pdf", "image"} or new.source_format in {"pdf", "image"}:
        d.warnings.append(
            "At least one input is a PDF/image: components were heuristically "
            "extracted from text and nets are not available. Treat 'added'/"
            "'removed' lists as suggestive; confirm against the page images."
        )

    return d


__all__ = [
    "SchematicDiff",
    "ComponentChange",
    "LikelyRename",
    "diff_schematics",
]
