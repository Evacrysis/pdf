from typing import Optional

from app.models import JobRecord, JobStatus, TextLine, TranslatedLine, TranslationOptions
from app.services.rules import RuleEngine


def line(
    text: str,
    translated: str,
    size: float = 12,
    output_size: Optional[float] = None,
    role: str = "body",
) -> TranslatedLine:
    src = TextLine(
        page_index=0,
        line_index=0,
        text=text,
        bbox=(0, 0, 100, 20),
        font_name="Helvetica",
        font_size=size,
        role=role,
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


def test_allows_window_covering_product_terms() -> None:
    results = RuleEngine().validate([line("For Shangri-la Shades", "Shangri-la Shades 用")])
    assert not any(result.code == "english_residue" for result in results)


def test_rejects_missing_protected_token() -> None:
    item = line('Press "OK"', "押します。")
    item.source.protected_tokens = ['"OK"']
    results = RuleEngine().validate([item])
    assert any(result.code == "protected_token_missing" for result in results)


def test_figure_label_source_size_variation_is_warning_not_hard_fail() -> None:
    results = RuleEngine().validate(
        [
            line("PULL", "引く", size=7.16, role="figure_label"),
            line("REMOVE", "取り外す", size=2.94, role="figure_label"),
        ]
    )

    matching = [result for result in results if result.code == "same_role_font_mismatch"]
    assert matching
    assert matching[0].severity == "warning"


def test_rejects_known_fixed_translation_mismatch() -> None:
    results = RuleEngine().validate(
        [line("1-9 Channel: One channel corresponds to one blind.", "1つのブラインドに対応します。")]
    )

    assert any(result.code == "fixed_translation_mismatch" for result in results)


def test_rejects_empty_icon_brackets_for_quote_gap_source() -> None:
    results = RuleEngine().validate([line('Press "    " or "    "', "「」または「」を押す")])

    assert any(result.code == "empty_protected_icon_bracket" for result in results)


def test_api_key_is_not_serialized() -> None:
    options = TranslationOptions(api_key="secret-value")
    dumped = options.model_dump()
    assert "api_key" not in dumped


def test_job_progress_is_serialized(tmp_path) -> None:
    record = JobRecord(
        id="job-1",
        status=JobStatus.running,
        source_filename="source.pdf",
        source_path=tmp_path / "source.pdf",
        options=TranslationOptions(),
        stage="translating",
        progress=0.5,
        total_pages=4,
        processed_pages=2,
        total_lines=40,
        processed_lines=20,
    )

    dumped = record.model_dump()

    assert dumped["stage"] == "translating"
    assert dumped["progress"] == 0.5
    assert dumped["processed_lines"] == 20
