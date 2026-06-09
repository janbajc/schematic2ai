# schematic2ai

Convert electronic schematics into **AI-readable** files (JSON + Markdown) so
you can hand them to an LLM.

## Supported inputs

| Format            | Extension(s)                      | Extraction quality           |
|-------------------|-----------------------------------|------------------------------|
| KiCad             | `.kicad_sch`, `.sch` (legacy)     | Components + named nets      |
| EAGLE             | `.sch` (XML)                      | Components + nets + pinrefs  |
| Altium            | `.SchDoc`, `.SchLib`              | Best-effort string scrape    |
| SPICE netlist     | `.cir`, `.sp`, `.net`, `.spice`   | Full netlist (components + connections) |
| PDF schematic     | `.pdf`                            | Text + rendered page images  |
| Image schematic   | `.png`, `.jpg`, `.tif`, ...       | OCR text + image passthrough |
| Gerber (PCB)      | `.gbr`, `.gtl`, `.gbl`, ...       | Summary only (PCB, not schematic) |

## Outputs

For an input `acme.pdf` you get:

```
out/
├── acme.json            # structured (components, nets, connections, metadata)
├── acme.md              # LLM-friendly narrative
└── acme_pages/          # (PDFs only) one PNG per page
    ├── page_001.png
    └── page_002.png
```

The Markdown file is what you paste/upload into an AI chat. The JSON file is
what your code consumes. PDFs and images also produce a bundle of PNGs you can
attach to multimodal models (GPT-4o, Claude, Gemini, etc.).

## Install

```bash
cd schematic2ai
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

OCR for image/PDF schematics also needs the `tesseract` binary installed on
your system (e.g. `sudo apt install tesseract-ocr` on Debian/Ubuntu).

## Usage

The tool installs **three equivalent commands** — use whichever you prefer:

| Command        | Notes                          |
|----------------|--------------------------------|
| `sch2ai`       | Shortest. Recommended.         |
| `schtoai`      | Alternate short form.          |
| `schematic2ai` | Full name (back-compat).       |

```bash
# Convert one schematic (this is also `sch2ai convert PATH`).
sch2ai path/to/schematic.pdf
sch2ai design.kicad_sch -o out/ --format json
sch2ai amplifier.cir --format md

# Diff two revisions of the same schematic.
sch2ai diff old.pdf new.pdf -o out/
```

CLI options (apply to both `convert` and `diff`):

- `-o, --output-dir DIR` — where to write artifacts (default: `out/`).
- `-f, --format {json,md,both}` — choose exporters (default: `both`).
- `--quiet` — suppress progress output.

### Diffing two schematics

`sch2ai diff OLD NEW` parses both inputs and writes an AI-readable delta
alongside the individual schematic artifacts:

```
out/
├── OLD.json / OLD.md / OLD_pages/         # per-side IR
├── NEW.json / NEW.md / NEW_pages/         # per-side IR
├── OLD__vs__NEW.diff.json                 # deterministic, schema-stable
└── OLD__vs__NEW.diff.md                   # LLM narrative of the delta
```

The diff is **deterministic** (running it twice with the same inputs and
the same `-o` directory produces byte-identical files) and **token-frugal**
(it never embeds the full raw text of either side — only the delta). For
PDF/image inputs it also detects likely refdes renames heuristically and
annotates them with a confidence score and a short reason the model can
weigh.

## How to feed the output to an AI

For **text-only** LLMs, paste the contents of `out/<name>.md`. It contains a
components table, net list, connections, warnings about extraction quality, and
any recovered raw text.

For **multimodal** LLMs, additionally upload the PNGs listed under
"Bundled images" in the Markdown file. The AI can then visually read wires
and symbols that the parser couldn't recover (especially from PDFs and scans).

For **programmatic** use, load `out/<name>.json` — it's a stable schema with a
`schema_version` field. Example:

```python
import json
data = json.loads(open("out/amplifier.json").read())["schematic"]
for comp in data["components"]:
    print(comp["reference"], comp["value"])
```

## Architecture

```
input file
    │
    ▼
┌─────────────┐  detect_parser()  ┌──────────────────────────┐
│  parsers/   │ ─────────────────►│  Schematic (IR)          │
│  pdf, kicad,│                   │   components, nets,      │
│  eagle, ... │                   │   connections, raw_text, │
└─────────────┘                   │   images, warnings       │
                                  └────────────┬─────────────┘
                                               │
                            ┌──────────────────┴──────────────────┐
                            ▼                                     ▼
                  ┌───────────────────┐                ┌───────────────────┐
                  │ json_exporter     │                │ markdown_exporter │
                  └───────────────────┘                └───────────────────┘
```

The IR (`src/schematic2ai/ir.py`) is the contract every parser fills and every
exporter consumes. To add a new input format, write a parser in
`src/schematic2ai/parsers/` subclassing `BaseParser` and register it in
`parsers/__init__.py`.

## Limitations

- PDFs of scanned schematics are not vectorized — wires/symbols are not
  recovered. The page images are passed through for vision LLMs.
- Altium `.SchDoc` is a proprietary binary; only ASCII strings are recovered.
  Export to PDF from Altium for best results.
- KiCad net resolution is approximate — only *named* labels become nets. For
  ground-truth, use `kicad-cli sch export netlist` and feed the resulting SPICE
  netlist to `schematic2ai`.

## Benchmarking

The repo ships two complementary benchmarks under `benchmarks/` and
`tests/benchmarks/`. Install the dev extras first:

```bash
pip install -e ".[dev]"
```

### Accuracy (extraction quality)

`benchmarks/accuracy.py` scores every example against the ground truth in
`benchmarks/ground_truth.yaml` and reports, per file and in aggregate:

- **format detection** — was the right parser selected?
- **component precision / recall / F1** — by reference designator
- **net recall** — by net name (where ground truth lists nets)
- **connection-count ratio** — extracted vs. expected
- **classification accuracy** — fraction of components whose inferred `kind`
  matches the expected category
- **parse time** per file

```bash
python benchmarks/accuracy.py                       # human-readable table
python benchmarks/accuracy.py --json                # machine-readable
python benchmarks/accuracy.py --min-f1 0.95 --min-kind-acc 1.0   # gate CI
```

The script exits non-zero if format detection regresses or a threshold is
missed, so it can be wired into CI. Add a new example by dropping the file in
`examples/` and adding an entry to `ground_truth.yaml`.

### Performance (speed)

`tests/benchmarks/test_perf.py` uses
[`pytest-benchmark`](https://pytest-benchmark.readthedocs.io/) to measure parse
throughput and full parse→JSON→Markdown export latency. Benchmarks are marked
`benchmark` and **excluded from the normal test run** so the suite stays fast;
run them explicitly:

```bash
pytest tests/benchmarks -m benchmark --benchmark-only
```

Useful flags: `--benchmark-columns=min,mean,max`, `--benchmark-autosave` to
record a baseline, and `--benchmark-compare` to diff against it.

### Determinism

The diff output is contractually byte-identical across runs. Verify with:

```bash
sch2ai diff examples/amplifier.cir examples/diff_pair.cir -o /tmp/d1 --quiet
sch2ai diff examples/amplifier.cir examples/diff_pair.cir -o /tmp/d2 --quiet
diff -r /tmp/d1 /tmp/d2 && echo "deterministic ✓"
```

## License

MIT
