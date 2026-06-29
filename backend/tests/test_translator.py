import asyncio

import httpx

from app.models import TranslationOptions
from app.services.translator import AnthropicCompatibleTranslator, OpenAICompatibleTranslator


def test_completion_url_adds_v1_for_provider_root() -> None:
    assert (
        OpenAICompatibleTranslator.completion_url("https://maoyulin.xyz/")
        == "https://maoyulin.xyz/v1/chat/completions"
    )


def test_completion_url_keeps_existing_v1() -> None:
    assert (
        OpenAICompatibleTranslator.completion_url("https://api.openai.com/v1")
        == "https://api.openai.com/v1/chat/completions"
    )


def test_completion_url_accepts_full_completion_url() -> None:
    assert (
        OpenAICompatibleTranslator.completion_url("https://api.example.com/v1/chat/completions")
        == "https://api.example.com/v1/chat/completions"
    )


def test_models_url_accepts_full_models_url() -> None:
    assert (
        OpenAICompatibleTranslator.models_url("https://api.example.com/v1/models")
        == "https://api.example.com/v1/models"
    )


def test_anthropic_messages_url_adds_v1_for_provider_root() -> None:
    assert (
        AnthropicCompatibleTranslator.messages_url("https://api.anthropic.com/")
        == "https://api.anthropic.com/v1/messages"
    )


def test_anthropic_messages_url_accepts_full_messages_url() -> None:
    assert (
        AnthropicCompatibleTranslator.messages_url("https://api.example.com/v1/messages")
        == "https://api.example.com/v1/messages"
    )


def test_anthropic_models_url_accepts_full_models_url() -> None:
    assert (
        AnthropicCompatibleTranslator.models_url("https://api.example.com/v1/models")
        == "https://api.example.com/v1/models"
    )


def test_openai_connection_test_probes_chat_completion(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeAsyncClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, headers: dict[str, str]):
            calls.append(("GET", url))
            return httpx.Response(
                200,
                json={"data": [{"id": "gpt-test"}]},
            )

        async def post(self, url: str, json: dict, headers: dict[str, str]):
            calls.append(("POST", url))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "OK"}}]},
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    result = asyncio.run(
        OpenAICompatibleTranslator().test_connection(
            TranslationOptions(
                provider="openai_compatible",
                base_url="https://api.example.com",
                model="gpt-test",
                api_key="token",
            )
        )
    )

    assert result.ok is True
    assert calls == [
        ("GET", "https://api.example.com/v1/models"),
        ("POST", "https://api.example.com/v1/chat/completions"),
    ]
