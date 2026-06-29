from __future__ import annotations

import json
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models import ModelConnectionTestResult, TextLine, TranslationOptions


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
    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise RuntimeError("Model API Base URL is required")
        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            raise RuntimeError("Model API Base URL must include scheme and host, for example https://api.example.com/v1")
        path = parsed.path.rstrip("/")
        for suffix in ("/chat/completions", "/models"):
            if path.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                path = path[: -len(suffix)]
                break
        if not path.endswith("/v1"):
            normalized = f"{normalized}/v1"
        return normalized.rstrip("/")

    @classmethod
    def completion_url(cls, base_url: str) -> str:
        return f"{cls.normalize_base_url(base_url)}/chat/completions"

    @classmethod
    def models_url(cls, base_url: str) -> str:
        return f"{cls.normalize_base_url(base_url)}/models"

    @staticmethod
    def _extract_error(response: httpx.Response) -> str:
        content_type = response.headers.get("content-type", "")
        try:
            body = response.json()
        except ValueError:
            snippet = response.text[:500].replace("\n", " ")
            return (
                f"Model API returned non-JSON response. "
                f"status={response.status_code}, content-type={content_type}, body={snippet}"
            )

        if isinstance(body, dict) and "error" in body:
            error = body["error"]
            if isinstance(error, dict):
                message = error.get("message") or error
            else:
                message = error
            return f"Model API error. status={response.status_code}, message={message}"
        return f"Model API error. status={response.status_code}, body={body}"

    async def translate_line(self, line: TextLine, options: TranslationOptions) -> str:
        if not line.localizable:
            return line.text

        api_key = options.api_key or settings.openai_api_key
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for strict translation jobs")

        base_url = (options.base_url or settings.openai_base_url).rstrip("/")
        model = options.model or settings.default_model
        completion_url = self.completion_url(base_url)
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
            response = await client.post(completion_url, json=payload, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(self._extract_error(response))
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError(self._extract_error(response)) from None
        try:
            content = body["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"Model API response missing choices[0].message.content: {body}") from None
        try:
            parsed = json.loads(content)
            return str(parsed["translation"]).strip()
        except Exception:
            return content.strip()

    async def test_connection(self, options: TranslationOptions) -> ModelConnectionTestResult:
        base_url = options.base_url or settings.openai_base_url
        normalized = self.normalize_base_url(base_url)
        api_key = options.api_key or settings.openai_api_key
        if not api_key:
            return ModelConnectionTestResult(
                ok=False,
                provider=options.provider,
                normalized_base_url=normalized,
                model=options.model,
                message="API Key is required for OpenAI-compatible provider.",
            )

        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self.models_url(base_url), headers=headers)

        if response.status_code >= 400:
            return ModelConnectionTestResult(
                ok=False,
                provider=options.provider,
                normalized_base_url=normalized,
                model=options.model,
                message=self._extract_error(response),
            )

        try:
            body = response.json()
        except ValueError:
            return ModelConnectionTestResult(
                ok=False,
                provider=options.provider,
                normalized_base_url=normalized,
                model=options.model,
                message=self._extract_error(response),
            )

        raw_models = body.get("data", []) if isinstance(body, dict) else []
        model_ids = [
            str(item.get("id"))
            for item in raw_models
            if isinstance(item, dict) and item.get("id")
        ]
        model = options.model or settings.default_model
        model_found = model in model_ids if model and model_ids else None
        if model and model_ids and not model_found:
            message = f"API is reachable, but model '{model}' was not found in /models."
        else:
            message = "API is reachable."
        return ModelConnectionTestResult(
            ok=not (model and model_ids and not model_found),
            provider=options.provider,
            normalized_base_url=normalized,
            model=model,
            model_found=model_found,
            sample_models=model_ids[:12],
            message=message,
        )


class DryRunTranslator(Translator):
    async def translate_line(self, line: TextLine, options: TranslationOptions) -> str:
        if not line.localizable:
            return line.text
        return f"[DRY-RUN:{options.target_language}] {line.text}"

    async def test_connection(self, options: TranslationOptions) -> ModelConnectionTestResult:
        return ModelConnectionTestResult(
            ok=True,
            provider=options.provider,
            model=options.model,
            message="Dry run provider is available locally and does not call an external API.",
        )


class AnthropicCompatibleTranslator(Translator):
    anthropic_version = "2023-06-01"

    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise RuntimeError("Anthropic-compatible Base URL is required")
        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            raise RuntimeError("Anthropic-compatible Base URL must include scheme and host, for example https://api.anthropic.com/v1")
        path = parsed.path.rstrip("/")
        for suffix in ("/messages", "/models"):
            if path.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                path = path[: -len(suffix)]
                break
        if not path.endswith("/v1"):
            normalized = f"{normalized}/v1"
        return normalized.rstrip("/")

    @classmethod
    def messages_url(cls, base_url: str) -> str:
        return f"{cls.normalize_base_url(base_url)}/messages"

    @classmethod
    def models_url(cls, base_url: str) -> str:
        return f"{cls.normalize_base_url(base_url)}/models"

    @classmethod
    def _headers(cls, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": cls.anthropic_version,
            "content-type": "application/json",
        }

    @staticmethod
    def _extract_error(response: httpx.Response) -> str:
        content_type = response.headers.get("content-type", "")
        try:
            body = response.json()
        except ValueError:
            snippet = response.text[:500].replace("\n", " ")
            return (
                f"Anthropic-compatible API returned non-JSON response. "
                f"status={response.status_code}, content-type={content_type}, body={snippet}"
            )

        if isinstance(body, dict) and "error" in body:
            error = body["error"]
            if isinstance(error, dict):
                message = error.get("message") or error
            else:
                message = error
            return f"Anthropic-compatible API error. status={response.status_code}, message={message}"
        return f"Anthropic-compatible API error. status={response.status_code}, body={body}"

    async def translate_line(self, line: TextLine, options: TranslationOptions) -> str:
        if not line.localizable:
            return line.text

        api_key = options.api_key or settings.openai_api_key
        if not api_key:
            raise RuntimeError("API Key is required for Anthropic-compatible translation jobs")

        base_url = options.base_url or settings.openai_base_url
        model = options.model or settings.default_model
        payload = {
            "model": model,
            "max_tokens": 1024,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [
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
                }
            ],
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(self.messages_url(base_url), json=payload, headers=self._headers(api_key))
        if response.status_code >= 400:
            raise RuntimeError(self._extract_error(response))
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError(self._extract_error(response)) from None
        try:
            text_blocks = body["content"]
            content = "".join(block.get("text", "") for block in text_blocks if isinstance(block, dict)).strip()
        except (KeyError, TypeError):
            raise RuntimeError(f"Anthropic-compatible response missing content text: {body}") from None
        try:
            parsed = json.loads(content)
            return str(parsed["translation"]).strip()
        except Exception:
            return content.strip()

    async def test_connection(self, options: TranslationOptions) -> ModelConnectionTestResult:
        base_url = options.base_url or settings.openai_base_url
        normalized = self.normalize_base_url(base_url)
        api_key = options.api_key or settings.openai_api_key
        if not api_key:
            return ModelConnectionTestResult(
                ok=False,
                provider=options.provider,
                normalized_base_url=normalized,
                model=options.model,
                message="API Key is required for Anthropic-compatible provider.",
            )

        model = options.model or settings.default_model
        async with httpx.AsyncClient(timeout=30) as client:
            models_response = await client.get(self.models_url(base_url), headers=self._headers(api_key))

        sample_models: list[str] = []
        model_found: bool | None = None
        if models_response.status_code < 400:
            try:
                body = models_response.json()
                raw_models = body.get("data", []) if isinstance(body, dict) else []
                sample_models = [
                    str(item.get("id"))
                    for item in raw_models
                    if isinstance(item, dict) and item.get("id")
                ][:12]
                if sample_models and model:
                    model_found = model in sample_models
            except ValueError:
                sample_models = []
        else:
            message = self._extract_error(models_response)
            if models_response.status_code not in {404, 405}:
                return ModelConnectionTestResult(
                    ok=False,
                    provider=options.provider,
                    normalized_base_url=normalized,
                    model=model,
                    message=message,
                )

        probe_payload = {
            "model": model,
            "max_tokens": 16,
            "temperature": 0,
            "messages": [{"role": "user", "content": "Reply with OK only."}],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            probe_response = await client.post(
                self.messages_url(base_url),
                json=probe_payload,
                headers=self._headers(api_key),
            )
        if probe_response.status_code >= 400:
            return ModelConnectionTestResult(
                ok=False,
                provider=options.provider,
                normalized_base_url=normalized,
                model=model,
                model_found=model_found,
                sample_models=sample_models,
                message=self._extract_error(probe_response),
            )
        return ModelConnectionTestResult(
            ok=True,
            provider=options.provider,
            normalized_base_url=normalized,
            model=model,
            model_found=model_found,
            sample_models=sample_models,
            message="Anthropic-compatible API is reachable.",
        )


def get_translator(provider: str) -> Translator:
    if provider == "dry_run":
        return DryRunTranslator()
    if provider == "anthropic_compatible":
        return AnthropicCompatibleTranslator()
    return OpenAICompatibleTranslator()
