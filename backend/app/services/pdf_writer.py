from __future__ import annotations

from pathlib import Path

import fitz

from app.models import TranslatedLine
from app.services.line_processing import QUOTE_BLANK_RE, QUOTE_GAP_RE, fixed_translation_for

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

PAGE_FALLBACK_MARGIN = 36.0


def _content_safe_bounds(page: fitz.Page) -> tuple[float, float]:
    """Return the horizontal visual content frame for the current source page."""
    page_rect = page.rect
    page_width = float(page_rect.width)
    long_rules: list[fitz.Rect] = []

    def add_rule(x0: float, y0: float, x1: float, y1: float) -> None:
        left = max(float(page_rect.x0), min(float(x0), float(x1)))
        right = min(float(page_rect.x1), max(float(x0), float(x1)))
        top = max(float(page_rect.y0), min(float(y0), float(y1)))
        bottom = min(float(page_rect.y1), max(float(y0), float(y1)))
        width = right - left
        height = bottom - top
        if width < max(220.0, page_width * 0.45):
            return
        if width > page_width * 0.92:
            return
        if height > 6:
            return
        if left < 12 or right > page_width - 12:
            return
        if top > page_rect.height * 0.55:
            return
        long_rules.append(fitz.Rect(left, top, right, max(bottom, top + 0.1)))

    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect:
            rect = fitz.Rect(rect)
            add_rule(rect.x0, rect.y0, rect.x1, rect.y1)
        for item in drawing.get("items", []):
            if not item or item[0] != "l" or len(item) < 3:
                continue
            start, end = item[1], item[2]
            if abs(start.y - end.y) <= 2:
                add_rule(start.x, start.y, end.x, end.y)

    if long_rules:
        best = max(long_rules, key=lambda rect: (rect.width, -rect.y0))
        return float(best.x0), float(best.x1)

    return PAGE_FALLBACK_MARGIN, page_width - PAGE_FALLBACK_MARGIN


def _clamp_to_safe_x(page: fitz.Page, x: float, width: float) -> float:
    safe_left, safe_right = _content_safe_bounds(page)
    rightmost = max(safe_left, safe_right - max(0, width))
    return min(max(x, safe_left), rightmost)


def _wrap_text(text: str, font: fitz.Font, font_size: float, max_width: float) -> list[str]:
    if "\n" in text:
        wrapped: list[str] = []
        for paragraph in text.splitlines():
            wrapped.extend(_wrap_text(paragraph, font, font_size, max_width) if paragraph else [""])
        return wrapped
    if font.text_length(text, fontsize=font_size) <= max_width:
        return [text]
    for marker in ("ランプ", "点灯", "充電済み"):
        if marker in text and not text.startswith(marker):
            prefix = text[: text.index(marker)]
            suffix = text[text.index(marker) :]
            if prefix and font.text_length(prefix, fontsize=font_size) <= max_width and font.text_length(suffix, fontsize=font_size) <= max_width:
                return [prefix, suffix]
    parts: list[str] = []
    current = ""
    line_start_prohibited = set("。、．，」』】）〕］｝・：；ー！？")
    for char in text:
        candidate = current + char
        if current and font.text_length(candidate, fontsize=font_size) > max_width:
            if char in line_start_prohibited:
                parts.append(candidate)
                current = ""
            else:
                parts.append(current)
                current = char
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _layout_text(item: TranslatedLine) -> str:
    if _is_quote_gap_line(item.source.text) or _is_source_icon_template_line(item):
        return item.translated_text
    fixed_translation = fixed_translation_for(item.source)
    if fixed_translation is not None and item.translated_text == fixed_translation:
        return item.translated_text
    return " ".join(part.strip() for part in item.translated_text.splitlines() if part.strip())


def _is_quote_gap_line(text: str) -> bool:
    return bool(QUOTE_GAP_RE.match(" ".join(text.split())))


def _is_source_icon_template_line(item: TranslatedLine) -> bool:
    return "□" in item.translated_text and bool(QUOTE_BLANK_RE.search(item.source.text))


def _placeholder_count(text: str) -> int:
    return text.count("□")


def _cluster_icon_rects(rects: list[fitz.Rect]) -> list[fitz.Rect]:
    clusters: list[fitz.Rect] = []
    for rect in sorted(rects, key=lambda item: (item.x0, item.y0)):
        matched = False
        center = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
        for index, existing in enumerate(clusters):
            existing_center = fitz.Point((existing.x0 + existing.x1) / 2, (existing.y0 + existing.y1) / 2)
            if abs(center.x - existing_center.x) <= 5 and abs(center.y - existing_center.y) <= 5:
                clusters[index] = existing | rect
                matched = True
                break
        if not matched:
            clusters.append(fitz.Rect(rect))
    return clusters


def _normalized_quote_key(text: str) -> str:
    return QUOTE_BLANK_RE.sub('"□"', " ".join(text.split()))


def _raw_line_text(line: dict) -> str:
    return "".join("".join(char.get("c", "") for char in span.get("chars", [])) for span in line.get("spans", []))


def _raw_line_chars(line: dict) -> list[dict]:
    chars: list[dict] = []
    for span in line.get("spans", []):
        chars.extend(span.get("chars", []))
    return chars


def _quote_blank_rects(page: fitz.Page, text: str, bbox: tuple[float, float, float, float], font_size: float) -> list[fitz.Rect]:
    source_key = _normalized_quote_key(text)
    if not source_key:
        return []
    source_rect = fitz.Rect(*bbox)
    search_rect = source_rect + (-3, -3, 3, 3)
    rects: list[fitz.Rect] = []
    for block in page.get_text("rawdict").get("blocks", []):
        for line in block.get("lines", []):
            line_bbox = fitz.Rect(line.get("bbox", (0, 0, 0, 0)))
            if not search_rect.intersects(line_bbox):
                continue
            if abs(line_bbox.y0 - source_rect.y0) > max(4.0, font_size * 0.6):
                continue
            line_text = _raw_line_text(line)
            line_key = _normalized_quote_key(line_text)
            if '"□"' not in line_key:
                continue
            if line_key and not (source_key.startswith(line_key.strip()) or line_key.startswith(source_key.strip())):
                continue
            chars = _raw_line_chars(line)
            index = 0
            while index < len(chars):
                if chars[index].get("c") != '"':
                    index += 1
                    continue
                end = index + 1
                while end < len(chars) and chars[end].get("c") != '"':
                    end += 1
                if end >= len(chars):
                    break
                inner = chars[index + 1 : end]
                if inner and all(char.get("c", "").isspace() or char.get("c") == "\u00a0" for char in inner):
                    opening = fitz.Rect(chars[index].get("bbox"))
                    closing = fitz.Rect(chars[end].get("bbox"))
                    x0 = opening.x1
                    x1 = closing.x0
                    if x1 <= x0:
                        center = (opening.x1 + closing.x0) / 2
                        x0 = center - max(1.0, font_size * 0.18)
                        x1 = center + max(1.0, font_size * 0.18)
                    rects.append(fitz.Rect(x0, line_bbox.y0, x1, line_bbox.y1))
                index = end + 1
    if rects:
        return rects

    normalized = " ".join(text.split())
    if not normalized:
        return []
    row_height = min(source_rect.height, font_size * 1.8)
    for match in QUOTE_BLANK_RE.finditer(normalized):
        x0 = source_rect.x0 + source_rect.width * (match.start() / len(normalized))
        x1 = source_rect.x0 + source_rect.width * (match.end() / len(normalized))
        rects.append(fitz.Rect(x0, source_rect.y0, x1, source_rect.y0 + row_height))
    return rects


def _drawing_icon_candidates(page: fitz.Page, search_rect: fitz.Rect) -> list[fitz.Rect]:
    candidates: list[fitz.Rect] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if not rect:
            continue
        rect = fitz.Rect(rect)
        if not search_rect.intersects(rect):
            continue
        width = rect.width
        height = rect.height
        if 2 <= width <= 28 and 2 <= height <= 28:
            candidates.append(rect)
    return candidates


def _source_icon_rect_for_quote(page: fitz.Page, quote_rect: fitz.Rect, font_size: float) -> fitz.Rect | None:
    search_rect = quote_rect + (-2, -5, 2, 5)
    candidates = []
    for rect in _drawing_icon_candidates(page, search_rect):
        center_y = (rect.y0 + rect.y1) / 2
        horizontal_overlap = max(0.0, min(rect.x1, search_rect.x1) - max(rect.x0, search_rect.x0))
        required_overlap = min(rect.width, quote_rect.width) * 0.25
        if search_rect.y0 <= center_y <= search_rect.y1 and horizontal_overlap >= required_overlap:
            candidates.append(rect)
    if not candidates:
        return None
    icon_rect = fitz.Rect(candidates[0])
    for rect in candidates[1:]:
        icon_rect |= rect
    max_width = max(2.0, quote_rect.width + font_size * 0.65)
    max_height = max(2.0, quote_rect.height + font_size * 0.35)
    if icon_rect.width > max_width or icon_rect.height > max_height:
        return None
    return icon_rect


def _icon_gap_rects(
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    needed: int = 2,
    source_text: str = "",
    font_size: float = 14,
) -> list[fitz.Rect]:
    source_rect = fitz.Rect(*bbox)
    quote_rects = _quote_blank_rects(page, source_text, bbox, font_size)
    if quote_rects:
        selected: list[fitz.Rect] = []
        for quote_rect in quote_rects[:needed]:
            icon_rect = _source_icon_rect_for_quote(page, quote_rect, font_size)
            if icon_rect is not None:
                selected.append(icon_rect)
        if len(selected) >= needed:
            selected.sort(key=lambda rect: rect.x0)
            return selected[:needed]
        return []

    expanded = source_rect + (-8, -14, 8, 14)
    clustered = _cluster_icon_rects(_drawing_icon_candidates(page, expanded))
    clustered.sort(key=lambda rect: rect.x0)
    return clustered[:needed]


def _redaction_rects(page: fitz.Page, item: TranslatedLine) -> list[fitz.Rect]:
    rect = fitz.Rect(*item.source.bbox)
    if item.source.role == "section_title":
        rect.y1 = min(rect.y1, rect.y0 + item.source.font_size * 1.08)
    return [rect]


def _large_artwork_rects(page: fitz.Page) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if not rect:
            continue
        rect = fitz.Rect(rect)
        if rect.width < 35 or rect.height < 45:
            continue
        aspect = rect.width / max(rect.height, 1)
        if 0.25 <= aspect <= 2.5:
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


def _diagram_below(page: fitz.Page, item: TranslatedLine) -> fitz.Rect | None:
    artwork = _nearest_artwork_rect(page, item)
    if artwork is None:
        return None
    label = fitz.Rect(*item.source.bbox)
    label_center_x = (label.x0 + label.x1) / 2
    horizontally_related = artwork.x0 <= label_center_x <= artwork.x1
    below = label.y0 >= artwork.y1 - 8
    if below and horizontally_related:
        return artwork
    return None


def _figure_label_slot(page: fitz.Page, item: TranslatedLine) -> tuple[float, float] | None:
    if item.source.role != "figure_label":
        return None
    label = fitz.Rect(*item.source.bbox)
    center_x = (label.x0 + label.x1) / 2
    center_y = (label.y0 + label.y1) / 2
    left_lines: list[float] = []
    right_lines: list[float] = []
    for drawing in page.get_drawings():
        for raw_item in drawing.get("items", []):
            if not raw_item or raw_item[0] != "l" or len(raw_item) < 3:
                continue
            start, end = raw_item[1], raw_item[2]
            if abs(start.x - end.x) > 1:
                continue
            y0, y1 = sorted((start.y, end.y))
            if y1 - y0 < 20:
                continue
            if not (y0 - 4 <= center_y <= y1 + 4):
                continue
            x = float(start.x)
            if center_x - 90 <= x < center_x:
                left_lines.append(x)
            elif center_x < x <= center_x + 90:
                right_lines.append(x)
    if not left_lines or not right_lines:
        return None
    left = max(left_lines)
    right = min(right_lines)
    if right - left < 20:
        return None
    # Figure cells in the source often fit English tightly between vertical
    # rules.  A large artificial padding forces Japanese peer labels to wrap,
    # which then pushes the following row onto the cell separator.
    padding = 0.35
    return left + padding, right - padding


def _max_width(page: fitz.Page, item: TranslatedLine, font: fitz.Font) -> float:
    src = item.source
    x0, _, x1, _ = src.bbox
    safe_left, safe_right = _content_safe_bounds(page)
    safe_width = max(4, safe_right - safe_left)
    start_x = min(max(x0, safe_left), safe_right - 4)
    available = max(4, safe_right - start_x)
    original = max(4, min(x1 - x0, available))
    desired = max(
        [font.text_length(line, fontsize=item.output_font_size) for line in item.translated_text.splitlines() if line]
        or [0]
    ) + 2
    diagram_side = _diagram_side(page, item)
    if diagram_side is not None:
        artwork, side = diagram_side
        safe_gap = max(14, item.output_font_size * 1.15)
        if side == "left":
            slot = max(4, artwork.x0 - safe_gap - safe_left)
        else:
            slot = max(4, safe_right - (artwork.x1 + safe_gap))
        return min(desired, slot) if desired > 0 else slot
    below_artwork = _diagram_below(page, item)
    if below_artwork is not None:
        slot = min(safe_width, max(desired, below_artwork.width * 1.35))
        return max(4, slot)
    if src.role in {"title", "section_title", "subsection_title", "emphasis"}:
        if src.role == "emphasis" and original > safe_width * 0.6:
            return max(4, min(original, safe_right - start_x - PAGE_FALLBACK_MARGIN))
        return max(4, min(max(original, available), available))
    if src.role == "figure_label":
        slot = _figure_label_slot(page, item)
        if slot is not None:
            return max(4, slot[1] - slot[0])
        return max(4, min(max(original, desired), available, original * 1.5))
    if desired <= available:
        return max(original, desired)
    if src.role == "body" and original >= 90:
        return max(original, min(available, original * 1.8))
    return original


def _line_widths(wrapped: list[str], font: fitz.Font, font_size: float) -> list[float]:
    return [font.text_length(line, fontsize=font_size) for line in wrapped]


def _line_step(font_size: float) -> float:
    return font_size * 1.2


def _estimated_text_rect(x: float, baseline: float, width: float, font_size: float) -> fitz.Rect:
    return fitz.Rect(x, baseline - font_size, x + width, baseline + font_size * 0.24)


def _horizontal_overlap_ratio(left: fitz.Rect, right: fitz.Rect) -> float:
    overlap = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    denominator = max(1.0, min(left.width, right.width))
    return overlap / denominator


def _avoid_generated_overlap(
    x: float,
    width: float,
    baseline: float,
    font_size: float,
    placed_rows: list[fitz.Rect],
) -> float:
    adjusted = baseline
    padding = max(1.0, font_size * 0.12)
    for previous in placed_rows:
        candidate = _estimated_text_rect(x, adjusted, width, font_size)
        if _horizontal_overlap_ratio(candidate, previous) < 0.18:
            continue
        intersection = candidate & previous
        if intersection.is_empty:
            continue
        adjusted += previous.y1 - candidate.y0 + padding
    return adjusted


def _label_start_x(
    page: fitz.Page,
    item: TranslatedLine,
    wrapped: list[str],
    font: fitz.Font,
) -> float:
    label = fitz.Rect(*item.source.bbox)
    source_x = item.source.origin[0] if item.source.origin else label.x0
    safe_left, safe_right = _content_safe_bounds(page)
    diagram_side = _diagram_side(page, item)
    if diagram_side is None:
        below_artwork = _diagram_below(page, item)
        if below_artwork is None:
            label_width = max(_line_widths(wrapped, font, item.output_font_size) or [label.width])
            if item.source.role == "figure_label":
                slot = _figure_label_slot(page, item)
                if slot is not None:
                    return _clamp_to_safe_x(page, (slot[0] + slot[1]) / 2 - label_width / 2, label_width)
                source_center = (label.x0 + label.x1) / 2
                return _clamp_to_safe_x(page, source_center - label_width / 2, label_width)
            return _clamp_to_safe_x(page, source_x, label_width)
        label_width = max(_line_widths(wrapped, font, item.output_font_size) or [label.width])
        artwork_center = (below_artwork.x0 + below_artwork.x1) / 2
        return _clamp_to_safe_x(page, artwork_center - label_width / 2, label_width)
    artwork, side = diagram_side
    label_width = max(_line_widths(wrapped, font, item.output_font_size) or [label.width])
    safe_gap = max(14, item.output_font_size * 1.15)
    if side == "left":
        return max(safe_left, artwork.x0 - safe_gap - label_width)
    target = artwork.x1 + safe_gap
    return min(max(target, source_x, safe_left), max(safe_left, safe_right - label_width))


def _baseline(item: TranslatedLine) -> float:
    src = item.source
    if src.origin:
        return src.origin[1]
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
    placed_rows: list[fitz.Rect],
) -> bool:
    if len(icon_streams) < 2:
        return False
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
    x = _clamp_to_safe_x(page, x0, total)
    baseline = _avoid_generated_overlap(x, total, _baseline(item), size, placed_rows)
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
    placed_rows.append(_estimated_text_rect(x, baseline, total, size))
    return True


def _draw_template_line(
    page: fitz.Page,
    x: float,
    baseline: float,
    template: str,
    font: fitz.Font,
    font_name: str,
    font_size: float,
    icon_streams: list[tuple[fitz.Rect, bytes]],
) -> int:
    parts = template.split("□")
    cursor = x
    used_icons = 0
    gap = 1.2
    for index, part in enumerate(parts):
        if part:
            _insert_text(page, fitz.Point(cursor, baseline), part, font_name, font_size)
            cursor += font.text_length(part, fontsize=font_size)
        if index < len(parts) - 1:
            rect, stream = icon_streams[used_icons]
            icon_width = max(2.0, rect.width)
            icon_height = max(2.0, rect.height)
            icon_top = baseline - icon_height * 0.82
            page.insert_image(
                fitz.Rect(cursor + gap, icon_top, cursor + gap + icon_width, icon_top + icon_height),
                stream=stream,
                overlay=True,
            )
            cursor += icon_width + gap * 2
            used_icons += 1
    return used_icons


def _template_line_width(
    template: str,
    font: fitz.Font,
    font_size: float,
    icon_rects: list[fitz.Rect],
) -> float:
    parts = template.split("□")
    text_width = sum(font.text_length(part, fontsize=font_size) for part in parts)
    icon_width = sum(icon_rects[index].width for index in range(min(len(icon_rects), len(parts) - 1)))
    gap_width = max(0, len(parts) - 1) * 2.4
    return text_width + icon_width + gap_width


def _write_source_icon_template_line(
    page: fitz.Page,
    item: TranslatedLine,
    font: fitz.Font,
    font_name: str,
    icon_streams: list[tuple[fitz.Rect, bytes]],
    placed_rows: list[fitz.Rect],
) -> bool:
    needed = _placeholder_count(item.translated_text)
    if needed == 0:
        return False
    if len(icon_streams) < needed:
        return False

    lines = [line for line in item.translated_text.splitlines() if line.strip()]
    baseline = _baseline(item)
    size = item.output_font_size
    line_step = _line_step(size)
    icon_index = 0
    rendered: list[str] = []
    base_adjustment = 0.0
    for offset, template in enumerate(lines):
        count = _placeholder_count(template)
        current_icons = icon_streams[icon_index : icon_index + count]
        width = _template_line_width(template, font, size, [rect for rect, _ in current_icons])
        x = _clamp_to_safe_x(page, item.source.bbox[0], width)
        desired_baseline = baseline + base_adjustment + offset * line_step
        row_baseline = _avoid_generated_overlap(x, width, desired_baseline, size, placed_rows)
        if offset == 0:
            base_adjustment = row_baseline - baseline
        used = _draw_template_line(
            page,
            x,
            row_baseline,
            template,
            font,
            font_name,
            size,
            current_icons,
        )
        icon_index += used
        rendered.append(template.replace("□", "source-icon"))
        if template:
            placed_rows.append(_estimated_text_rect(x, row_baseline, width, size))
    item.wrapped_lines = rendered
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
            if _is_quote_gap_line(src.text) or _is_source_icon_template_line(item):
                streams: list[tuple[fitz.Rect, bytes]] = []
                needed = max(2 if _is_quote_gap_line(src.text) else 0, _placeholder_count(item.translated_text))
                for rect in _icon_gap_rects(page, src.bbox, needed=needed, source_text=src.text, font_size=src.font_size):
                    pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=fitz.Rect(rect), alpha=False)
                    streams.append((fitz.Rect(rect), pix.tobytes("png")))
                quote_icon_streams[id(item)] = streams
            for rect in _redaction_rects(page, item):
                if rect.width > 0 and rect.height > 0:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        page.insert_font(fontname=font_name, fontfile=str(font_path))

        placed_rows: list[fitz.Rect] = []
        for item in items:
            src = item.source
            if not src.localizable:
                continue
            if _is_source_icon_template_line(item):
                if not _write_source_icon_template_line(page, item, font, font_name, quote_icon_streams.get(id(item), []), placed_rows):
                    raise RuntimeError(
                        f"Protected source icons could not be located for source-icon template line on page {src.page_index + 1}."
                    )
                continue
            if _is_quote_gap_line(src.text):
                if not _write_quote_gap_line(page, item, font, font_name, quote_icon_streams.get(id(item), []), placed_rows):
                    raise RuntimeError(
                        f"Protected source icons could not be located for quote-gap line on page {src.page_index + 1}."
                    )
                continue
            layout_text = _layout_text(item)
            max_width = _max_width(page, item, font)
            wrapped = _wrap_text(layout_text, font, item.output_font_size, max_width)
            item.wrapped_lines = wrapped
            line_step = _line_step(item.output_font_size)
            baseline = _baseline(item)
            x = _label_start_x(page, item, wrapped, font)
            for offset, text in enumerate(wrapped):
                text_width = font.text_length(text, fontsize=item.output_font_size)
                row_baseline = _avoid_generated_overlap(
                    x,
                    text_width,
                    baseline + offset * line_step,
                    item.output_font_size,
                    placed_rows,
                )
                _insert_text(
                    page,
                    fitz.Point(x, row_baseline),
                    text,
                    font_name,
                    item.output_font_size,
                )
                if text:
                    placed_rows.append(_estimated_text_rect(x, row_baseline, text_width, item.output_font_size))

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_pdf, garbage=4, deflate=True)
    doc.close()
    return translated_lines
