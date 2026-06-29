import pytest

from db.models import LLMProvider
from services.llm_provider_readiness import (
    is_llm_provider_configured,
    llm_provider_model_label,
)


@pytest.mark.parametrize(
    "api_key, provider_type, base_url, model_identifier, expected",
    [
        # Cloud providers
        ("some-api-key", "openai", None, None, True),
        ("some-api-key", "anthropic", "http://url", "model-id", True),
        (None, "openai", None, None, False),
        ("", "openai", None, None, False),
        ("   ", "openai", None, None, False),
        # Local providers
        (None, "ollama", "http://localhost:11434", "llama3", True),
        (None, "vllm", "http://localhost:8000", "mistral", True),
        (None, "local", "http://localhost:8000", "model", True),
        (None, "openai-compatible-local", "http://localhost:8000", "model", True),
        # Local provider missing base_url or model_identifier
        (None, "ollama", None, "llama3", False),
        (None, "ollama", "http://localhost:11434", None, False),
        (None, "ollama", None, None, False),
        (None, "ollama", "", "llama3", False),
        (None, "ollama", "http://localhost:11434", "   ", False),
        # Provider type edge cases (whitespace, casing)
        (None, " OLLAMA ", "http://url", "model", True),
        (None, " Vllm ", "http://url", "model", True),
        (
            None,
            "unknown-local",
            "http://url",
            "model",
            False,
        ),  # Not in LOCAL_PROVIDER_TYPES
        # API key provided for local (should just return True fast)
        ("api-key-for-local", "ollama", None, None, True),
        # Edge cases for provider_type being None
        ("some-api-key", None, None, None, True),
        (None, None, "http://localhost:11434", "llama3", False),
        # Edge cases for whitespace-only strings
        (None, "ollama", "   ", "llama3", False),
        (None, "ollama", "http://localhost", "   ", False),
        # Provider type non-string (should be caught by type hints, but None is possible)
        ("valid-key", None, "http://localhost", "model", True),
    ],
)
def test_is_llm_provider_configured(
    api_key, provider_type, base_url, model_identifier, expected
):
    provider = LLMProvider(
        user_id="user1",
        organization_id="org1",
        name="Test Provider",
        provider_type=provider_type,
        base_url=base_url,
        model_identifier=model_identifier,
        api_key=api_key,
    )
    assert is_llm_provider_configured(provider) == expected


@pytest.mark.parametrize(
    "provider_type, model_identifier, expected",
    [
        ("openai", "gpt-4o", "gpt-4o"),
        ("openai", "  gpt-4o  ", "gpt-4o"),
        ("ollama", "llama3", "llama3"),
        ("openai", None, "openai"),
        ("openai", "", "openai"),
        ("openai", "   ", "openai"),
    ],
)
def test_llm_provider_model_label(provider_type, model_identifier, expected):
    provider = LLMProvider(
        user_id="user1",
        organization_id="org1",
        name="Test Provider",
        provider_type=provider_type,
        model_identifier=model_identifier,
    )
    assert llm_provider_model_label(provider) == expected
