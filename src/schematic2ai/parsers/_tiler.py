"""
Slice a large page image into overlapping tiles for vision-LLM consumption.

Schematic pages are frequently rendered at sizes (e.g. 3168×2448 px for a
1584×1224 pt PDF at 2× scale) where small text in dense corners becomes
hard for vision models to read. Splitting the page into a grid of
overlapping tiles lets the model "zoom in" on the relevant region — and
because each tile is referenced separately in the Markdown, the model can
load only the tile(s) it needs.

We tile **only when the page is large enough to benefit** (heuristic
threshold on the longer edge). The original page render is always kept;
tiles are additive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


# Tile the page when its longer edge exceeds this many pixels.
_TILE_THRESHOLD_PX = 2200

# Default grid (rows × cols) and per-edge overlap in pixels.
_DEFAULT_ROWS = 3
_DEFAULT_COLS = 4
_DEFAULT_OVERLAP = 96


def tile_image(
    image_path: Path,
    out_dir: Path,
    rows: int = _DEFAULT_ROWS,
    cols: int = _DEFAULT_COLS,
    overlap_px: int = _DEFAULT_OVERLAP,
    threshold_px: int = _TILE_THRESHOLD_PX,
) -> list[Path]:
    """
    Tile *image_path* into ``rows × cols`` overlapping PNGs under *out_dir*.

    Returns the list of tile paths written, sorted row-major. If the image
    is below the size threshold or Pillow is unavailable, returns an empty
    list (the original image is fine as-is).
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return []

    try:
        img = Image.open(image_path)
    except Exception:
        return []

    w, h = img.size
    if max(w, h) < threshold_px:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)

    tile_w = w // cols
    tile_h = h // rows
    written: list[Path] = []

    for r in range(rows):
        for c in range(cols):
            x0 = max(0, c * tile_w - overlap_px)
            y0 = max(0, r * tile_h - overlap_px)
            x1 = min(w, (c + 1) * tile_w + overlap_px)
            y1 = min(h, (r + 1) * tile_h + overlap_px)
            crop = img.crop((x0, y0, x1, y1))
            tile_path = out_dir / f"r{r}c{c}.png"
            try:
                crop.save(tile_path, optimize=True)
            except Exception:
                continue
            written.append(tile_path)
    return written


__all__ = ["tile_image"]
