"""Image (PNG/JPG/etc.) schematic parser — OCR + reference-designator scan."""

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


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

_REF_RE = re.compile(
    r"\b(R|C|L|D|Q|U|IC|J|JP|K|F|FB|TP|SW|S|BT|Y|X|RV|RN|LED|MOV|CN|P)(\d{1,4})\b"
)


class ImageParser(BaseParser):
    format_name = "image"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        return path.suffix.lower() in _IMAGE_EXTS

    def parse(self, path: Path, output_dir: Optional[Path] = None) -> Schematic:
        sch = Schematic(source_file=str(path), source_format=self.format_name)
        sch.title = path.stem
        sch.images.append(str(path))

        # Tile large images so vision LLMs can "zoom in" without re-cropping.
        tile_base = Path(output_dir) if output_dir is not None else path.parent
        tile_dir = tile_base / f"{path.stem}_tiles"
        tiles = tile_image(path, tile_dir)
        if tiles:
            sch.image_tiles.append({
                "page": str(path),
                "tiles": [str(t) for t in tiles],
            })

        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
        except ImportError:
            sch.add_warning(
                "pytesseract/Pillow not installed — cannot OCR. "
                "The raw image is still bundled for vision models."
            )
            return sch

        pre = preprocess_for_ocr(path)
        ocr_target = pre if pre is not None else path
        try:
            sch.raw_text = pytesseract.image_to_string(Image.open(ocr_target))
        except Exception as e:  # noqa: BLE001
            sch.add_warning(f"OCR failed: {e}")
            return sch

        seen: set[str] = set()
        for prefix, num in _REF_RE.findall(sch.raw_text):
            ref = f"{prefix}{num}"
            if ref in seen:
                continue
            seen.add(ref)
            sch.components.append(Component(reference=ref))

        sch.add_warning(
            "Components were heuristically extracted from OCR text. "
            "Connections were NOT extracted — pass the image to a multimodal model."
        )

        # Populate value/footprint and title-block from OCR text.
        enriched = enrich_components_from_text(sch.components, sch.raw_text)
        if enriched:
            sch.metadata["enriched_components"] = enriched
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
