from pathlib import Path
import os

import fitz
import pytest

from app.services.pdf_preview import render_page_png


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=120)
    page.insert_text(fitz.Point(24, 48), "Preview source")
    doc.save(path)
    doc.close()


def test_render_page_png_creates_preview(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "preview" / "page-1.png"
    _make_pdf(source)

    rendered = render_page_png(source, 0, output)

    assert rendered == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_render_page_png_refreshes_stale_preview(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "preview" / "page-1.png"
    _make_pdf(source)
    output.parent.mkdir(parents=True)
    output.write_bytes(b"stale")
    os.utime(output, (source.stat().st_mtime - 10, source.stat().st_mtime - 10))

    render_page_png(source, 0, output)

    assert output.read_bytes() != b"stale"


def test_render_page_png_rejects_out_of_range_page(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    _make_pdf(source)

    with pytest.raises(IndexError):
        render_page_png(source, 1, tmp_path / "page-2.png")
