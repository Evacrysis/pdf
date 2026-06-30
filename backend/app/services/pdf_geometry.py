from __future__ import annotations

import re
from collections import Counter

import fitz

from app.models import TextLine


PROTECTED_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:CH\+|CH-|P[12]|OK|A\d+|\d+s|\d+x|GC|EC)(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9.])\d{2}(?![A-Za-z0-9.])",
    re.IGNORECASE,
)

PROTECTED_SHORT_CODE_RE = re.compile(r"(?:[A-Za-z]{1,3}|[A-Za-z]\s*[xX]\s*\d+|[xX]\s*\d+|[A-Za-z]\s*[0-9]+)")


def _line_text(line: dict) -> str:
    return "".join(span.get("text", "") for span in line.get("spans", [])).strip()


def _dominant_span(line: dict) -> dict:
    spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
    if not spans:
        return {"font": "", "size": 0}
    return max(spans, key=lambda span: len(span.get("text", "")))


def _line_origin(line: dict, dominant: dict) -> tuple[float, float] | None:
    spans = [span for span in line.get("spans", []) if span.get("text", "").strip() and span.get("origin")]
    if not spans:
        return None
    x = min(float(span["origin"][0]) for span in spans)
    dominant_origin = dominant.get("origin")
    if dominant_origin:
        y = float(dominant_origin[1])
    else:
        y = float(spans[0]["origin"][1])
    return (x, y)


def _is_localizable(text: str) -> bool:
    if not text:
        return False
    stripped = " ".join(text.strip().split())
    if re.fullmatch(r"[\W\d_]+", text):
        return False
    if re.fullmatch(r"(?:Lithium Cell|CR\d{4}|3V)", stripped, re.IGNORECASE):
        return False
    if re.fullmatch(r"(?:[124]x|CH\+|CH-|P[12]|OK|A\d+|\d{2}|\d+s|\d+x|GC|EC|on)", stripped, re.IGNORECASE):
        return False
    if PROTECTED_SHORT_CODE_RE.fullmatch(stripped):
        return False
    return bool(re.search(r"[A-Za-z]", text))


def _classify_roles(lines: list[TextLine]) -> None:
    sizes = [line.font_size for line in lines if line.localizable and line.font_size > 0]
    if not sizes:
        return
    rounded_sizes = [round(size, 1) for size in sizes]
    body_size = Counter(rounded_sizes).most_common(1)[0][0]
    for line in lines:
        if line.font_size >= body_size + 18:
            line.role = "title"
        elif line.font_size >= body_size + 8:
            line.role = "section_title"
        elif line.font_size >= body_size + 4:
            line.role = "subsection_title"
        elif line.font_size >= body_size + 1.5:
            line.role = "emphasis"
        elif line.font_size <= body_size - 2:
            line.role = "figure_label"
        else:
            line.role = "body"


def extract_text_lines(pdf_path: str) -> list[TextLine]:
    doc = fitz.open(pdf_path)
    result: list[TextLine] = []
    for page_index, page in enumerate(doc):
        raw = page.get_text("dict")
        page_lines: list[TextLine] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for raw_line in block.get("lines", []):
                text = _line_text(raw_line)
                if not text:
                    continue
                span = _dominant_span(raw_line)
                bbox = tuple(float(v) for v in raw_line.get("bbox", (0, 0, 0, 0)))
                origin = _line_origin(raw_line, span)
                tokens = [token for token in PROTECTED_TOKEN_RE.findall(text) if token.strip()]
                page_lines.append(
                    TextLine(
                        page_index=page_index,
                        line_index=len(page_lines),
                        text=text,
                        bbox=bbox,
                        origin=origin,
                        font_name=str(span.get("font", "")),
                        font_size=float(span.get("size", 0)),
                        protected_tokens=tokens,
                        localizable=_is_localizable(text),
                    )
                )
        _classify_roles(page_lines)
        result.extend(page_lines)
    doc.close()
    return result
