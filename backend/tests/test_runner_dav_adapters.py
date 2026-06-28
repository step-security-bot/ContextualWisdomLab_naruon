import socket

import pytest

from runner.local_dav_adapters import LocalDavAdapters, LocalDavSourceConfig


class FakeDavResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeDavClient:
    def __init__(self, response: FakeDavResponse):
        self.response = response
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def put(self, url, *, content, headers, auth):
        self.requests.append(
            {
                "url": url,
                "content": content,
                "headers": headers,
                "auth": auth,
            }
        )
        return self.response


@pytest.fixture(autouse=True)
def stub_dav_dns(monkeypatch):
    def fake_getaddrinfo(host, port, type=socket.SOCK_STREAM):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", port),
            )
        ]

    monkeypatch.setattr(
        "runner.local_dav_adapters.socket.getaddrinfo", fake_getaddrinfo
    )


@pytest.mark.asyncio
async def test_webdav_adapter_puts_content_with_if_match():
    fake_client = FakeDavClient(
        FakeDavResponse(204, headers={"ETag": "etag-after-write"})
    )
    adapters = LocalDavAdapters(
        [
            LocalDavSourceConfig(
                source_id="webdav_src_1",
                protocol="webdav",
                base_url="https://webdav.example.com/remote.php/dav/files/alice",
                username="alice",
                password="dav-secret",
                writeback_enabled=True,
            )
        ],
        http_client_factory=lambda: fake_client,
    )

    result = await adapters.write_webdav(
        {
            "source_id": "webdav_src_1",
            "target_path": "/Naruon/Notes/task.md",
            "content": "# Note\n",
            "content_type": "text/markdown; charset=utf-8",
            "if_match": "etag-before-write",
        }
    )

    assert result == {
        "status": "success",
        "provider_write_executed": True,
        "provider_status": 204,
        "etag": "etag-after-write",
    }
    assert fake_client.requests == [
        {
            "url": "https://webdav.example.com/remote.php/dav/files/alice/Naruon/Notes/task.md",
            "content": b"# Note\n",
            "headers": {
                "Content-Type": "text/markdown; charset=utf-8",
                "If-Match": "etag-before-write",
            },
            "auth": ("alice", "dav-secret"),
        }
    ]


@pytest.mark.asyncio
async def test_webdav_adapter_requires_if_match_before_network_request():
    fake_client = FakeDavClient(FakeDavResponse(204))
    adapters = LocalDavAdapters(
        [
            LocalDavSourceConfig(
                source_id="webdav_src_1",
                protocol="webdav",
                base_url="https://webdav.example.com",
                writeback_enabled=True,
            )
        ],
        http_client_factory=lambda: fake_client,
    )

    result = await adapters.write_webdav(
        {
            "source_id": "webdav_src_1",
            "target_path": "/Naruon/Notes/task.md",
            "content": "# Note\n",
        }
    )

    assert result == {
        "status": "error",
        "error": "missing_if_match",
        "error_code": "missing_if_match",
        "provider_write_executed": False,
    }
    assert fake_client.requests == []


@pytest.mark.asyncio
async def test_webdav_adapter_reports_provider_conflict_without_write_success():
    fake_client = FakeDavClient(FakeDavResponse(412))
    adapters = LocalDavAdapters(
        [
            LocalDavSourceConfig(
                source_id="webdav_src_1",
                protocol="webdav",
                base_url="https://webdav.example.com",
                writeback_enabled=True,
            )
        ],
        http_client_factory=lambda: fake_client,
    )

    result = await adapters.write_webdav(
        {
            "source_id": "webdav_src_1",
            "target_path": "/Naruon/Notes/task.md",
            "content": "# Note\n",
            "if_match": "stale-etag",
        }
    )

    assert result == {
        "status": "conflict",
        "error": "provider_conflict",
        "error_code": "provider_conflict",
        "provider_write_executed": False,
        "provider_status": 412,
    }


@pytest.mark.asyncio
async def test_webdav_adapter_rejects_path_traversal_before_network_request():
    fake_client = FakeDavClient(FakeDavResponse(204))
    adapters = LocalDavAdapters(
        [
            LocalDavSourceConfig(
                source_id="webdav_src_1",
                protocol="webdav",
                base_url="https://webdav.example.com",
                writeback_enabled=True,
            )
        ],
        http_client_factory=lambda: fake_client,
    )

    result = await adapters.write_webdav(
        {
            "source_id": "webdav_src_1",
            "target_path": "/Naruon/../Secrets/task.md",
            "content": "# Note\n",
            "if_match": "etag-before-write",
        }
    )

    assert result == {
        "status": "error",
        "error": "invalid_target_path",
        "error_code": "invalid_target_path",
        "provider_write_executed": False,
    }
    assert fake_client.requests == []


@pytest.mark.asyncio
async def test_webdav_adapter_rejects_private_source_url_before_network_request(
    monkeypatch,
):
    def fake_private_getaddrinfo(host, port, type=socket.SOCK_STREAM):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("192.168.1.10", port),
            )
        ]

    monkeypatch.setattr(
        "runner.local_dav_adapters.socket.getaddrinfo",
        fake_private_getaddrinfo,
    )
    fake_client = FakeDavClient(FakeDavResponse(204))
    adapters = LocalDavAdapters(
        [
            LocalDavSourceConfig(
                source_id="webdav_src_1",
                protocol="webdav",
                base_url="https://webdav.example.com",
                writeback_enabled=True,
            )
        ],
        http_client_factory=lambda: fake_client,
    )

    result = await adapters.write_webdav(
        {
            "source_id": "webdav_src_1",
            "target_path": "/Naruon/Notes/task.md",
            "content": "# Note\n",
            "if_match": "etag-before-write",
        }
    )

    assert result == {
        "status": "error",
        "error": "invalid_source_url",
        "error_code": "invalid_source_url",
        "provider_write_executed": False,
    }
    assert fake_client.requests == []


@pytest.mark.asyncio
async def test_caldav_adapter_puts_icalendar_content_with_if_match():
    fake_client = FakeDavClient(FakeDavResponse(201, headers={"ETag": "caldav-etag"}))
    adapters = LocalDavAdapters(
        [
            LocalDavSourceConfig(
                source_id="caldav_src_1",
                protocol="caldav",
                base_url="https://calendar.example.com/dav/calendars/alice/tasks",
                writeback_enabled=True,
            )
        ],
        http_client_factory=lambda: fake_client,
    )

    result = await adapters.write_caldav(
        {
            "source_id": "caldav_src_1",
            "target_path": "/naruon-task.ics",
            "content": "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            "if_match": "caldav-before",
        }
    )

    assert result == {
        "status": "success",
        "provider_write_executed": True,
        "provider_status": 201,
        "etag": "caldav-etag",
    }
    assert fake_client.requests[0]["url"] == (
        "https://calendar.example.com/dav/calendars/alice/tasks/naruon-task.ics"
    )
    assert fake_client.requests[0]["headers"] == {
        "Content-Type": "text/calendar; charset=utf-8",
        "If-Match": "caldav-before",
    }


@pytest.mark.asyncio
async def test_webdav_adapter_rejects_unresolvable_source_url_before_network_request(
    monkeypatch,
):
    def fake_unresolvable_getaddrinfo(host, port, type=socket.SOCK_STREAM):
        raise OSError("Name or service not known")

    monkeypatch.setattr(
        "runner.local_dav_adapters.socket.getaddrinfo",
        fake_unresolvable_getaddrinfo,
    )
    fake_client = FakeDavClient(FakeDavResponse(204))
    adapters = LocalDavAdapters(
        [
            LocalDavSourceConfig(
                source_id="webdav_src_1",
                protocol="webdav",
                base_url="https://webdav.example.com",
                writeback_enabled=True,
            )
        ],
        http_client_factory=lambda: fake_client,
    )

    result = await adapters.write_webdav(
        {
            "source_id": "webdav_src_1",
            "target_path": "/Naruon/Notes/task.md",
            "content": "# Note\n",
            "if_match": "etag-before-write",
        }
    )

    assert result == {
        "status": "error",
        "error": "invalid_source_url",
        "error_code": "invalid_source_url",
        "provider_write_executed": False,
    }
    assert fake_client.requests == []


@pytest.mark.asyncio
async def test_webdav_adapter_rejects_invalid_port_before_dns_lookup(monkeypatch):
    def fail_getaddrinfo(host, port, type=socket.SOCK_STREAM):
        raise AssertionError("invalid port URL should fail before DNS lookup")

    monkeypatch.setattr(
        "runner.local_dav_adapters.socket.getaddrinfo",
        fail_getaddrinfo,
    )
    fake_client = FakeDavClient(FakeDavResponse(204))
    adapters = LocalDavAdapters(
        [
            LocalDavSourceConfig(
                source_id="webdav_src_1",
                protocol="webdav",
                base_url="https://webdav.example.com:abc",
                writeback_enabled=True,
            )
        ],
        http_client_factory=lambda: fake_client,
    )

    result = await adapters.write_webdav(
        {
            "source_id": "webdav_src_1",
            "target_path": "/Naruon/Notes/task.md",
            "content": "# Note\n",
            "if_match": "etag-before-write",
        }
    )

    assert result == {
        "status": "error",
        "error": "invalid_source_url",
        "error_code": "invalid_source_url",
        "provider_write_executed": False,
    }
    assert fake_client.requests == []
