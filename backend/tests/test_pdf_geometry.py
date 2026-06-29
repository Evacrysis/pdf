from app.models import TextLine
from app.services.pdf_geometry import PROTECTED_TOKEN_RE, _classify_roles, _is_localizable


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
