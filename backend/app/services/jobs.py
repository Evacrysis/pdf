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
from app.models import JobRecord, JobStatus, PageReport, TranslatedLine, TranslationOptions
from app.services.pdf_geometry import extract_text_lines
from app.services.pdf_writer import write_editable_pdf
from app.services.rules import RuleEngine
from app.services.translator import get_translator


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

    def _persist(self, record: JobRecord) -> None:
        meta_path = self.root / record.id / "job.json"
        meta_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

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
            lines = extract_text_lines(str(record.source_path))
            self._set_progress(
                record,
                stage="translating",
                total_pages=total_pages,
                total_lines=len(lines),
                processed_lines=0,
                processed_pages=0,
            )
            translator = get_translator(record.options.provider)
            translated: list[TranslatedLine] = []
            processed_pages: set[int] = set()
            for index, line in enumerate(lines, start=1):
                translated_text = await translator.translate_line(line, record.options)
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

            self._set_progress(record, stage="writing_pdf")
            output_path = self.root / job_id / "translated.pdf"
            write_editable_pdf(record.source_path, output_path, translated, settings.pdf_font_path)

            self._set_progress(record, stage="qa")
            gates = RuleEngine().validate(translated)
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
            record.processed_pages = record.total_pages
            record.processed_lines = record.total_lines
            record.progress = 1
        except Exception as exc:
            record.status = JobStatus.failed
            record.stage = "failed"
            record.errors.append(str(exc))
        self._persist(record)


job_store = JobStore(settings.storage_dir / "jobs")
