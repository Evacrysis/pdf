import pytest

from app.models import JobRecord, JobStatus, TranslationOptions
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
