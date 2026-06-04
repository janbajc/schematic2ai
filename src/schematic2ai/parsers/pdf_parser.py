"""
PDF schematic parser.

PDFs are usually rasterized scans or vector exports from EDA tools. We:

  1. Extract any embedded text (titleblock, BOM tables, net labels) with pdfplumber.
  2. Render each page to PNG with pypdfium2 so vision LLMs can see the drawing.
  3. Heuristically pull component references (R1, C12, U3, ...) from the text.

We do **not** try to vectorize wires — that's a research problem. Instead we
hand the AI both the structured text we found *and* a page image bundle, which
modern multimodal models can read directly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..ir import Schematic, Component
from .base import BaseParser
from ._value_extractor import enrich_components_from_text
from ._title_block import extract_title_block
from ._ocr_preprocess import preprocess_for_ocr
from ._tiler import tile_image


# Common reference designator prefixes used on schematics.
_REF_RE = re.compile(
    r"\b("
    r"R|C|L|D|Q|U|IC|J|JP|K|F|FB|TP|SW|S|BT|Y|X|RV|RN|LED|MOV|CN|P"
    r")(\d{1,4})\b"
)


class PdfParser(BaseParser):
    format_name = "pdf"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path, output_dir: Optional[Path] = None) -> Schematic:
        sch = Schematic(source_file=str(path), source_format=self.format_name)
        sch.title = path.stem

        text_blocks: list[str] = []

        # ---- 1. Text extraction --------------------------------------------------
        try:
            import pdfplumber  # type: ignore
        except ImportError:
            sch.add_warning("pdfplumber not installed — skipping text extraction.")
        else:
            try:
                with pdfplumber.open(path) as pdf:
                    sch.metadata["page_count"] = len(pdf.pages)
                    for i, page in enumerate(pdf.pages, start=1):
                        txt = page.extract_text() or ""
                        if txt.strip():
                            text_blocks.append(f"--- Page {i} ---\n{txt}")
            except Exception as e:  # noqa: BLE001
                sch.add_warning(f"pdfplumber failed: {e}")

        sch.raw_text = "\n\n".join(text_blocks)

        # ---- 2. Page rendering ---------------------------------------------------
        # Write page PNGs under the user-specified output directory so they sit
        # next to the JSON/Markdown the CLI emits. Fall back to a sibling of
        # the input file when no output directory was supplied (e.g. when the
        # parser is invoked programmatically).
        base_dir = Path(output_dir) if output_dir is not None else path.parent
        out_img_dir = base_dir / f"{path.stem}_pages"
        try:
            import pypdfium2 as pdfium  # type: ignore
        except ImportError:
            sch.add_warning("pypdfium2 not installed — skipping page rendering.")
        else:
            try:
                out_img_dir.mkdir(parents=True, exist_ok=True)
                pdf = pdfium.PdfDocument(str(path))
                for i, page in enumerate(pdf, start=1):
                    pil_image = page.render(scale=2.0).to_pil()
                    img_path = out_img_dir / f"page_{i:03d}.png"
                    pil_image.save(img_path)
                    sch.images.append(str(img_path))

                    # Tile large pages so vision LLMs can "zoom" into a
                    # specific region without re-rendering the whole sheet.
                    tile_dir = out_img_dir / f"page_{i:03d}_tiles"
                    tiles = tile_image(img_path, tile_dir)
                    if tiles:
                        sch.image_tiles.append({
                            "page": str(img_path),
                            "tiles": [str(t) for t in tiles],
                        })
            except Exception as e:  # noqa: BLE001
                sch.add_warning(f"pypdfium2 render failed: {e}")

        # ---- 3. OCR fallback if no text was extractable --------------------------
        if not sch.raw_text.strip() and sch.images:
            try:
                import pytesseract  # type: ignore
                from PIL import Image  # type: ignore
            except ImportError:
                sch.add_warning(
                    "No embedded text and pytesseract/Pillow missing — install them "
                    "for OCR on scanned schematics."
                )
            else:
                ocr_chunks = []
                for img_path in sch.images:
                    src = Path(img_path)
                    # Preprocess to a high-contrast 1-bit image at ~300 DPI
                    # before OCR; fall back to the original on failure.
                    pre = preprocess_for_ocr(src)
                    target = pre if pre is not None else src
                    try:
                        ocr_chunks.append(
                            f"--- OCR {src.name} ---\n"
                            + pytesseract.image_to_string(Image.open(target))
                        )
                    except Exception as e:  # noqa: BLE001
                        sch.add_warning(f"OCR failed for {img_path}: {e}")
                sch.raw_text = "\n\n".join(ocr_chunks)

        # ---- 4. Heuristic component extraction -----------------------------------
        if sch.raw_text:
            seen: set[str] = set()
            for prefix, num in _REF_RE.findall(sch.raw_text):
                ref = f"{prefix}{num}"
                if ref in seen:
                    continue
                seen.add(ref)
                sch.components.append(Component(reference=ref))
            sch.add_warning(
                "Components were heuristically extracted from text. "
                "Connections were NOT extracted — pass the rendered page images "
                "to a multimodal model for topology."
            )

            # ---- 4b. Populate value/footprint from textual adjacency. -------------
            enriched = enrich_components_from_text(sch.components, sch.raw_text)
            if enriched:
                sch.metadata["enriched_components"] = enriched

            # ---- 4c. Title-block (revision / author / date / title). --------------
            tb = extract_title_block(sch.raw_text)
            if tb.get("revision") and not sch.revision:
                sch.revision = tb["revision"]
            if tb.get("author") and not sch.author:
                sch.author = tb["author"]
            if tb.get("title") and not sch.title:
                sch.title = tb["title"]
            for k in ("date", "sheet", "company"):
                if tb.get(k):
                    sch.metadata.setdefault("title_block", {})[k] = tb[k]

        return sch
