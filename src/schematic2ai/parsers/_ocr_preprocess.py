"""
Pre-process raster images before handing them to Tesseract OCR.

Tesseract's accuracy is highly sensitive to image quality. Schematic page
renders are usually clean line art, but they're often rendered at the PDF's
native DPI (~150) which is below Tesseract's sweet spot (~300 DPI for line
art). We apply a small fixed pipeline that consistently improves accuracy
on EDA-style schematic pages:

  1. Convert to grayscale.
  2. Auto-contrast.
  3. Upscale (Lanczos) to at least ~300 effective DPI.
  4. Binarize (Otsu via PIL).

The result is a high-contrast, sharp 1-bit image that Tesseract reads well.

If Pillow is unavailable we return the input unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Effective DPI we aim for after upscaling. 300 is Tesseract's documented
# preferred range for line art / small fonts.
_TARGET_DPI = 300


def preprocess_for_ocr(image_path: Path) -> Optional[Path]:
    """
    Return a path to a preprocessed copy of *image_path* suitable for
    Tesseract. Writes the copy as ``<stem>.ocr.png`` next to the source.

    Returns ``None`` if Pillow is missing or the image cannot be opened —
    callers should fall back to the original.
    """
    try:
        from PIL import Image, ImageOps  # type: ignore
    except ImportError:
        return None

    try:
        img = Image.open(image_path)
    except Exception:
        return None

    # 1. Grayscale.
    img = img.convert("L")

    # 2. Auto-contrast (clip 1 % on each side to avoid washing out ink).
    img = ImageOps.autocontrast(img, cutoff=1)

    # 3. Upscale. Page renders from `pypdfium2` carry DPI metadata in
    #    ``info['dpi']`` when present; otherwise assume 144 DPI (which is
    #    the default 2× scale on letter / A-size pages).
    src_dpi = 144
    try:
        d = img.info.get("dpi")
        if isinstance(d, tuple) and d and d[0]:
            src_dpi = int(d[0])
    except Exception:
        pass
    if src_dpi < _TARGET_DPI:
        scale = _TARGET_DPI / float(src_dpi)
        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)

    # 4. Binarize using a simple global threshold. (PIL's ``point`` is fast
    #    and avoids pulling in numpy / opencv.)
    threshold = 180
    img = img.point(lambda v, t=threshold: 255 if v > t else 0, mode="1")

    out_path = image_path.with_suffix(".ocr.png")
    try:
        img.save(out_path, optimize=True)
    except Exception:
        return None
    return out_path


__all__ = ["preprocess_for_ocr"]
