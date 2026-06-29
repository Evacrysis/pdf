from typing import Optional

from app.models import TextLine, TranslatedLine, TranslationOptions
from app.services.rules import RuleEngine


def line(text: str, translated: str, size: float = 12, output_size: Optional[float] = None) -> TranslatedLine:
    src = TextLine(
        page_index=0,
        line_index=0,
        text=text,
        bbox=(0, 0, 100, 20),
        font_name="Helvetica",
        font_size=size,
        role="body",
        protected_tokens=[],
        localizable=True,
    )
    return TranslatedLine(source=src, translated_text=translated, output_font_size=output_size or size)


def test_rejects_text_scaling() -> None:
    results = RuleEngine().validate([line("Press Open", "開を押します。", 12, 10)])
    assert any(result.code == "text_scaling_forbidden" for result in results)


def test_rejects_english_residue() -> None:
    results = RuleEngine().validate([line("Press Open", "Press Open")])
    assert any(result.code == "english_residue" for result in results)


def test_rejects_missing_protected_token() -> None:
    item = line('Press "OK"', "押します。")
    item.source.protected_tokens = ['"OK"']
    results = RuleEngine().validate([item])
    assert any(result.code == "protected_token_missing" for result in results)


def test_api_key_is_not_serialized() -> None:
    options = TranslationOptions(api_key="secret-value")
    dumped = options.model_dump()
    assert "api_key" not in dumped
