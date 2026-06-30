from __future__ import annotations

from pathlib import Path

import fitz


def render_page_png(pdf_path: Path, page_index: int, output_path: Path, zoom: float = 1.6) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_mtime >= pdf_path.stat().st_mtime:
        return output_path

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            raise IndexError(f"Page index out of range: {page_index}")
        page = doc[page_index]
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        pixmap.save(output_path)
        return output_path
    finally:
        doc.close()
