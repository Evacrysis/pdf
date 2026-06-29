from __future__ import annotations

from pathlib import Path

import fitz

from app.models import TranslatedLine
from app.services.line_processing import QUOTE_GAP_RE

DIAGRAM_LABEL_SOURCES = {
    "Knob: Adjust the opening percentage",
    "Open",
    "Close",
    "Stop",
    "Slight Open",
    "Slight Close",
    "Favorite Position",
    "Control All Blinds (max 9 blinds)",
    "1-9 Channel: One channel corresponds to one blind.",
    "Set key P1",
    "Set key P2",
    "Tilt vanes",
    "Adjust the overlap of stripes",
}


def _wrap_text(text: str, font: fitz.Font, font_size: float, max_width: float) -> list[str]:
    if "\n" in text:
        wrapped: list[str] = []
        for paragraph in text.splitlines():
            wrapped.extend(_wrap_text(paragraph, font, font_size, max_width) if paragraph else [""])
        return wrapped
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


def _is_quote_gap_line(text: str) -> bool:
    return bool(QUOTE_GAP_RE.match(" ".join(text.split())))


def _icon_gap_rects(page: fitz.Page, bbox: tuple[float, float, float, float]) -> list[fitz.Rect]:
    source_rect = fitz.Rect(*bbox)
    candidates: list[fitz.Rect] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if not rect:
            continue
        if rect.x0 < source_rect.x0 or rect.x1 > source_rect.x1:
            continue
        if rect.y1 < source_rect.y0 - 4 or rect.y0 > source_rect.y1 + 4:
            continue
        width = rect.width
        height = rect.height
        if 6 <= width <= 22 and 6 <= height <= 22:
            candidates.append(fitz.Rect(rect))
    candidates.sort(key=lambda rect: rect.x0)
    return candidates[:2]


def _redaction_rects(page: fitz.Page, item: TranslatedLine) -> list[fitz.Rect]:
    return [fitz.Rect(*item.source.bbox)]


def _large_artwork_rects(page: fitz.Page) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if not rect:
            continue
        rect = fitz.Rect(rect)
        if rect.width < 55 or rect.height < 55:
            continue
        aspect = rect.width / max(rect.height, 1)
        if 0.55 <= aspect <= 1.85:
            rects.append(rect)
    return rects


def _nearest_artwork_rect(page: fitz.Page, item: TranslatedLine) -> fitz.Rect | None:
    source = " ".join(item.source.text.split())
    if source not in DIAGRAM_LABEL_SOURCES:
        return None
    label = fitz.Rect(*item.source.bbox)
    label_center = fitz.Point((label.x0 + label.x1) / 2, (label.y0 + label.y1) / 2)
    candidates: list[tuple[float, fitz.Rect]] = []
    for rect in _large_artwork_rects(page):
        center = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
        dx = label_center.x - center.x
        dy = label_center.y - center.y
        distance = (dx * dx + dy * dy) ** 0.5
        if distance <= 260:
            candidates.append((distance, rect))
    if not candidates:
        return None
    candidates.sort(key=lambda item_: item_[0])
    return candidates[0][1]


def _diagram_side(page: fitz.Page, item: TranslatedLine) -> tuple[fitz.Rect, str] | None:
    artwork = _nearest_artwork_rect(page, item)
    if artwork is None:
        return None
    label = fitz.Rect(*item.source.bbox)
    label_center_x = (label.x0 + label.x1) / 2
    artwork_center_x = (artwork.x0 + artwork.x1) / 2
    vertically_aligned = label.y0 < artwork.y1 and label.y1 > artwork.y0
    if vertically_aligned and label_center_x < artwork_center_x and label.x0 < artwork.x0:
        return artwork, "left"
    if vertically_aligned and label_center_x > artwork_center_x and label.x1 > artwork.x1:
        return artwork, "right"
    return None


def _max_width(page: fitz.Page, item: TranslatedLine, font: fitz.Font) -> float:
    src = item.source
    x0, _, x1, _ = src.bbox
    original = max(4, x1 - x0)
    available = max(original, page.rect.width - x0 - 36)
    desired = max(
        [font.text_length(line, fontsize=item.output_font_size) for line in item.translated_text.splitlines() if line]
        or [0]
    ) + 2
    diagram_side = _diagram_side(page, item)
    if diagram_side is not None:
        artwork, side = diagram_side
        safe_gap = max(14, item.output_font_size * 1.15)
        if side == "left":
            slot = max(4, artwork.x0 - safe_gap - 36)
        else:
            slot = max(4, page.rect.width - 36 - (artwork.x1 + safe_gap))
        return min(desired, slot) if desired > 0 else slot
    if src.role in {"title", "section_title", "subsection_title", "emphasis"}:
        return max(original, available)
    if desired <= available:
        return max(original, desired)
    if src.role == "body" and original >= 90:
        return max(original, min(available, original * 1.8))
    if src.role == "figure_label":
        return max(original, min(available, original * 2.4))
    return original


def _line_widths(wrapped: list[str], font: fitz.Font, font_size: float) -> list[float]:
    return [font.text_length(line, fontsize=font_size) for line in wrapped]


def _label_start_x(
    page: fitz.Page,
    item: TranslatedLine,
    wrapped: list[str],
    font: fitz.Font,
) -> float:
    label = fitz.Rect(*item.source.bbox)
    diagram_side = _diagram_side(page, item)
    if diagram_side is None:
        return label.x0
    artwork, side = diagram_side
    label_width = max(_line_widths(wrapped, font, item.output_font_size) or [label.width])
    safe_gap = max(14, item.output_font_size * 1.15)
    if side == "left":
        return max(36, artwork.x0 - safe_gap - label_width)
    return min(max(artwork.x1 + safe_gap, label.x0), page.rect.width - 36 - label_width)


def _baseline(item: TranslatedLine) -> float:
    src = item.source
    x0, y0, x1, y1 = src.bbox
    if src.role in {"title", "section_title", "subsection_title"}:
        return y0 + src.font_size * 1.08
    return y1 - (src.font_size * 0.22)


def _insert_text(page: fitz.Page, point: fitz.Point, text: str, font_name: str, font_size: float) -> None:
    if text:
        page.insert_text(point, text, fontname=font_name, fontsize=font_size, color=(0, 0, 0))


def _write_quote_gap_line(
    page: fitz.Page,
    item: TranslatedLine,
    font: fitz.Font,
    font_name: str,
    icon_streams: list[tuple[fitz.Rect, bytes]],
) -> bool:
    if len(icon_streams) < 2:
        return False
    baseline = _baseline(item)
    size = item.output_font_size
    left_open = "「"
    middle = "」または「"
    tail = "」を押す"
    gap = 1.5
    icon_height = size * 0.9
    icon_widths = [icon_height * (rect.width / max(rect.height, 1)) for rect, _ in icon_streams[:2]]
    widths = [
        font.text_length(left_open, fontsize=size),
        font.text_length(middle, fontsize=size),
        font.text_length(tail, fontsize=size),
    ]
    total = sum(widths) + sum(icon_widths) + gap * 4
    x0 = item.source.bbox[0]
    x = min(x0, max(36, page.rect.width - 36 - total))
    icon_top = baseline - icon_height + 2

    _insert_text(page, fitz.Point(x, baseline), left_open, font_name, size)
    x += widths[0] + gap
    page.insert_image(fitz.Rect(x, icon_top, x + icon_widths[0], icon_top + icon_height), stream=icon_streams[0][1], overlay=True)
    x += icon_widths[0] + gap
    _insert_text(page, fitz.Point(x, baseline), middle, font_name, size)
    x += widths[1] + gap
    page.insert_image(fitz.Rect(x, icon_top, x + icon_widths[1], icon_top + icon_height), stream=icon_streams[1][1], overlay=True)
    x += icon_widths[1] + gap
    _insert_text(page, fitz.Point(x, baseline), tail, font_name, size)
    item.wrapped_lines = ["「source-icon」または「source-icon」を押す"]
    return True


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
        quote_icon_streams: dict[int, list[tuple[fitz.Rect, bytes]]] = {}
        for item in items:
            src = item.source
            if not src.localizable:
                continue
            if _is_quote_gap_line(src.text):
                streams: list[tuple[fitz.Rect, bytes]] = []
                for rect in _icon_gap_rects(page, src.bbox):
                    pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=fitz.Rect(rect), alpha=False)
                    streams.append((fitz.Rect(rect), pix.tobytes("png")))
                quote_icon_streams[id(item)] = streams
            for rect in _redaction_rects(page, item):
                if rect.width > 0 and rect.height > 0:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        page.insert_font(fontname=font_name, fontfile=str(font_path))

        for item in items:
            src = item.source
            if not src.localizable:
                continue
            if _is_quote_gap_line(src.text):
                if not _write_quote_gap_line(page, item, font, font_name, quote_icon_streams.get(id(item), [])):
                    raise RuntimeError(
                        f"Protected source icons could not be located for quote-gap line on page {src.page_index + 1}."
                    )
                continue
            max_width = _max_width(page, item, font)
            wrapped = _wrap_text(item.translated_text, font, item.output_font_size, max_width)
            item.wrapped_lines = wrapped
            line_step = item.output_font_size * 1.35
            baseline = _baseline(item)
            x = _label_start_x(page, item, wrapped, font)
            for offset, text in enumerate(wrapped):
                _insert_text(
                    page,
                    fitz.Point(x, baseline + offset * line_step),
                    text,
                    font_name,
                    item.output_font_size,
                )

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_pdf, garbage=4, deflate=True)
    doc.close()
    return translated_lines
