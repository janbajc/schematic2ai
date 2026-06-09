#!/usr/bin/env python3
"""Accuracy benchmark for schematic2ai parsers.

Scores each example schematic against the ground truth in
``benchmarks/ground_truth.yaml`` and prints a per-file and aggregate report
covering:

  * **format detection** — did the right parser get picked?
  * **component recall / precision / F1** — by reference designator
  * **net recall** — by net name (only checked when listed in ground truth)
  * **connection-count ratio** — extracted vs. expected
  * **classification accuracy** — fraction of components whose inferred
    ``kind`` matches the expected category
  * **wall-clock parse time** per file

Usage::

    python benchmarks/accuracy.py
    python benchmarks/accuracy.py --json          # machine-readable output
    python benchmarks/accuracy.py --min-f1 0.95   # exit non-zero if below

Exit code is non-zero when any thresholds are violated, so it can gate CI.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import yaml

# Make the package importable when run straight from the repo.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from schematic2ai.parsers import parse, detect_parser  # noqa: E402


GROUND_TRUTH = Path(__file__).resolve().parent / "ground_truth.yaml"


# ---------------------------------------------------------------------------
# Scoring primitives
# ---------------------------------------------------------------------------


@dataclass
class SetScore:
    """Precision/recall/F1 for a set-vs-set comparison."""
    expected: int = 0
    found: int = 0
    correct: int = 0
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.correct / self.found if self.found else 1.0

    @property
    def recall(self) -> float:
        return self.correct / self.expected if self.expected else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 1.0


def _score_sets(expected: set[str], found: set[str]) -> SetScore:
    correct = expected & found
    return SetScore(
        expected=len(expected),
        found=len(found),
        correct=len(correct),
        missing=sorted(expected - found),
        extra=sorted(found - expected),
    )


@dataclass
class FileResult:
    file: str
    format_expected: str
    format_detected: str
    format_ok: bool
    components: SetScore
    nets: Optional[SetScore]
    connections_expected: int
    connections_found: int
    kind_total: int
    kind_correct: int
    kind_mismatches: dict[str, str]
    parse_seconds: float

    @property
    def connection_ratio(self) -> float:
        if not self.connections_expected:
            return 1.0
        return self.connections_found / self.connections_expected

    @property
    def kind_accuracy(self) -> float:
        return self.kind_correct / self.kind_total if self.kind_total else 1.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["components"] = {
            **asdict(self.components),
            "precision": round(self.components.precision, 4),
            "recall": round(self.components.recall, 4),
            "f1": round(self.components.f1, 4),
        }
        if self.nets is not None:
            d["nets"] = {
                **asdict(self.nets),
                "recall": round(self.nets.recall, 4),
            }
        d["connection_ratio"] = round(self.connection_ratio, 4)
        d["kind_accuracy"] = round(self.kind_accuracy, 4)
        d["parse_seconds"] = round(self.parse_seconds, 6)
        return d


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


def _score_file(rel_path: str, spec: dict[str, Any]) -> FileResult:
    path = REPO_ROOT / rel_path

    detected_cls = detect_parser(path)
    detected = detected_cls.format_name if detected_cls else "(none)"

    t0 = time.perf_counter()
    sch = parse(path)
    elapsed = time.perf_counter() - t0

    # Components by reference designator.
    expected_refs = set(spec.get("components", []))
    found_refs = {c.reference for c in sch.components}
    comp_score = _score_sets(expected_refs, found_refs)

    # Nets (optional in ground truth).
    net_score: Optional[SetScore] = None
    if "nets" in spec:
        expected_nets = {str(n) for n in spec["nets"]}
        found_nets = {n.name for n in sch.nets}
        net_score = _score_sets(expected_nets, found_nets)

    # Classification accuracy.
    kinds_spec: dict[str, str] = spec.get("kinds", {})
    by_ref = {c.reference: c for c in sch.components}
    kind_correct = 0
    mismatches: dict[str, str] = {}
    for ref, expected_kind in kinds_spec.items():
        comp = by_ref.get(ref)
        actual = comp.classified_kind(sch.source_format) if comp else "(missing)"
        if actual == expected_kind:
            kind_correct += 1
        else:
            mismatches[ref] = f"expected={expected_kind!r} got={actual!r}"

    return FileResult(
        file=rel_path,
        format_expected=spec.get("format", ""),
        format_detected=detected,
        format_ok=(detected == spec.get("format", "")),
        components=comp_score,
        nets=net_score,
        connections_expected=int(spec.get("connections", 0)),
        connections_found=len(sch.connections),
        kind_total=len(kinds_spec),
        kind_correct=kind_correct,
        kind_mismatches=mismatches,
        parse_seconds=elapsed,
    )


def run() -> list[FileResult]:
    truth = yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8")) or {}
    return [_score_file(rel, spec) for rel, spec in truth.items()]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_human(results: list[FileResult]) -> None:
    print(f"{'file':<34} {'fmt':>5} {'comp-F1':>8} {'net-rec':>8} "
          f"{'conn':>9} {'kind-acc':>9} {'ms':>7}")
    print("-" * 88)
    for r in results:
        net_rec = f"{r.nets.recall:.2f}" if r.nets is not None else "  -"
        conn = f"{r.connections_found}/{r.connections_expected}"
        print(
            f"{Path(r.file).name:<34} "
            f"{'ok' if r.format_ok else 'BAD':>5} "
            f"{r.components.f1:>8.3f} "
            f"{net_rec:>8} "
            f"{conn:>9} "
            f"{r.kind_accuracy:>9.3f} "
            f"{r.parse_seconds * 1000:>7.2f}"
        )
        if r.components.missing:
            print(f"    ! missing components: {r.components.missing}")
        if r.components.extra:
            print(f"    ! extra components:   {r.components.extra}")
        if r.kind_mismatches:
            for ref, msg in r.kind_mismatches.items():
                print(f"    ! kind[{ref}]: {msg}")

    print("-" * 88)
    n = len(results) or 1
    print(
        f"AGGREGATE  format={sum(r.format_ok for r in results)}/{len(results)}  "
        f"comp-F1={sum(r.components.f1 for r in results) / n:.3f}  "
        f"kind-acc={sum(r.kind_accuracy for r in results) / n:.3f}  "
        f"total-parse={sum(r.parse_seconds for r in results) * 1000:.2f} ms"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    ap.add_argument("--min-f1", type=float, default=None,
                    help="Fail (exit 1) if mean component F1 is below this.")
    ap.add_argument("--min-kind-acc", type=float, default=None,
                    help="Fail (exit 1) if mean classification accuracy is below this.")
    args = ap.parse_args()

    results = run()

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        _print_human(results)

    n = len(results) or 1
    mean_f1 = sum(r.components.f1 for r in results) / n
    mean_kind = sum(r.kind_accuracy for r in results) / n

    failed = False
    if not all(r.format_ok for r in results):
        print("FAIL: format detection regression", file=sys.stderr)
        failed = True
    if args.min_f1 is not None and mean_f1 < args.min_f1:
        print(f"FAIL: mean component F1 {mean_f1:.3f} < {args.min_f1}", file=sys.stderr)
        failed = True
    if args.min_kind_acc is not None and mean_kind < args.min_kind_acc:
        print(f"FAIL: mean kind accuracy {mean_kind:.3f} < {args.min_kind_acc}", file=sys.stderr)
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
