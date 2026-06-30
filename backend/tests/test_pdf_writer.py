from pathlib import Path

import fitz
import pytest

from app.models import TextLine, TranslatedLine
from app.services.pdf_writer import (
    _baseline,
    _content_safe_bounds,
    _label_start_x,
    _layout_text,
    _max_width,
    _redaction_rects,
    _wrap_text,
    write_editable_pdf,
)


def _make_source_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=240, height=120)
    page.insert_text(fitz.Point(24, 48), "Remote Control", fontsize=14)
    doc.save(path)
    doc.close()


def _make_quote_gap_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=260, height=120)
    page.insert_text(fitz.Point(24, 60), 'Press "    " or "    "', fontsize=14)
    page.draw_circle(fitz.Point(83, 56), 5, color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_circle(fitz.Point(133, 56), 5, color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(path)
    doc.close()


def test_write_editable_pdf_embeds_japanese_font(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    output = tmp_path / "translated.pdf"
    _make_source_pdf(source)
    line = TextLine(
        page_index=0,
        line_index=0,
        text="Remote Control",
        bbox=(24, 32, 180, 54),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )

    write_editable_pdf(
        source,
        output,
        [TranslatedLine(source=line, translated_text="リモコン", output_font_size=14)],
        font_path,
    )

    doc = fitz.open(output)
    try:
        text = doc[0].get_text()
        raw = doc[0].get_text("dict")
    finally:
        doc.close()

    fonts = [
        span.get("font")
        for block in raw.get("blocks", [])
        if block.get("type") == 0
        for line_data in block.get("lines", [])
        for span in line_data.get("spans", [])
    ]
    assert "リモコン" in text
    assert "··" not in text
    assert any("NotoSansCJKjp-Regular" in str(font) for font in fonts)


def test_write_editable_pdf_rejects_cff_otf_font(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "SourceHanSansJP-Regular.otf"
    if not font_path.exists():
        pytest.skip("CFF/OpenType test font is not available.")

    source = tmp_path / "source.pdf"
    output = tmp_path / "translated.pdf"
    _make_source_pdf(source)
    line = TextLine(
        page_index=0,
        line_index=0,
        text="Remote Control",
        bbox=(24, 32, 180, 54),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )

    with pytest.raises(RuntimeError, match="TrueType"):
        write_editable_pdf(
            source,
            output,
            [TranslatedLine(source=line, translated_text="リモコン", output_font_size=14)],
            font_path,
        )


def test_baseline_prefers_source_origin() -> None:
    line = TextLine(
        page_index=0,
        line_index=0,
        text="Features",
        bbox=(50, 82, 150, 116),
        origin=(50, 108.7),
        font_name="Helvetica",
        font_size=24,
        role="section_title",
    )

    assert _baseline(TranslatedLine(source=line, translated_text="特徴", output_font_size=24)) == 108.7


def test_write_editable_pdf_keeps_source_icons_for_quote_gap(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    output = tmp_path / "translated.pdf"
    _make_quote_gap_pdf(source)
    line = TextLine(
        page_index=0,
        line_index=0,
        text='Press "    " or "    "',
        bbox=(24, 42, 160, 66),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )

    write_editable_pdf(
        source,
        output,
        [TranslatedLine(source=line, translated_text="「□」または「□」を押す", output_font_size=14)],
        font_path,
    )

    doc = fitz.open(output)
    try:
        text = doc[0].get_text()
        images = doc[0].get_images(full=True)
    finally:
        doc.close()

    assert "または" in text
    assert "Press" not in text
    assert len(images) >= 2


def test_write_editable_pdf_uses_source_icons_for_template_placeholders(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    output = tmp_path / "translated.pdf"
    _make_quote_gap_pdf(source)
    line = TextLine(
        page_index=0,
        line_index=0,
        text='Press "    " or "    ", check channel.',
        bbox=(24, 42, 170, 66),
        origin=(24, 60),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )

    write_editable_pdf(
        source,
        output,
        [
            TranslatedLine(
                source=line,
                translated_text="「□」または「□」を押す\nチャンネル確認",
                output_font_size=14,
            )
        ],
        font_path,
    )

    doc = fitz.open(output)
    try:
        text = doc[0].get_text()
        images = doc[0].get_images(full=True)
    finally:
        doc.close()

    assert "□" not in text
    assert "チャンネル確認" in text
    assert len(images) >= 2


def test_wrap_text_respects_explicit_natural_line_breaks() -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    font = fitz.Font(fontfile=str(font_path))
    text = "1～9チャンネル：\n1チャンネルに1台の\nシェードを登録できます。"

    assert _wrap_text(text, font, 14, 196) == [
        "1～9チャンネル：",
        "1チャンネルに1台の",
        "シェードを登録できます。",
    ]


def test_wrap_text_keeps_short_labels_on_one_line() -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    font = fitz.Font(fontfile=str(font_path))

    assert _wrap_text("キーP1を設定", font, 14, 90) == ["キーP1を設定"]
    assert _wrap_text("チルトベーン", font, 14, 90) == ["チルトベーン"]


def test_diagram_labels_align_away_from_artwork_lines(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420, height=260)
    page.draw_circle(fitz.Point(220, 130), 55, color=(0, 0, 0))
    doc.save(source)
    doc.close()

    doc = fitz.open(source)
    page = doc[0]
    font = fitz.Font(fontfile=str(font_path))
    left = TextLine(
        page_index=0,
        line_index=0,
        text="Knob: Adjust the opening percentage",
        bbox=(48, 118, 164, 138),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )
    right = TextLine(
        page_index=0,
        line_index=1,
        text="1-9 Channel: One channel corresponds to one blind.",
        bbox=(260, 118, 392, 138),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )
    try:
        left_item = TranslatedLine(source=left, translated_text="つまみ：開き具合を調整", output_font_size=14)
        right_item = TranslatedLine(source=right, translated_text="1～9チャンネル：", output_font_size=14)

        left_wrapped = _wrap_text(left_item.translated_text, font, 14, _max_width(page, left_item, font))
        right_wrapped = _wrap_text(right_item.translated_text, font, 14, _max_width(page, right_item, font))
        left_x = _label_start_x(page, left_item, left_wrapped, font)
        right_x = _label_start_x(page, right_item, right_wrapped, font)
    finally:
        doc.close()

    assert left_x < left.bbox[0]
    assert all(left_x + font.text_length(line, fontsize=14) <= 220 - 55 - 14 for line in left_wrapped)
    assert right_x >= 220 + 55 + 14


def test_section_title_redaction_does_not_cover_underline() -> None:
    line = TextLine(
        page_index=0,
        line_index=0,
        text="Features",
        bbox=(50, 82, 150, 116),
        font_name="Helvetica",
        font_size=24,
        role="section_title",
    )
    item = TranslatedLine(source=line, translated_text="特徴", output_font_size=24)

    rects = _redaction_rects(None, item)  # type: ignore[arg-type]

    assert rects[0].y1 <= 108


def test_below_artwork_labels_are_centered(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420, height=260)
    page.draw_rect(fitz.Rect(190, 70, 270, 180), color=(0, 0, 0))
    doc.save(source)
    doc.close()

    doc = fitz.open(source)
    page = doc[0]
    font = fitz.Font(fontfile=str(font_path))
    line = TextLine(
        page_index=0,
        line_index=0,
        text="Tilt vanes",
        bbox=(206, 186, 254, 206),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )
    try:
        item = TranslatedLine(source=line, translated_text="チルトベーン", output_font_size=14)
        wrapped = _wrap_text(item.translated_text, font, 14, _max_width(page, item, font))
        x = _label_start_x(page, item, wrapped, font)
    finally:
        doc.close()

    width = font.text_length(item.translated_text, fontsize=14)
    assert abs((x + width / 2) - 230) <= 1


def test_lower_right_diagram_label_stays_right_aligned(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420, height=260)
    page.draw_circle(fitz.Point(220, 130), 55, color=(0, 0, 0))
    doc.save(source)
    doc.close()

    doc = fitz.open(source)
    page = doc[0]
    font = fitz.Font(fontfile=str(font_path))
    line = TextLine(
        page_index=0,
        line_index=0,
        text="1-9 Channel: One channel corresponds to one blind.",
        bbox=(286, 178, 400, 198),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )
    try:
        item = TranslatedLine(source=line, translated_text="1～9チャンネル：", output_font_size=14)
        wrapped = _wrap_text(item.translated_text, font, 14, _max_width(page, item, font))
        x = _label_start_x(page, item, wrapped, font)
    finally:
        doc.close()

    assert x >= 220 + 55 + 14


def test_right_side_diagram_label_keeps_source_gap_from_artwork(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=520, height=260)
    page.draw_circle(fitz.Point(220, 130), 55, color=(0, 0, 0))
    doc.save(source)
    doc.close()

    doc = fitz.open(source)
    page = doc[0]
    font = fitz.Font(fontfile=str(font_path))
    line = TextLine(
        page_index=0,
        line_index=0,
        text="Slight Close",
        bbox=(330, 118, 410, 138),
        origin=(330, 133),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )
    try:
        item = TranslatedLine(source=line, translated_text="微閉", output_font_size=14)
        wrapped = _wrap_text(item.translated_text, font, 14, _max_width(page, item, font))
        x = _label_start_x(page, item, wrapped, font)
    finally:
        doc.close()

    assert x == 330


def test_layout_text_removes_model_or_fixed_hard_breaks_for_normal_text() -> None:
    line = TextLine(
        page_index=0,
        line_index=0,
        text="Congratulations! Remove the sleeping blocker.",
        bbox=(84.4, 509.1, 558.8, 561.1),
        font_name="Helvetica",
        font_size=14,
        role="emphasis",
    )
    item = TranslatedLine(source=line, translated_text="おめでとうございます！\nスリープブロッカーを外します。", output_font_size=14)

    assert _layout_text(item) == "おめでとうございます！ スリープブロッカーを外します。"


def test_wide_emphasis_paragraph_keeps_right_safety_margin(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    doc.save(source)
    doc.close()

    doc = fitz.open(source)
    page = doc[0]
    font = fitz.Font(fontfile=str(font_path))
    line = TextLine(
        page_index=0,
        line_index=0,
        text="Congratulations! Remove the sleeping blocker, chooes the channel number refer to page 9-17.",
        bbox=(84.4, 509.1, 558.8, 561.1),
        origin=(84.4, 524.6),
        font_name="Helvetica",
        font_size=14,
        role="emphasis",
    )
    try:
        item = TranslatedLine(
            source=line,
            translated_text="おめでとうございます！スリープブロッカーを取り外し、チャンネル番号を選択してください。",
            output_font_size=14,
        )
        max_width = _max_width(page, item, font)
    finally:
        doc.close()

    assert max_width <= 595 - 84.4 - 72


def test_content_safe_bounds_uses_source_title_rule(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_line(fitz.Point(52, 116), fitz.Point(533, 116), color=(0, 0, 0), width=1)
    page.draw_line(fitz.Point(20, 760), fitz.Point(592, 760), color=(0, 0, 0), width=1)
    doc.save(source)
    doc.close()

    doc = fitz.open(source)
    try:
        assert _content_safe_bounds(doc[0]) == (52.0, 533.0)
    finally:
        doc.close()


def test_body_text_width_stays_inside_source_content_frame(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_line(fitz.Point(52, 116), fitz.Point(533, 116), color=(0, 0, 0), width=1)
    doc.save(source)
    doc.close()

    doc = fitz.open(source)
    page = doc[0]
    font = fitz.Font(fontfile=str(font_path))
    line = TextLine(
        page_index=0,
        line_index=0,
        text="1-9 Channel: One channel corresponds to one blind.",
        bbox=(390, 140, 570, 160),
        origin=(390, 155),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )
    try:
        item = TranslatedLine(
            source=line,
            translated_text="1～9チャンネル：1チャンネルに1台のシェードを登録できます。",
            output_font_size=14,
        )
        max_width = _max_width(page, item, font)
        wrapped = _wrap_text(item.translated_text, font, 14, max_width)
        x = _label_start_x(page, item, wrapped, font)
        widths = [font.text_length(row, fontsize=14) for row in wrapped]
    finally:
        doc.close()

    assert max_width <= 533 - 390
    assert x >= 52
    assert all(x + width <= 533 for width in widths)


def test_write_editable_pdf_spaces_adjacent_generated_rows(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    output = tmp_path / "translated.pdf"
    doc = fitz.open()
    page = doc.new_page(width=260, height=160)
    page.insert_text(fitz.Point(24, 48), "First line", fontsize=14)
    page.insert_text(fitz.Point(24, 62), "Second line", fontsize=14)
    doc.save(source)
    doc.close()

    lines = [
        TranslatedLine(
            source=TextLine(
                page_index=0,
                line_index=0,
                text="First line",
                bbox=(24, 32, 160, 54),
                origin=(24, 48),
                font_name="Helvetica",
                font_size=14,
                role="body",
            ),
            translated_text="一行目のテキスト",
            output_font_size=14,
        ),
        TranslatedLine(
            source=TextLine(
                page_index=0,
                line_index=1,
                text="Second line",
                bbox=(24, 46, 160, 68),
                origin=(24, 62),
                font_name="Helvetica",
                font_size=14,
                role="body",
            ),
            translated_text="二行目のテキスト",
            output_font_size=14,
        ),
    ]

    write_editable_pdf(source, output, lines, font_path)

    doc = fitz.open(output)
    try:
        spans = [
            span
            for block in doc[0].get_text("dict").get("blocks", [])
            if block.get("type") == 0
            for line_data in block.get("lines", [])
            for span in line_data.get("spans", [])
            if "NotoSansCJKjp" in str(span.get("font", ""))
        ]
    finally:
        doc.close()

    rects = [fitz.Rect(span["bbox"]) for span in spans if span.get("text", "").strip()]
    assert len(rects) == 2
    assert (rects[0] & rects[1]).is_empty


def test_right_diagram_label_clamps_to_source_content_frame(tmp_path) -> None:
    font_path = Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"
    if not font_path.exists():
        pytest.skip("Japanese test font is not available.")

    source = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_line(fitz.Point(52, 116), fitz.Point(533, 116), color=(0, 0, 0), width=1)
    page.draw_circle(fitz.Point(360, 250), 55, color=(0, 0, 0))
    doc.save(source)
    doc.close()

    doc = fitz.open(source)
    page = doc[0]
    font = fitz.Font(fontfile=str(font_path))
    line = TextLine(
        page_index=0,
        line_index=0,
        text="Slight Close",
        bbox=(470, 238, 592, 258),
        origin=(470, 253),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )
    try:
        item = TranslatedLine(source=line, translated_text="微閉", output_font_size=14)
        wrapped = _wrap_text(item.translated_text, font, 14, _max_width(page, item, font))
        x = _label_start_x(page, item, wrapped, font)
        width = font.text_length(wrapped[0], fontsize=14)
    finally:
        doc.close()

    assert x + width <= 533
