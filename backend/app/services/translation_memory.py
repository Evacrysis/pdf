from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.models import TextLine, TranslationOptions


TRANSLATION_MEMORY_VERSION = "2026-06-29-semantic-fixed-rules-v4"


class TranslationMemory:
    """Persistent text-level memory for deterministic repeated translations."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items()}

    def _save(self) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self._entries, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    @staticmethod
    def key_for(line: TextLine, options: TranslationOptions) -> str:
        payload = {
            "version": TRANSLATION_MEMORY_VERSION,
            "source_language": options.source_language,
            "target_language": options.target_language,
            "provider": options.provider,
            "model": options.model,
            "role": line.role,
            "source_text": " ".join(line.text.split()),
            "protected_tokens": line.protected_tokens,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, line: TextLine, options: TranslationOptions) -> str | None:
        return self._entries.get(self.key_for(line, options))

    def set(self, line: TextLine, options: TranslationOptions, translation: str) -> None:
        self._entries[self.key_for(line, options)] = translation
        self._save()
