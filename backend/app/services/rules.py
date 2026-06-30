from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import fitz

from app.models import GateResult, GateSeverity, TranslatedLine
from app.services.line_processing import FIXED_TRANSLATIONS, QUOTE_GAP_RE


ASCII_WORD_RE = re.compile(r"[A-Za-z]{3,}")


class RuleEngine:
    def validate(self, lines: list[TranslatedLine]) -> list[GateResult]:
        results: list[GateResult] = []
        results.extend(self._no_missing_translation(lines))
        results.extend(self._no_text_scaling(lines))
        results.extend(self._same_role_font_consistency(lines))
        results.extend(self._protected_tokens_preserved(lines))
        results.extend(self._no_english_residue(lines))
        results.extend(self._fixed_translations_applied(lines))
        results.extend(self._no_empty_protected_icon_brackets(lines))
        return results

    def validate_output_pdf(self, source_pdf: Path, output_pdf: Path) -> list[GateResult]:
        failures: list[GateResult] = []
        source_doc = fitz.open(source_pdf)
        output_doc = fitz.open(output_pdf)
        try:
            for page_index in range(min(source_doc.page_count, output_doc.page_count)):
                generated = _generated_text_spans(output_doc[page_index])
                failures.extend(_text_line_overlap_failures(page_index, generated))
                protected_lines = _source_drawing_lines(source_doc[page_index])
                for span in generated:
                    span_rect = fitz.Rect(span["bbox"]) + (0.4, 0.4, 0.4, 0.4)
                    for line_rect in protected_lines:
                        intersection = span_rect & line_rect
                        if not intersection.is_empty and intersection.get_area() > 1.5:
                            failures.append(
                                GateResult(
                                    code="translated_text_overlaps_source_line",
                                    severity=GateSeverity.hard_fail,
                                    passed=False,
                                    page_index=page_index,
                                    message="Generated translated text overlaps a protected source line or border.",
                                    details={
                                        "text": span["text"],
                                        "text_bbox": list(span["bbox"]),
                                        "line_bbox": [line_rect.x0, line_rect.y0, line_rect.x1, line_rect.y1],
                                    },
                                )
                            )
                            break
        finally:
            source_doc.close()
            output_doc.close()
        return failures

    def _no_missing_translation(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        for item in lines:
            src = item.source
            if src.localizable and not item.translated_text.strip():
                failures.append(
                    GateResult(
                        code="missing_translation",
                        severity=GateSeverity.hard_fail,
                        passed=False,
                        page_index=src.page_index,
                        line_index=src.line_index,
                        message="Localizable source line has empty translation.",
                    )
                )
        return failures

    def _fixed_translations_applied(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        for item in lines:
            expected = FIXED_TRANSLATIONS.get(" ".join(item.source.text.split()))
            if expected is None:
                continue
            actual = " ".join(item.translated_text.split())
            expected_flat = " ".join(expected.split())
            if actual != expected_flat:
                failures.append(
                    GateResult(
                        code="fixed_translation_mismatch",
                        severity=GateSeverity.hard_fail,
                        passed=False,
                        page_index=item.source.page_index,
                        line_index=item.source.line_index,
                        message="Known repeated source text did not use the locked translation.",
                        details={"expected": expected, "translation": item.translated_text},
                    )
                )
        return failures

    def _no_empty_protected_icon_brackets(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        for item in lines:
            source = " ".join(item.source.text.split())
            if QUOTE_GAP_RE.match(source) and re.search(r"「\s*」", item.translated_text):
                failures.append(
                    GateResult(
                        code="empty_protected_icon_bracket",
                        severity=GateSeverity.hard_fail,
                        passed=False,
                        page_index=item.source.page_index,
                        line_index=item.source.line_index,
                        message="Source quote gap contains a protected icon; final text must not be an empty Japanese bracket.",
                        details={"translation": item.translated_text},
                    )
                )
        return failures

    def _no_text_scaling(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        for item in lines:
            src = item.source
            if abs(item.output_font_size - src.font_size) > 0.01:
                failures.append(
                    GateResult(
                        code="text_scaling_forbidden",
                        severity=GateSeverity.hard_fail,
                        passed=False,
                        page_index=src.page_index,
                        line_index=src.line_index,
                        message="Output font size differs from source role size.",
                        details={"source_size": src.font_size, "output_size": item.output_font_size},
                    )
                )
        return failures

    def _same_role_font_consistency(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        grouped: dict[tuple[int, str], list[TranslatedLine]] = defaultdict(list)
        for item in lines:
            if item.source.localizable:
                grouped[(item.source.page_index, item.source.role)].append(item)
        for (page_index, role), items in grouped.items():
            sizes = {round(item.output_font_size, 2) for item in items}
            if len(sizes) > 1 and role in {"body", "figure_label", "section_title", "title"}:
                severity = GateSeverity.warning if role == "figure_label" else GateSeverity.hard_fail
                failures.append(
                    GateResult(
                        code="same_role_font_mismatch",
                        severity=severity,
                        passed=False,
                        page_index=page_index,
                        message=f"Same role has mixed font sizes: {role}.",
                        details={"sizes": sorted(sizes), "role": role},
                    )
                )
        return failures

    def _protected_tokens_preserved(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        for item in lines:
            for token in item.source.protected_tokens:
                normalized = token.strip("\"'")
                if normalized and normalized not in item.translated_text and token not in item.translated_text:
                    failures.append(
                        GateResult(
                            code="protected_token_missing",
                            severity=GateSeverity.hard_fail,
                            passed=False,
                            page_index=item.source.page_index,
                            line_index=item.source.line_index,
                            message="Protected token is missing from translated line.",
                            details={"token": token, "translation": item.translated_text},
                        )
                    )
        return failures

    def _no_english_residue(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        allowed = {
            "Alexa",
            "Apple",
            "Google",
            "Matter",
            "Shades",
            "Shangri",
            "Yoolax",
            "Zebra",
        }
        for item in lines:
            if not item.source.localizable:
                continue
            words = set(ASCII_WORD_RE.findall(item.translated_text))
            residue = sorted(word for word in words if word not in allowed)
            if residue:
                failures.append(
                    GateResult(
                        code="english_residue",
                        severity=GateSeverity.hard_fail,
                        passed=False,
                        page_index=item.source.page_index,
                        line_index=item.source.line_index,
                        message="Translated line still contains likely untranslated English.",
                        details={"words": residue, "translation": item.translated_text},
                    )
                )
        return failures


def _generated_text_spans(page: fitz.Page) -> list[dict]:
    raw = page.get_text("dict")
    spans: list[dict] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                font = str(span.get("font", ""))
                if not text or "NotoSansCJKjp" not in font:
                    continue
                spans.append({"text": text, "bbox": tuple(float(v) for v in span["bbox"])})
    return spans


def _text_line_overlap_failures(page_index: int, spans: list[dict]) -> list[GateResult]:
    failures: list[GateResult] = []
    for left_index, left in enumerate(spans):
        left_rect = fitz.Rect(left["bbox"])
        for right in spans[left_index + 1 :]:
            right_rect = fitz.Rect(right["bbox"])
            intersection = left_rect & right_rect
            if intersection.is_empty or not _meaningful_text_overlap(left_rect, right_rect, intersection):
                continue
            failures.append(
                GateResult(
                    code="translated_text_line_overlap",
                    severity=GateSeverity.hard_fail,
                    passed=False,
                    page_index=page_index,
                    message="Generated translated text lines overlap each other; line spacing or placement is invalid.",
                    details={
                        "first": left["text"],
                        "second": right["text"],
                        "first_bbox": list(left["bbox"]),
                        "second_bbox": list(right["bbox"]),
                    },
                )
            )
    return failures


def _meaningful_text_overlap(left: fitz.Rect, right: fitz.Rect, intersection: fitz.Rect) -> bool:
    vertical_ratio = intersection.height / max(1.0, min(left.height, right.height))
    horizontal_ratio = intersection.width / max(1.0, min(left.width, right.width))
    area_ratio = intersection.get_area() / max(1.0, min(left.get_area(), right.get_area()))
    if vertical_ratio < 0.18:
        return False
    if area_ratio < 0.08 and horizontal_ratio < 0.6:
        return False
    return intersection.get_area() > 8


def _source_drawing_lines(page: fitz.Page) -> list[fitz.Rect]:
    page_rect = page.rect
    lines: list[fitz.Rect] = []
    for drawing in page.get_drawings():
        width = max(float(drawing.get("width") or 1.0), 1.0)
        for item in drawing.get("items", []):
            if not item or item[0] != "l" or len(item) < 3:
                continue
            start, end = item[1], item[2]
            if abs(start.x - end.x) <= 1 or abs(start.y - end.y) <= 1:
                length = max(abs(start.x - end.x), abs(start.y - end.y))
                if length < 16:
                    continue
                pad = max(1.0, width * 0.75)
                rect = fitz.Rect(start, end).normalize() + (-pad, -pad, pad, pad)
                clipped = rect & page_rect
                if not clipped.is_empty and (clipped.width >= 8 or clipped.height >= 8):
                    lines.append(clipped)
    return lines
