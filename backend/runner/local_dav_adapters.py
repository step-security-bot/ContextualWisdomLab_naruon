import ipaddress
import socket
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal
from urllib.parse import quote, urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class LocalDavSourceConfig:
    source_id: str
    protocol: Literal["caldav", "webdav"]
    base_url: str
    username: str | None = None
    password: str | None = None
    writeback_enabled: bool = False


class LocalDavAdapters:
    def __init__(
        self,
        sources: Iterable[LocalDavSourceConfig],
        *,
        http_client_factory: Callable[[], Any] | None = None,
    ):
        self._sources = {
            source.source_id.strip(): source
            for source in sources
            if source.source_id.strip()
        }
        self._http_client_factory = http_client_factory or self._default_http_client

    async def write_webdav(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._put(
            payload,
            protocol="webdav",
            default_content_type="application/octet-stream",
        )

    async def write_caldav(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._put(
            payload,
            protocol="caldav",
            default_content_type="text/calendar; charset=utf-8",
        )

    def _default_http_client(self):
        return httpx.AsyncClient(follow_redirects=False, timeout=60)

    async def _put(
        self,
        payload: dict[str, Any],
        *,
        protocol: Literal["caldav", "webdav"],
        default_content_type: str,
    ) -> dict[str, Any]:
        source = self._source_for_payload(payload, protocol)
        if source is None:
            return self._error("source_not_configured")
        if not source.writeback_enabled:
            return self._error("source_writeback_disabled")

        if_match = self._payload_text(payload, "if_match")
        if if_match is None:
            return self._error("missing_if_match")

        target_path = self._safe_target_path(payload.get("target_path"))
        if target_path is None:
            return self._error("invalid_target_path")

        content = self._payload_content(payload.get("content"))
        if content is None:
            return self._error("invalid_payload")

        try:
            target_url = self._target_url(source.base_url, target_path)
        except ValueError as exc:
            return self._error(str(exc))

        content_type = self._payload_text(payload, "content_type") or default_content_type
        headers = {"Content-Type": content_type, "If-Match": if_match}
        auth = (
            (source.username, source.password or "")
            if source.username is not None
            else None
        )

        try:
            async with self._http_client_factory() as client:
                response = await client.put(
                    target_url,
                    content=content,
                    headers=headers,
                    auth=auth,
                )
        except httpx.HTTPError:
            return self._error("provider_request_failed")

        return self._result_from_response(response)

    def _source_for_payload(
        self,
        payload: dict[str, Any],
        protocol: Literal["caldav", "webdav"],
    ) -> LocalDavSourceConfig | None:
        source_id = self._payload_text(payload, "source_id")
        if source_id is None:
            return None
        source = self._sources.get(source_id)
        if source is None or source.protocol != protocol:
            return None
        return source

    def _payload_text(self, payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    def _payload_content(self, value: Any) -> bytes | None:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        return None

    def _safe_target_path(self, raw_path: Any) -> str | None:
        if not isinstance(raw_path, str):
            return None
        if not raw_path.startswith("/") or "\\" in raw_path or "://" in raw_path:
            return None
        segments = [segment for segment in raw_path.split("/") if segment]
        if not segments or any(segment in {".", ".."} for segment in segments):
            return None
        return "/" + "/".join(quote(segment, safe="@:$&'()*+,;=-._~") for segment in segments)

    def _target_url(self, base_url: str, target_path: str) -> str:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid_source_url")
        try:
            source_port = parsed.port or 443
        except ValueError as exc:
            raise ValueError("invalid_source_url") from exc
        self._validate_global_source_host(parsed.hostname, source_port)
        base_path = parsed.path.rstrip("/")
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                f"{base_path}{target_path}",
                "",
                "",
            )
        )

    def _validate_global_source_host(self, hostname: str, port: int) -> None:
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            self._validate_global_address(hostname)
            return

        try:
            address_infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError("invalid_source_url") from exc
        addresses = {str(address_info[4][0]) for address_info in address_infos}
        if not addresses:
            raise ValueError("invalid_source_url")
        for address in addresses:
            self._validate_global_address(address)

    @staticmethod
    def _validate_global_address(address: str) -> None:
        try:
            ip_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("invalid_source_url") from exc
        if not ip_address.is_global:
            raise ValueError("invalid_source_url")

    def _result_from_response(self, response) -> dict[str, Any]:
        status_code = int(response.status_code)
        if status_code in {200, 201, 204}:
            result: dict[str, Any] = {
                "status": "success",
                "provider_write_executed": True,
                "provider_status": status_code,
            }
            etag = response.headers.get("ETag") or response.headers.get("etag")
            if etag:
                result["etag"] = etag
            return result
        if status_code in {409, 412}:
            return {
                "status": "conflict",
                "error": "provider_conflict",
                "error_code": "provider_conflict",
                "provider_write_executed": False,
                "provider_status": status_code,
            }
        result = self._error("provider_write_failed")
        result["provider_status"] = status_code
        return result

    def _error(self, error_code: str) -> dict[str, Any]:
        return {
            "status": "error",
            "error": error_code,
            "error_code": error_code,
            "provider_write_executed": False,
        }
