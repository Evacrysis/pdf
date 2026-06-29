from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class GateSeverity(str, Enum):
    info = "info"
    warning = "warning"
    hard_fail = "hard_fail"


class TranslationOptions(BaseModel):
    source_language: str = "en"
    target_language: str = "ja"
    provider: str = "openai_compatible"
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = Field(default=None, exclude=True)
    strict_mode: bool = True


class ModelConnectionTestRequest(BaseModel):
    provider: str = "openai_compatible"
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = Field(default=None, exclude=True)


class ModelConnectionTestResult(BaseModel):
    ok: bool
    provider: str
    normalized_base_url: Optional[str] = None
    message: str
    model: Optional[str] = None
    model_found: Optional[bool] = None
    sample_models: list[str] = Field(default_factory=list)


class TextLine(BaseModel):
    page_index: int
    line_index: int
    text: str
    bbox: tuple[float, float, float, float]
    font_name: str
    font_size: float
    role: str = "body"
    protected_tokens: list[str] = Field(default_factory=list)
    localizable: bool = True


class TranslatedLine(BaseModel):
    source: TextLine
    translated_text: str
    output_font_size: float
    wrapped_lines: list[str] = Field(default_factory=list)


class GateResult(BaseModel):
    code: str
    severity: GateSeverity
    passed: bool
    message: str
    page_index: Optional[int] = None
    line_index: Optional[int] = None
    details: dict[str, Any] = Field(default_factory=dict)


class PageReport(BaseModel):
    page_index: int
    status: str
    line_count: int
    failures: list[GateResult] = Field(default_factory=list)
    warnings: list[GateResult] = Field(default_factory=list)


class JobRecord(BaseModel):
    id: str
    status: JobStatus
    options: TranslationOptions
    source_filename: str
    source_path: Path
    output_path: Optional[Path] = None
    report_path: Optional[Path] = None
    stage: str = "queued"
    progress: float = 0
    total_pages: int = 0
    processed_pages: int = 0
    total_lines: int = 0
    processed_lines: int = 0
    pages: list[PageReport] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
