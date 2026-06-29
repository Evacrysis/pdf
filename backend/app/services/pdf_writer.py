from __future__ import annotations

from pathlib import Path

import fitz

from app.models import TranslatedLine


def _wrap_text(text: str, font: fitz.Font, font_size: float, max_width: float) -> list[str]:
    if font.text_length(text, fontsize=font_size) <= max_width:
        return [text]
    parts: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and font.text_length(candidate, fontsize=font_size) > max_width:
            parts.append(current)
            current = char
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def write_editable_pdf(
    source_pdf: Path,
    output_pdf: Path,
    translated_lines: list[TranslatedLine],
    font_path: Path,
) -> list[TranslatedLine]:
    if not font_path.exists():
        raise RuntimeError(f"Configured PDF font does not exist: {font_path}")
    if font_path.suffix.lower() != ".ttf":
        raise RuntimeError(
            "Configured PDF font must be a TrueType .ttf file. "
            "CFF/OpenType fonts can extract as Japanese but render as corrupt glyphs in generated PDFs."
        )

    doc = fitz.open(source_pdf)
    font = fitz.Font(fontfile=str(font_path))
    font_name = "F0"
    by_page: dict[int, list[TranslatedLine]] = {}
    for item in translated_lines:
        by_page.setdefault(item.source.page_index, []).append(item)

    for page_index, items in by_page.items():
        page = doc[page_index]
        for item in items:
            src = item.source
            if not src.localizable:
                continue
            x0, y0, x1, y1 = src.bbox
            rect = fitz.Rect(x0, y0, x1, y1)
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        page.insert_font(fontname=font_name, fontfile=str(font_path))

        for item in items:
            src = item.source
            if not src.localizable:
                continue
            x0, y0, x1, y1 = src.bbox
            max_width = max(4, x1 - x0)
            wrapped = _wrap_text(item.translated_text, font, item.output_font_size, max_width)
            item.wrapped_lines = wrapped
            line_step = item.output_font_size * 1.35
            baseline = y1 - (src.font_size * 0.22)
            for offset, text in enumerate(wrapped):
                page.insert_text(
                    fitz.Point(x0, baseline + offset * line_step),
                    text,
                    fontname=font_name,
                    fontsize=item.output_font_size,
                    color=(0, 0, 0),
                )

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_pdf, garbage=4, deflate=True)
    doc.close()
    return translated_lines
