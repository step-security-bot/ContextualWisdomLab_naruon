import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend
from httpx._config import DEFAULT_LIMITS, create_ssl_context
from httpx._transports.default import AsyncResponseStream, map_httpcore_exceptions

from core.config import settings

LLM_BASE_URL_NOT_ALLOWED = "LLM provider base URL is not allowed"
_DNS_RESOLUTION_TIMEOUT_SECONDS = 5.0
_LOCAL_DEV_HOSTNAMES = {"localhost", "localhost.localdomain"}
_LOCAL_DEV_IP_LITERALS = {"127.0.0.1", "::1"}


def _has_url_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


@dataclass(frozen=True)
class ValidatedLLMProviderBaseURL:
    normalized_url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def _parse_allowed_hosts() -> set[str]:
    return {
        item.strip().lower().rstrip(".")
        for item in settings.ALLOWED_LLM_BASE_URL_HOSTS.split(",")
        if item.strip()
    }


def _is_ip_literal(candidate: str) -> bool:
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return True


def _looks_like_ip_literal(candidate: str) -> bool:
    compact_candidate = candidate.replace(".", "").lower()
    return (
        ":" in candidate
        or compact_candidate.isdigit()
        or compact_candidate.startswith("0x")
    )


def _is_local_dev_host(hostname: str) -> bool:
    normalized_hostname = hostname.lower().rstrip(".")
    return (
        normalized_hostname in _LOCAL_DEV_HOSTNAMES
        or normalized_hostname in _LOCAL_DEV_IP_LITERALS
    )


def _is_allowlisted_local_provider_host(hostname: str) -> bool:
    normalized_hostname = hostname.lower().rstrip(".")
    return (
        settings.ALLOW_LOCAL_LLM_PROVIDERS
        and normalized_hostname in _parse_allowed_hosts()
        and "." not in normalized_hostname
        and not _is_ip_literal(normalized_hostname)
        and not _looks_like_ip_literal(normalized_hostname)
    )


def _format_normalized_netloc(hostname: str, port: int, *, explicit_port: bool) -> str:
    host_part = f"[{hostname}]" if ":" in hostname else hostname
    if not explicit_port:
        return host_part
    return f"{host_part}:{port}"


def _validate_global_address(address: str, *, hostname: str | None = None) -> str:
    """Validate that an IP address is globally routable, or explicitly allowed.

    When ``ALLOW_LOCAL_LLM_PROVIDERS`` is enabled the address is accepted if:
    - the IP is a loopback address, **or**
    - the *original* hostname (before DNS resolution) is present in
      ``ALLOWED_LLM_BASE_URL_HOSTS``.

    This second condition is necessary because Docker container names (e.g.
    ``ollama``) resolve to RFC-1918 private IPs that would otherwise be
    rejected by the global-address check.
    """
    try:
        ip_address = ipaddress.ip_address(address)
    except ValueError as exc:
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED) from exc

    is_allowed_local = False
    if settings.ALLOW_LOCAL_LLM_PROVIDERS:
        if ip_address.is_loopback:
            is_allowed_local = True
        elif hostname and _is_allowlisted_local_provider_host(hostname):
            is_allowed_local = True

    if not is_allowed_local:
        if (
            ip_address.is_private
            or ip_address.is_loopback
            or ip_address.is_link_local
            or ip_address.is_reserved
            or ip_address.is_unspecified
            or ip_address.is_multicast
            or not ip_address.is_global
        ):
            raise ValueError(LLM_BASE_URL_NOT_ALLOWED)
    return str(ip_address)


def _resolve_all_global_addresses(hostname: str, port: int) -> tuple[str, ...]:
    try:
        address_infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED) from exc

    if not address_infos:
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED)
    addresses: list[str] = []
    seen_addresses: set[str] = set()
    for address_info in address_infos:
        # Pass the original hostname so that Docker container names listed in
        # ALLOWED_LLM_BASE_URL_HOSTS are matched before checking the resolved IP.
        address = _validate_global_address(str(address_info[4][0]), hostname=hostname)
        if address not in seen_addresses:
            seen_addresses.add(address)
            addresses.append(address)
    return tuple(addresses)


async def _resolve_all_global_addresses_async(
    hostname: str, port: int
) -> tuple[str, ...]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_resolve_all_global_addresses, hostname, port),
            timeout=_DNS_RESOLUTION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED) from exc


def _parse_and_validate_candidate_url(
    value: str | None,
) -> tuple[SplitResult | None, int | None]:
    if value is None:
        return None, None

    candidate = value.strip()
    if not candidate:
        return None, None

    if "\\" in candidate or _has_url_control_character(candidate):
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED)

    try:
        parsed = urlsplit(candidate)
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        port = parsed.port or default_port
        return parsed, port
    except ValueError as exc:
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED) from exc


def _validate_url_components(parsed, hostname: str, is_local_dev_host: bool) -> None:
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED)

    if (
        parsed.scheme.lower() == "http"
        and not is_local_dev_host
        and not _is_allowlisted_local_provider_host(hostname)
    ):
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED)

    if (
        not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED)


def _validate_remote_host_is_allowed(hostname: str) -> None:
    allowed_hosts = _parse_allowed_hosts()
    if not allowed_hosts or any("*" in allowed_host for allowed_host in allowed_hosts):
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED)
    if hostname not in allowed_hosts:
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED)
    if _is_ip_literal(hostname) or _looks_like_ip_literal(hostname):
        raise ValueError(LLM_BASE_URL_NOT_ALLOWED)


def _normalize_llm_provider_base_url(value: str | None):
    parsed, port = _parse_and_validate_candidate_url(value)
    if parsed is None or port is None:
        return None, None, None

    hostname = (parsed.hostname or "").lower().rstrip(".")
    # Note: Container names like 'ollama' are NOT treated as localhost unless explicitly intended.
    is_local_dev_host = _is_local_dev_host(hostname)

    _validate_url_components(parsed, hostname, is_local_dev_host)

    # If not localhost, must be in allowed hosts
    if not is_local_dev_host:
        _validate_remote_host_is_allowed(hostname)

    netloc = _format_normalized_netloc(
        hostname, port, explicit_port=parsed.port is not None
    )
    return (
        urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "", "", "")),
        hostname,
        port,
    )


def validate_llm_provider_base_url_details(
    value: str | None,
) -> ValidatedLLMProviderBaseURL | None:
    normalized_url, hostname, port = _normalize_llm_provider_base_url(value)
    if normalized_url is None:
        return None
    addresses = _resolve_all_global_addresses(hostname, port)
    return ValidatedLLMProviderBaseURL(normalized_url, hostname, port, addresses)


def validate_llm_provider_base_url(value: str | None) -> str | None:
    validated = validate_llm_provider_base_url_details(value)
    if validated is None:
        return None
    return validated.normalized_url


async def validate_llm_provider_base_url_details_async(
    value: str | None,
) -> ValidatedLLMProviderBaseURL | None:
    normalized_url, hostname, port = _normalize_llm_provider_base_url(value)
    if normalized_url is None:
        return None
    addresses = await _resolve_all_global_addresses_async(hostname, port)
    return ValidatedLLMProviderBaseURL(normalized_url, hostname, port, addresses)


async def validate_llm_provider_base_url_async(value: str | None) -> str | None:
    validated = await validate_llm_provider_base_url_details_async(value)
    if validated is None:
        return None
    return validated.normalized_url


class _PinnedLLMProviderNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, hostname: str, port: int, addresses: tuple[str, ...]):
        if not addresses:
            raise ValueError(LLM_BASE_URL_NOT_ALLOWED)
        self._hostname = hostname
        self._port = port
        # Re-validate each address; pass the hostname so Docker-container names
        # in ALLOWED_LLM_BASE_URL_HOSTS are accepted.
        self._addresses = tuple(
            _validate_global_address(address, hostname=hostname)
            for address in addresses
        )
        self._backend = AutoBackend()

    async def _connect_validated_ip_address(
        self,
        address: str,
        port: int,
        timeout: float | None,
        local_address: str | None,
        socket_options,
    ):
        pinned_address = _validate_global_address(address, hostname=self._hostname)
        return await self._backend.connect_tcp(
            pinned_address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    def _verify_host_port(self, host: str | bytes, port: int) -> None:
        host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
        normalized_host = host_text.lower().rstrip(".")
        if normalized_host != self._hostname or int(port) != self._port:
            raise OSError("LLM provider base URL host changed after validation")

    async def _cancel_and_wait_tasks(self, tasks: set) -> None:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _wait_for_first_successful_stream(self, tasks: set):
        last_error: Exception | None = None
        while tasks:
            done, tasks_remaining = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            tasks.clear()
            tasks.update(tasks_remaining)

            successful_stream = None
            for task in done:
                try:
                    stream = task.result()
                except Exception as exc:  # pragma: no cover - backend-specific
                    last_error = exc
                    continue

                if successful_stream is None:
                    successful_stream = stream
                else:
                    await stream.aclose()

            if successful_stream is not None:
                return successful_stream, last_error
        return None, last_error

    async def connect_tcp(
        self,
        host: str | bytes,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        self._verify_host_port(host, port)

        tasks = {
            asyncio.create_task(
                self._connect_validated_ip_address(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            )
            for address in self._addresses
        }

        try:
            (
                successful_stream,
                last_error,
            ) = await self._wait_for_first_successful_stream(tasks)
            if successful_stream is not None:
                return successful_stream
        finally:
            await self._cancel_and_wait_tasks(tasks)

        if last_error is not None:
            raise last_error
        raise OSError(LLM_BASE_URL_NOT_ALLOWED)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options=None,
    ):
        raise OSError("LLM provider base URL must not use Unix sockets")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedLLMProviderAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, validated: ValidatedLLMProviderBaseURL):
        self._validated = validated
        ssl_context = create_ssl_context(verify=True, trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=DEFAULT_LIMITS.max_connections,
            max_keepalive_connections=DEFAULT_LIMITS.max_keepalive_connections,
            keepalive_expiry=DEFAULT_LIMITS.keepalive_expiry,
            http1=True,
            http2=False,
            network_backend=_PinnedLLMProviderNetworkBackend(
                validated.hostname,
                validated.port,
                validated.addresses,
            ),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        validated_host = self._validated.hostname.encode("ascii")
        parsed_url = urlsplit(self._validated.normalized_url)
        validated_netloc = parsed_url.netloc.encode("ascii")
        validated_scheme = parsed_url.scheme.encode("ascii")

        safe_headers = []
        for k, v in request.headers.raw:
            if k.lower() == b"host":
                safe_headers.append((b"host", validated_netloc))
            else:
                safe_headers.append((k, v))

        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=validated_scheme,
                host=validated_host,
                port=self._validated.port,
                target=request.url.raw_path,
            ),
            headers=safe_headers,
            content=request.stream,
            extensions=request.extensions,
        )
        with map_httpcore_exceptions():
            resp = await self._pool.handle_async_request(req)

        return httpx.Response(
            status_code=resp.status,
            headers=resp.headers,
            stream=AsyncResponseStream(resp.stream),
            extensions=resp.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


async def build_llm_provider_http_client(
    base_url: str | None,
) -> tuple[str | None, httpx.AsyncClient]:
    validated = await validate_llm_provider_base_url_details_async(base_url)
    if validated is None:
        return None, httpx.AsyncClient(follow_redirects=False, trust_env=False)
    return (
        validated.normalized_url,
        httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
            transport=_PinnedLLMProviderAsyncTransport(validated),
        ),
    )
