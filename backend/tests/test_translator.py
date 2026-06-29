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
