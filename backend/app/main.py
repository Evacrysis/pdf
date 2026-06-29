from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.models import TranslationOptions
from app.services.jobs import job_store

app = FastAPI(title="PDF Translation Workbench", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/rules")
async def rules() -> dict:
    return {
        "strict": True,
        "hard_gates": [
            "no_missing_translation",
            "no_reduced_translation",
            "no_text_scaling",
            "same_role_font_consistency",
            "protected_tokens_source_backed",
            "no_overlap_or_duplicate_translation",
            "no_image_or_line_crop",
            "editable_pdf_text_layer",
            "page_by_page_review_required",
        ],
        "rules_file": "docs/rules/pairing_manual_workflow_rules.md",
    }


@app.post("/api/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_language: str = Form("en"),
    target_language: str = Form(settings.default_target_language),
    provider: str = Form("openai_compatible"),
    base_url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    strict_mode: bool = Form(True),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    options = TranslationOptions(
        source_language=source_language,
        target_language=target_language,
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
        strict_mode=strict_mode,
    )
    record = await job_store.create(file, options)
    background_tasks.add_task(job_store.process, record.id)
    return record.model_dump(mode="json")


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    record = job_store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return record.model_dump(mode="json")


@app.get("/api/jobs/{job_id}/download")
async def download(job_id: str) -> FileResponse:
    record = job_store.get(job_id)
    if record is None or record.output_path is None:
        raise HTTPException(status_code=404, detail="Output PDF not found.")
    path = Path(record.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Output PDF not found.")
    return FileResponse(path, media_type="application/pdf", filename=f"{job_id}_translated.pdf")
