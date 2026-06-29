import pytest

from app.models import TranslationOptions
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
