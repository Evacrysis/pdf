from pathlib import Path

import fitz
import pytest

from app.models import TextLine, TranslatedLine
from app.services.pdf_writer import write_editable_pdf


def _make_source_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=240, height=120)
    page.insert_text(fitz.Point(24, 48), "Remote Control", fontsize=14)
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
