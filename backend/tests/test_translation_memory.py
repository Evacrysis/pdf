from app.models import TextLine, TranslationOptions
from app.services.translation_memory import TranslationMemory


def _line(text: str) -> TextLine:
    return TextLine(
        page_index=0,
        line_index=0,
        text=text,
        bbox=(0, 0, 100, 20),
        font_name="Helvetica",
        font_size=12,
        role="body",
        protected_tokens=[],
        localizable=True,
    )


def test_translation_memory_reuses_same_source_text(tmp_path) -> None:
    memory_path = tmp_path / "memory.json"
    memory = TranslationMemory(memory_path)
    options = TranslationOptions(provider="openai_compatible", model="gpt-test")

    memory.set(_line("Press Open"), options, "「開」を押します。")
    reloaded = TranslationMemory(memory_path)

    assert reloaded.get(_line("Press Open"), options) == "「開」を押します。"


def test_translation_memory_separates_models(tmp_path) -> None:
    memory = TranslationMemory(tmp_path / "memory.json")
    line = _line("Press Open")

    memory.set(line, TranslationOptions(provider="openai_compatible", model="model-a"), "A")

    assert memory.get(line, TranslationOptions(provider="openai_compatible", model="model-b")) is None
