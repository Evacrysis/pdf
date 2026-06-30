from app.models import TextLine
from pathlib import Path

import fitz

from app.services.pdf_geometry import PROTECTED_TOKEN_RE, _classify_roles, _is_localizable, _line_origin, extract_text_lines


def test_protected_tokens_do_not_match_inside_words() -> None:
    text = "Remote Control Favorite Position operation Press"

    assert PROTECTED_TOKEN_RE.findall(text) == []


def test_protected_tokens_match_standalone_button_tokens() -> None:
    text = 'Set key P1, press P2, CH+, CH-, OK, A1, 01, GC, EC, on, 2x.'

    assert PROTECTED_TOKEN_RE.findall(text) == [
        "P1",
        "P2",
        "CH+",
        "CH-",
        "OK",
        "A1",
        "01",
        "GC",
        "EC",
        "on",
        "2x",
    ]


def _line(size: float) -> TextLine:
    return TextLine(
        page_index=0,
        line_index=0,
        text="Text",
        bbox=(0, 0, 100, 20),
        font_name="Helvetica",
        font_size=size,
        localizable=True,
    )


def test_title_roles_are_split_by_font_level() -> None:
    lines = [_line(14), _line(20), _line(24), _line(36)]

    _classify_roles(lines)

    assert [line.role for line in lines] == ["body", "subsection_title", "section_title", "title"]


def test_battery_artwork_text_is_not_localizable() -> None:
    assert not _is_localizable("Lithium Cell")
    assert not _is_localizable("CR2450")
    assert not _is_localizable("3V")


def test_short_bold_codes_are_not_localizable() -> None:
    assert not _is_localizable("S")
    assert not _is_localizable("S x2")
    assert not _is_localizable("A1")
    assert _is_localizable("Low battery:")
    assert _is_localizable("Back")


def test_extract_text_lines_preserves_span_origin(tmp_path: Path) -> None:
    source = tmp_path / "origin.pdf"
    doc = fitz.open()
    page = doc.new_page(width=220, height=120)
    page.insert_text(fitz.Point(24, 64), "Remote Control", fontsize=14)
    doc.save(source)
    doc.close()

    lines = extract_text_lines(str(source))

    assert lines[0].origin == (24.0, 64.0)


def test_line_origin_uses_leftmost_span_x_and_dominant_baseline() -> None:
    raw_line = {
        "spans": [
            {"text": "（下部ロッドに取り付けて）", "origin": (267.4, 540.6)},
            {"text": "Congratulations", "origin": (84.4, 540.6)},
        ]
    }
    dominant = raw_line["spans"][0]

    assert _line_origin(raw_line, dominant) == (84.4, 540.6)
