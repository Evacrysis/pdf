from pathlib import Path

import fitz
import pytest

from app.models import TextLine, TranslatedLine
from app.services.pdf_writer import _wrap_text, write_editable_pdf


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
