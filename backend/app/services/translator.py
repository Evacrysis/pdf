from __future__ import annotations

import json
from abc import ABC, abstractmethod

import httpx

from app.config import settings
from app.models import TextLine, TranslationOptions


SYSTEM_PROMPT = """You translate PDF manual text under strict layout rules.
Return only JSON: {"translation":"..."}.
Rules:
- Preserve complete source meaning. No omission, no shortening that loses meaning.
- Protected button/display/icon tokens must remain unchanged in Japanese brackets when appropriate.
- Do not translate device/accessory printed English or protected display values.
- Prefer natural Japanese. If one line can fit naturally, do not force a line break.
- Keep source punctuation meaning but do not invent content.
"""


class Translator(ABC):
    @abstractmethod
    async def translate_line(self, line: TextLine, options: TranslationOptions) -> str:
        raise NotImplementedError


class OpenAICompatibleTranslator(Translator):
    async def translate_line(self, line: TextLine, options: TranslationOptions) -> str:
        if not line.localizable:
            return line.text

        api_key = options.api_key or settings.openai_api_key
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for strict translation jobs")

        base_url = (options.base_url or settings.openai_base_url).rstrip("/")
        model = options.model or settings.default_model
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "source_language": options.source_language,
                            "target_language": options.target_language,
                            "role": line.role,
                            "source_text": line.text,
                            "protected_tokens": line.protected_tokens,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        try:
            parsed = json.loads(content)
            return str(parsed["translation"]).strip()
        except Exception:
            return content.strip()


class DryRunTranslator(Translator):
    async def translate_line(self, line: TextLine, options: TranslationOptions) -> str:
        if not line.localizable:
            return line.text
        return f"[DRY-RUN:{options.target_language}] {line.text}"


def get_translator(provider: str) -> Translator:
    if provider == "dry_run":
        return DryRunTranslator()
    return OpenAICompatibleTranslator()
