import asyncio

import pytest

from app.models import GateResult, GateSeverity, JobRecord, JobStatus, TextLine, TranslatedLine, TranslationOptions
from app.services.jobs import JobStore


def test_selected_page_indexes_are_one_based_inclusive() -> None:
    options = TranslationOptions(page_start=2, page_end=4)

    assert JobStore._selected_page_indexes(options, total_pages=10) == {1, 2, 3}


def test_selected_page_indexes_defaults_to_full_document() -> None:
    options = TranslationOptions()

    assert JobStore._selected_page_indexes(options, total_pages=3) == {0, 1, 2}


def test_selected_page_indexes_rejects_invalid_range() -> None:
    options = TranslationOptions(page_start=5, page_end=3)

    with pytest.raises(RuntimeError):
        JobStore._selected_page_indexes(options, total_pages=10)


def test_job_persistence_restores_api_key_without_public_exposure(tmp_path) -> None:
    store = JobStore(tmp_path)
    job_dir = tmp_path / "job-1"
    job_dir.mkdir()
    source_path = job_dir / "source.pdf"
    source_path.write_bytes(b"%PDF-1.7\n")
    record = JobRecord(
        id="job-1",
        status=JobStatus.queued,
        options=TranslationOptions(api_key="secret-token", provider="openai_compatible"),
        source_filename="source.pdf",
        source_path=source_path,
    )

    store._persist(record)
    store.jobs.clear()

    restored = store.get("job-1")

    assert restored is not None
    assert restored.options.api_key == "secret-token"
    assert "api_key" not in store.public_dump(restored)["options"]


def test_output_repair_does_not_rewrite_fixed_translation(tmp_path) -> None:
    class RewritingTranslator:
        called = False

        async def repair_translation(self, line, current_translation, failures, options):
            self.called = True
            return "モデルが書き換えた文"

    store = JobStore(tmp_path)
    source = TextLine(
        page_index=0,
        line_index=0,
        text=(
            "When received, the blocker prevents the motor receiving signal. "
            "To activate it, please remove the sleeping blocker. "
            "If the motor is left idle for over 6 months, please insert the sleeping "
            "blocker into the charging port to reduce battery consumption."
        ),
        bbox=(100, 154, 546, 222),
        font_name="Helvetica",
        font_size=14,
        role="body",
    )
    fixed = (
        "受信時、ブロッカーはモーターの信号受信を防ぎます。\n"
        "使用するには、スリーピングブロッカーを取り外してください。\n"
        "6か月以上使用しない場合は、バッテリー消費を抑えるため、\n"
        "ブロッカーを充電ポートに差し込んでください。"
    )
    item = TranslatedLine(source=source, translated_text=fixed, output_font_size=14, wrapped_lines=[fixed])
    gate = GateResult(
        code="translated_text_overlaps_source_line",
        severity=GateSeverity.hard_fail,
        passed=False,
        page_index=0,
        message="overlap",
        details={"text": "受信時"},
    )
    translator = RewritingTranslator()

    repaired = asyncio.run(
        store._repair_output_gate_failures([item], [gate], translator, TranslationOptions(provider="dry_run"))
    )

    assert repaired == 0
    assert not translator.called
    assert item.translated_text == fixed
