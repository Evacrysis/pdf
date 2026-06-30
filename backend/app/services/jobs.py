from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

import fitz
from fastapi import UploadFile

from app.config import settings
from app.models import GateResult, JobRecord, JobStatus, PageReport, TranslatedLine, TranslationOptions
from app.services.pdf_geometry import extract_text_lines
from app.services.pdf_writer import write_editable_pdf
from app.services.line_processing import fixed_translation_for, merge_known_semantic_lines
from app.services.rules import RuleEngine
from app.services.translation_memory import TranslationMemory
from app.services.translator import get_translator


MAX_REPAIR_PASSES = 2
REPAIRABLE_TEXT_GATE_CODES = {
    "protected_token_missing",
    "english_residue",
    "fixed_translation_mismatch",
    "empty_protected_icon_bracket",
}
REPAIRABLE_OUTPUT_GATE_CODES = {
    "translated_text_line_overlap",
    "translated_text_overlaps_source_line",
}


def _gate_payload(gate: GateResult) -> dict:
    return {
        "code": gate.code,
        "message": gate.message,
        "page_index": gate.page_index,
        "line_index": gate.line_index,
        "details": gate.details,
    }


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _matching_translated_line(translated: list[TranslatedLine], page_index: int | None, text: str | None) -> TranslatedLine | None:
    if page_index is None or not text:
        return None
    needle = _normalize_text(text)
    if not needle:
        return None
    for item in translated:
        if item.source.page_index != page_index:
            continue
        candidates = [item.translated_text, *item.wrapped_lines]
        if any(needle in _normalize_text(candidate) or _normalize_text(candidate) in needle for candidate in candidates):
            return item
    return None


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        self.jobs: dict[str, JobRecord] = {}
        self.root.mkdir(parents=True, exist_ok=True)

    async def create(self, upload: UploadFile, options: TranslationOptions) -> JobRecord:
        job_id = uuid.uuid4().hex
        job_dir = self.root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "source.pdf"
        with source_path.open("wb") as target:
            shutil.copyfileobj(upload.file, target)
        record = JobRecord(
            id=job_id,
            status=JobStatus.queued,
            options=options,
            source_filename=upload.filename or "source.pdf",
            source_path=source_path,
        )
        self.jobs[job_id] = record
        self._persist(record)
        return record

    def get(self, job_id: str) -> Optional[JobRecord]:
        if job_id in self.jobs:
            return self.jobs[job_id]
        meta_path = self.root / job_id / "job.json"
        if not meta_path.exists():
            return None
        record = JobRecord.model_validate_json(meta_path.read_text(encoding="utf-8"))
        self.jobs[job_id] = record
        return record

    @staticmethod
    def public_dump(record: JobRecord) -> dict:
        return record.model_dump(mode="json", exclude={"options": {"api_key"}})

    def _persist(self, record: JobRecord) -> None:
        meta_path = self.root / record.id / "job.json"
        payload = record.model_dump(mode="json")
        if record.options.api_key:
            payload.setdefault("options", {})["api_key"] = record.options.api_key
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _set_progress(
        self,
        record: JobRecord,
        *,
        stage: str,
        processed_lines: Optional[int] = None,
        total_lines: Optional[int] = None,
        processed_pages: Optional[int] = None,
        total_pages: Optional[int] = None,
    ) -> None:
        record.stage = stage
        if processed_lines is not None:
            record.processed_lines = processed_lines
        if total_lines is not None:
            record.total_lines = total_lines
        if processed_pages is not None:
            record.processed_pages = processed_pages
        if total_pages is not None:
            record.total_pages = total_pages

        if record.total_lines > 0:
            record.progress = min(0.95, record.processed_lines / record.total_lines * 0.9)
        elif record.total_pages > 0:
            record.progress = min(0.95, record.processed_pages / record.total_pages * 0.9)
        else:
            record.progress = 0.02 if record.status == JobStatus.running else record.progress
        self._persist(record)

    @staticmethod
    def _page_count(pdf_path: Path) -> int:
        doc = fitz.open(pdf_path)
        try:
            return doc.page_count
        finally:
            doc.close()

    @staticmethod
    def _selected_page_indexes(options: TranslationOptions, total_pages: int) -> set[int]:
        start = options.page_start or 1
        end = options.page_end or total_pages
        if start < 1 or end < 1:
            raise RuntimeError("Page range must use 1-based positive page numbers.")
        if start > end:
            raise RuntimeError("Page range start must be less than or equal to page range end.")
        if start > total_pages:
            raise RuntimeError(f"Page range starts after the document ends. total_pages={total_pages}")
        end = min(end, total_pages)
        return set(range(start - 1, end))

    async def process(self, job_id: str) -> None:
        record = self.get(job_id)
        if record is None:
            return
        record.status = JobStatus.running
        record.stage = "extracting"
        record.progress = 0.02
        self._persist(record)
        try:
            total_pages = self._page_count(record.source_path)
            selected_pages = self._selected_page_indexes(record.options, total_pages)
            all_lines = extract_text_lines(str(record.source_path))
            lines = merge_known_semantic_lines([line for line in all_lines if line.page_index in selected_pages])
            if not lines:
                raise RuntimeError("Selected page range contains no extractable text lines.")
            self._set_progress(
                record,
                stage="translating",
                total_pages=total_pages,
                total_lines=len(lines),
                processed_lines=0,
                processed_pages=0,
            )
            translator = get_translator(record.options.provider)
            memory = TranslationMemory(self.root / "translation-memory.json")
            translated: list[TranslatedLine] = []
            processed_pages: set[int] = set()
            for index, line in enumerate(lines, start=1):
                fixed_translation = fixed_translation_for(line)
                if fixed_translation is not None:
                    translated_text = fixed_translation
                else:
                    cached = memory.get(line, record.options)
                    if cached is None:
                        try:
                            translated_text = await translator.translate_line(line, record.options)
                        except Exception as exc:
                            snippet = line.text[:80].replace("\n", " ")
                            raise RuntimeError(
                                f"Translation failed at page {line.page_index + 1}, line {line.line_index + 1}: "
                                f"{exc}. source={snippet}"
                            ) from exc
                        memory.set(line, record.options, translated_text)
                    else:
                        translated_text = cached
                translated.append(
                    TranslatedLine(
                        source=line,
                        translated_text=translated_text,
                        output_font_size=line.font_size,
                    )
                )
                processed_pages.add(line.page_index)
                self._set_progress(
                    record,
                    stage="translating",
                    processed_lines=index,
                    processed_pages=len(processed_pages),
                )
                await asyncio.sleep(0)

            output_path = self.root / job_id / "translated.pdf"

            rule_engine = RuleEngine()
            gates: list[GateResult] = []
            for repair_pass in range(MAX_REPAIR_PASSES + 1):
                self._set_progress(record, stage="qa" if repair_pass == 0 else f"repairing_pass_{repair_pass}")
                text_gates = rule_engine.validate(translated)
                if repair_pass < MAX_REPAIR_PASSES:
                    repaired_text = await self._repair_text_gate_failures(
                        translated,
                        text_gates,
                        translator,
                        record.options,
                    )
                    if repaired_text:
                        continue

                self._set_progress(record, stage="writing_pdf")
                write_editable_pdf(record.source_path, output_path, translated, settings.pdf_font_path)

                self._set_progress(record, stage="qa")
                output_gates = rule_engine.validate_output_pdf(record.source_path, output_path, translated)
                gates = [*text_gates, *output_gates]
                hard_failures = [gate for gate in gates if gate.severity == "hard_fail"]
                if not hard_failures:
                    break
                if repair_pass < MAX_REPAIR_PASSES:
                    repaired_output = await self._repair_output_gate_failures(
                        translated,
                        output_gates,
                        translator,
                        record.options,
                    )
                    if repaired_output:
                        continue
                break
            pages: list[PageReport] = []
            page_indexes = sorted({line.source.page_index for line in translated})
            for page_index in page_indexes:
                page_failures = [gate for gate in gates if gate.page_index == page_index and gate.severity == "hard_fail"]
                page_warnings = [gate for gate in gates if gate.page_index == page_index and gate.severity != "hard_fail"]
                pages.append(
                    PageReport(
                        page_index=page_index,
                        status="failed" if page_failures else "passed",
                        line_count=len([line for line in translated if line.source.page_index == page_index]),
                        failures=page_failures,
                        warnings=page_warnings,
                    )
                )

            report_path = self.root / job_id / "qa-report.json"
            report_path.write_text(
                json.dumps([page.model_dump(mode="json") for page in pages], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            record.output_path = output_path
            record.report_path = report_path
            record.pages = pages
            hard_failures = [gate for gate in gates if gate.severity == "hard_fail"]
            record.status = JobStatus.failed if record.options.strict_mode and hard_failures else JobStatus.completed
            record.stage = "completed" if record.status == JobStatus.completed else "qa_failed"
            record.processed_pages = len({line.source.page_index for line in translated})
            record.processed_lines = record.total_lines
            record.progress = 1
        except Exception as exc:
            record.status = JobStatus.failed
            record.stage = "failed"
            record.errors.append(str(exc))
        self._persist(record)

    async def _repair_text_gate_failures(
        self,
        translated: list[TranslatedLine],
        gates: list[GateResult],
        translator,
        options: TranslationOptions,
    ) -> int:
        grouped: dict[tuple[int, int], list[GateResult]] = {}
        for gate in gates:
            if gate.severity != "hard_fail" or gate.code not in REPAIRABLE_TEXT_GATE_CODES:
                continue
            if gate.page_index is None or gate.line_index is None:
                continue
            grouped.setdefault((gate.page_index, gate.line_index), []).append(gate)

        repaired = 0
        for item in translated:
            failures = grouped.get((item.source.page_index, item.source.line_index))
            if not failures:
                continue
            fixed_translation = fixed_translation_for(item.source)
            if fixed_translation is not None and item.translated_text != fixed_translation:
                item.translated_text = fixed_translation
                item.wrapped_lines = []
                repaired += 1
                continue
            repaired_translation = await translator.repair_translation(
                item.source,
                item.translated_text,
                [_gate_payload(gate) for gate in failures],
                options,
            )
            if repaired_translation and repaired_translation != item.translated_text:
                item.translated_text = repaired_translation
                item.wrapped_lines = []
                repaired += 1
        return repaired

    async def _repair_output_gate_failures(
        self,
        translated: list[TranslatedLine],
        gates: list[GateResult],
        translator,
        options: TranslationOptions,
    ) -> int:
        grouped: dict[int, list[GateResult]] = {}
        for gate in gates:
            if gate.severity != "hard_fail" or gate.code not in REPAIRABLE_OUTPUT_GATE_CODES:
                continue
            text = gate.details.get("text") or gate.details.get("first") or gate.details.get("second")
            item = _matching_translated_line(translated, gate.page_index, text)
            if item is None:
                continue
            grouped.setdefault(id(item), []).append(gate)

        repaired = 0
        items_by_id = {id(item): item for item in translated}
        for item_id, failures in grouped.items():
            item = items_by_id[item_id]
            fixed_translation = fixed_translation_for(item.source)
            if fixed_translation is not None and item.translated_text != fixed_translation:
                item.translated_text = fixed_translation
                item.wrapped_lines = []
                repaired += 1
                continue
            repaired_translation = await translator.repair_translation(
                item.source,
                item.translated_text,
                [_gate_payload(gate) for gate in failures],
                options,
            )
            if repaired_translation and repaired_translation != item.translated_text:
                item.translated_text = repaired_translation
                item.wrapped_lines = []
                repaired += 1
        return repaired


job_store = JobStore(settings.storage_dir / "jobs")
