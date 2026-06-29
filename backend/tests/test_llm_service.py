import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.config import settings
from core.exceptions import LLMServiceError
from services import llm_provider_urls as provider_urls
from services.llm_service import (
    extract_todos_and_summary,
    draft_reply,
    ExtractionResult,
)


@pytest.fixture
def mock_openai():
    with patch("services.llm_service.AsyncOpenAI") as mock_async_openai:
        # Mock the AsyncOpenAI client instance
        mock_client_instance = MagicMock()
        mock_client_instance.close = AsyncMock()
        mock_async_openai.return_value = mock_client_instance
        yield mock_client_instance


# Removed reset_client fixture


def test_extraction_result_confidence_is_optional_and_bounded():
    omitted = ExtractionResult(summary="Test summary", todos=[])
    assert omitted.confidence is None

    assert ExtractionResult(
        summary="Test summary",
        todos=[],
        confidence=0,
    ).confidence == 0
    assert ExtractionResult(
        summary="Test summary",
        todos=[],
        confidence=100,
    ).confidence == 100

    with pytest.raises(ValueError):
        ExtractionResult(summary="Test summary", todos=[], confidence=101)


@pytest.mark.asyncio
async def test_llm_provider_pinned_backend_uses_validated_ip_address():
    calls = []
    stream = object()
    backend = provider_urls._PinnedLLMProviderNetworkBackend(
        "llm-gateway.example.com",
        443,
        ("93.184.216.34",),
    )

    class FakeBackend:
        async def connect_tcp(
            self,
            host,
            port,
            timeout=None,
            local_address=None,
            socket_options=None,
        ):
            calls.append((host, port, timeout, local_address, socket_options))
            return stream

        async def sleep(self, seconds):
            return None

    backend._backend = FakeBackend()

    result = await backend.connect_tcp(
        b"llm-gateway.example.com",
        443,
        timeout=3.0,
        local_address=None,
        socket_options=None,
    )

    assert result is stream
    assert calls == [("93.184.216.34", 443, 3.0, None, None)]


@pytest.mark.asyncio
async def test_llm_provider_pinned_backend_returns_first_parallel_success():
    stream = object()
    backend = provider_urls._PinnedLLMProviderNetworkBackend(
        "llm-gateway.example.com",
        443,
        ("93.184.216.34", "8.8.8.8"),
    )
    started_addresses: set[str] = set()
    cancelled_addresses: list[str] = []
    all_started = asyncio.Event()

    async def fake_connect(address, port, timeout, local_address, socket_options):
        started_addresses.add(address)
        if len(started_addresses) == 2:
            all_started.set()
        await all_started.wait()
        if address == "93.184.216.34":
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled_addresses.append(address)
                raise
        return stream

    backend._connect_validated_ip_address = fake_connect

    result = await backend.connect_tcp(
        "llm-gateway.example.com",
        443,
        timeout=3.0,
        local_address=None,
        socket_options=None,
    )

    assert result is stream
    assert started_addresses == {"93.184.216.34", "8.8.8.8"}
    assert cancelled_addresses == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_llm_provider_pinned_backend_propagates_all_failures():
    backend = provider_urls._PinnedLLMProviderNetworkBackend(
        "llm-gateway.example.com",
        443,
        ("93.184.216.34", "8.8.8.8"),
    )
    attempted_addresses: set[str] = set()

    async def fake_connect(address, port, timeout, local_address, socket_options):
        attempted_addresses.add(address)
        await asyncio.sleep(0)
        raise OSError(f"connect failed for {address}")

    backend._connect_validated_ip_address = fake_connect

    with pytest.raises(OSError, match="connect failed"):
        await backend.connect_tcp("llm-gateway.example.com", 443)

    assert attempted_addresses == {"93.184.216.34", "8.8.8.8"}


@pytest.mark.asyncio
async def test_llm_provider_pinned_backend_closes_extra_success_streams():
    class FakeStream:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    backend = provider_urls._PinnedLLMProviderNetworkBackend(
        "llm-gateway.example.com",
        443,
        ("93.184.216.34", "8.8.8.8"),
    )
    streams = {
        "93.184.216.34": FakeStream(),
        "8.8.8.8": FakeStream(),
    }

    async def fake_connect(address, port, timeout, local_address, socket_options):
        return streams[address]

    backend._connect_validated_ip_address = fake_connect

    result = await backend.connect_tcp("llm-gateway.example.com", 443)

    closed_streams = [stream for stream in streams.values() if stream.closed]
    assert result in streams.values()
    assert result.closed is False
    assert len(closed_streams) == 1


@pytest.mark.asyncio
async def test_llm_provider_pinned_backend_rejects_host_changes():
    backend = provider_urls._PinnedLLMProviderNetworkBackend(
        "llm-gateway.example.com",
        443,
        ("93.184.216.34",),
    )

    with pytest.raises(OSError, match="host changed"):
        await backend.connect_tcp("metadata.google.internal", 443)


@pytest.mark.asyncio
async def test_extract_todos_and_summary_success(mock_openai):
    # Setup mock response
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.parsed = ExtractionResult(summary="Test summary", todos=["Task 1"], confidence=90)
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]

    mock_openai.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    # Call the service
    result = await extract_todos_and_summary("Test email", "test-key")

    # Verify results
    assert result.summary == "Test summary"
    assert result.todos == ["Task 1"]
    mock_openai.beta.chat.completions.parse.assert_called_once()
    assert (
        mock_openai.beta.chat.completions.parse.call_args.kwargs["model"]
        == settings.OPENAI_MODEL
    )


@pytest.mark.asyncio
async def test_extract_todos_and_summary_uses_selected_provider_model(mock_openai):
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.parsed = ExtractionResult(
        summary="Test summary", todos=["Task 1"], confidence=90
    )
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_openai.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await extract_todos_and_summary(
        "Test email",
        "test-key",
        provider_name="Local Gemma4",
        model="gemma4",
    )

    assert result.provenance == "Local Gemma4 (gemma4)"
    assert mock_openai.beta.chat.completions.parse.call_args.kwargs["model"] == "gemma4"


@pytest.mark.asyncio
async def test_extract_todos_and_summary_api_error(mock_openai):
    # Setup mock to raise an exception
    mock_openai.beta.chat.completions.parse = AsyncMock(
        side_effect=Exception("API Error")
    )

    with pytest.raises(LLMServiceError, match="LLM API error during extraction"):
        await extract_todos_and_summary("Test email", "test-key")


@pytest.mark.asyncio
async def test_extract_todos_and_summary_disables_redirect_following_for_custom_base_url(
    monkeypatch,
):
    monkeypatch.setattr(
        settings, "ALLOWED_LLM_BASE_URL_HOSTS", "llm-gateway.example.com"
    )

    def fake_getaddrinfo(host, port, type=0):
        assert host == "llm-gateway.example.com"
        assert port == 443
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(
        "services.llm_provider_urls.socket.getaddrinfo", fake_getaddrinfo
    )

    with patch("services.llm_service.AsyncOpenAI") as mock_async_openai:
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.parsed = ExtractionResult(summary="Test summary", todos=["Task 1"], confidence=90)
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)
        mock_async_openai.return_value = mock_client

        result = await extract_todos_and_summary(
            "Test email",
            "test-key",
            base_url="https://llm-gateway.example.com/v1",
        )

    assert result.summary == "Test summary"
    assert result.todos == ["Task 1"]
    constructor_kwargs = mock_async_openai.call_args.kwargs
    assert "http_client" in constructor_kwargs
    assert constructor_kwargs["http_client"].follow_redirects is False
    await constructor_kwargs["http_client"].aclose()
    mock_client.close.assert_awaited_once()


def test_validate_llm_provider_base_url_accepts_allowlisted_local_provider(
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOWED_LLM_BASE_URL_HOSTS", "ollama")
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", True)

    def fake_getaddrinfo(host, port, type=0):
        assert host == "ollama"
        assert port == 11434
        return [(2, 1, 6, "", ("172.20.0.10", port))]

    monkeypatch.setattr(
        "services.llm_provider_urls.socket.getaddrinfo", fake_getaddrinfo
    )

    assert (
        provider_urls.validate_llm_provider_base_url("http://ollama:11434/v1")
        == "http://ollama:11434/v1"
    )


def test_validate_llm_provider_base_url_rejects_http_for_external_allowlisted_host(
    monkeypatch,
):
    monkeypatch.setattr(
        settings, "ALLOWED_LLM_BASE_URL_HOSTS", "llm-gateway.example.com"
    )
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", True)

    with pytest.raises(ValueError, match=provider_urls.LLM_BASE_URL_NOT_ALLOWED):
        provider_urls.validate_llm_provider_base_url(
            "http://llm-gateway.example.com/v1"
        )


def test_validate_llm_provider_base_url_rejects_private_external_dns(
    monkeypatch,
):
    monkeypatch.setattr(
        settings, "ALLOWED_LLM_BASE_URL_HOSTS", "llm-gateway.example.com"
    )
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", True)

    def fake_getaddrinfo(host, port, type=0):
        assert host == "llm-gateway.example.com"
        assert port == 443
        return [(2, 1, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(
        "services.llm_provider_urls.socket.getaddrinfo", fake_getaddrinfo
    )

    with pytest.raises(ValueError, match=provider_urls.LLM_BASE_URL_NOT_ALLOWED):
        provider_urls.validate_llm_provider_base_url_details(
            "https://llm-gateway.example.com/v1"
        )


def test_normalize_llm_provider_base_url_handles_local_development_hosts():
    assert provider_urls._normalize_llm_provider_base_url(
        "HTTP://LOCALHOST:11434/v1"
    ) == ("http://localhost:11434/v1", "localhost", 11434)
    assert provider_urls._normalize_llm_provider_base_url(
        "http://[::1]:11434/v1"
    ) == ("http://[::1]:11434/v1", "::1", 11434)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost:11434/v1",
        "http://user:pass@localhost:11434/v1",
        "http://localhost:11434/v1?token=secret",
        "http://localhost:11434/v1#fragment",
        "http://0x7f000001:11434/v1",
        "https://llm-gateway.example.com/v1\nX-Test: bad",
        "https://llm-gateway.example.com\\@metadata.google.internal/v1",
    ],
)
def test_normalize_llm_provider_base_url_rejects_unsafe_shapes(url):
    with pytest.raises(ValueError, match=provider_urls.LLM_BASE_URL_NOT_ALLOWED):
        provider_urls._normalize_llm_provider_base_url(url)


def test_validate_llm_provider_base_url_details_accepts_localhost_only_in_local_mode(
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOWED_LLM_BASE_URL_HOSTS", "")
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", True)

    def fake_getaddrinfo(host, port, type=0):
        assert host == "localhost"
        assert port == 11434
        return [(2, 1, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(
        "services.llm_provider_urls.socket.getaddrinfo", fake_getaddrinfo
    )

    details = provider_urls.validate_llm_provider_base_url_details(
        "http://localhost:11434/v1"
    )

    assert details is not None
    assert details.normalized_url == "http://localhost:11434/v1"
    assert details.hostname == "localhost"
    assert details.port == 11434
    assert details.addresses == ("127.0.0.1",)


def test_validate_llm_provider_base_url_details_rejects_localhost_without_local_mode(
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOWED_LLM_BASE_URL_HOSTS", "")
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", False)

    def fake_getaddrinfo(host, port, type=0):
        assert host == "localhost"
        assert port == 11434
        return [(2, 1, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(
        "services.llm_provider_urls.socket.getaddrinfo", fake_getaddrinfo
    )

    with pytest.raises(ValueError, match=provider_urls.LLM_BASE_URL_NOT_ALLOWED):
        provider_urls.validate_llm_provider_base_url_details(
            "http://localhost:11434/v1"
        )


def test_validate_llm_provider_base_url_rejects_local_provider_without_local_mode(
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOWED_LLM_BASE_URL_HOSTS", "ollama")
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", False)

    with pytest.raises(ValueError, match=provider_urls.LLM_BASE_URL_NOT_ALLOWED):
        provider_urls.validate_llm_provider_base_url("http://ollama:11434/v1")


@pytest.mark.asyncio
async def test_draft_reply_success(mock_openai):
    # Setup mock response
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "Drafted reply text"
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]

    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    # Call the service
    result = await draft_reply("Test email", "Draft a positive reply", "test-key")

    # Verify results
    assert result == "Drafted reply text"
    mock_openai.chat.completions.create.assert_called_once()
    assert (
        mock_openai.chat.completions.create.call_args.kwargs["model"]
        == settings.OPENAI_MODEL
    )


@pytest.mark.asyncio
async def test_draft_reply_uses_selected_provider_model(mock_openai):
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "Drafted reply text"
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]

    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await draft_reply(
        "Test email",
        "Draft a positive reply",
        "test-key",
        model="gemma4",
    )

    assert result == "Drafted reply text"
    assert mock_openai.chat.completions.create.call_args.kwargs["model"] == "gemma4"


@pytest.mark.asyncio
async def test_draft_reply_resolves_custom_base_url_off_event_loop(
    mock_openai, monkeypatch
):
    monkeypatch.setattr(
        settings, "ALLOWED_LLM_BASE_URL_HOSTS", "llm-gateway.example.com"
    )

    def fake_getaddrinfo(host, port, type=0):
        assert host == "llm-gateway.example.com"
        assert port == 443
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise AssertionError("LLM provider DNS resolution ran on event loop")
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(
        "services.llm_provider_urls.socket.getaddrinfo", fake_getaddrinfo
    )
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "Drafted reply text"
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await draft_reply(
        "Test email",
        "Draft a positive reply",
        "test-key",
        base_url="https://llm-gateway.example.com/v1",
    )

    assert result == "Drafted reply text"
    mock_openai.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_draft_reply_disables_redirect_following_for_custom_base_url(
    monkeypatch,
):
    monkeypatch.setattr(
        settings, "ALLOWED_LLM_BASE_URL_HOSTS", "llm-gateway.example.com"
    )

    def fake_getaddrinfo(host, port, type=0):
        assert host == "llm-gateway.example.com"
        assert port == 443
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(
        "services.llm_provider_urls.socket.getaddrinfo", fake_getaddrinfo
    )

    with patch("services.llm_service.AsyncOpenAI") as mock_async_openai:
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Drafted reply text"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_async_openai.return_value = mock_client

        result = await draft_reply(
            "Test email",
            "Draft a positive reply",
            "test-key",
            base_url="https://llm-gateway.example.com/v1",
        )

    assert result == "Drafted reply text"
    constructor_kwargs = mock_async_openai.call_args.kwargs
    assert "http_client" in constructor_kwargs
    assert constructor_kwargs["http_client"].follow_redirects is False
    await constructor_kwargs["http_client"].aclose()
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_draft_reply_api_error(mock_openai):
    # Setup mock to raise an exception
    mock_openai.chat.completions.create = AsyncMock(side_effect=Exception("API Error"))

    with pytest.raises(LLMServiceError, match="LLM API error during drafting"):
        await draft_reply("Test email", "Draft a positive reply", "test-key")
