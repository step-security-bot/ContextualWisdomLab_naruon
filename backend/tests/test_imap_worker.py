from unittest.mock import AsyncMock, MagicMock

import pytest

from db.models import TenantConfig
from services.imap_worker import ImapSyncWorker


@pytest.mark.asyncio
async def test_imap_worker_skips_disallowed_destination(monkeypatch):
    worker = ImapSyncWorker()
    config = TenantConfig(
        user_id="testuser",
        imap_server="127.0.0.1",
        imap_port=993,
    )
    connection_attempts = []

    def fail_connect(*args, **kwargs):
        connection_attempts.append((args, kwargs))
        raise AssertionError("IMAP connection must not open before policy validation")

    monkeypatch.setattr("services.imap_worker.aioimaplib.IMAP4_SSL", fail_connect)

    await worker._sync_tenant(config)

    assert connection_attempts == []


@pytest.mark.asyncio
async def test_imap_worker_sync_tenant_raises_when_connection_fails(monkeypatch):
    worker = ImapSyncWorker()
    config = TenantConfig(
        user_id="testuser",
        imap_server="imap.example.com",
        imap_port=993,
    )

    imap_client = AsyncMock()
    imap_client.protocol = None
    imap_client.wait_hello_from_server.side_effect = RuntimeError("connect failed")

    monkeypatch.setattr(
        "services.imap_worker.validate_imap_destination",
        lambda host, port: (host, port),
    )
    monkeypatch.setattr(
        "services.imap_worker.aioimaplib.IMAP4_SSL",
        lambda host, port, **kwargs: imap_client,
    )

    with pytest.raises(Exception, match="IMAP Sync failed for user testuser"):
        await worker._sync_tenant(config)


@pytest.mark.asyncio
async def test_imap_worker_imports_fetched_rfc822_messages(monkeypatch):
    worker = ImapSyncWorker()
    config = TenantConfig(
        user_id="imap-user",
        organization_id="org-imap",
        imap_server="imap.example.com",
        imap_port=993,
        imap_username="imap-user@example.com",
        imap_password="imap-secret",
    )
    raw_message = (
        b"Message-ID: <imap-1@example.com>\r\n"
        b"From: Sender <sender@example.com>\r\n"
        b"To: imap-user@example.com\r\n"
        b"Subject: IMAP import\r\n"
        b"Date: Mon, 15 Jun 2026 10:00:00 +0000\r\n"
        b"\r\n"
        b"Imported from IMAP.\r\n"
    )

    imap_client = AsyncMock()
    imap_client.protocol = object()
    imap_client.wait_hello_from_server.return_value = None
    imap_client.login.return_value = ("OK", [b"logged in"])
    imap_client.select.return_value = ("OK", [b"selected"])
    imap_client.search.return_value = ("OK", [b"1"])
    imap_client.fetch.return_value = (
        "OK",
        [(b"1 (RFC822 {%d}" % len(raw_message), raw_message)],
    )
    imap_client.logout.return_value = None

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False

    process_fetched_email_mock = AsyncMock()

    monkeypatch.setattr(
        "services.imap_worker.validate_imap_destination",
        lambda host, port: (host, port),
    )
    monkeypatch.setattr(
        "services.imap_worker.aioimaplib.IMAP4_SSL",
        lambda host, port, **kwargs: imap_client,
    )
    monkeypatch.setattr("services.imap_worker.AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(
        "services.imap_worker.process_fetched_email",
        process_fetched_email_mock,
    )

    imported_count = await worker._sync_tenant(config)

    assert imported_count == 1

    imap_client.login.assert_called_once_with("imap-user@example.com", "imap-secret")
    imap_client.select.assert_called_once_with("INBOX")
    imap_client.search.assert_called_once_with("ALL")
    imap_client.fetch.assert_called_once_with("1", "(RFC822)")
    imap_client.logout.assert_called_once()

    process_fetched_email_mock.assert_called_once()
    args, kwargs = process_fetched_email_mock.call_args
    assert args[0] is session
    assert args[1]["message_id"] == "<imap-1@example.com>"
    assert args[1]["subject"] == "IMAP import"
    assert args[2] == "imap-user"
    assert args[3] == "org-imap"
    assert kwargs["owner_addresses"] == ["imap-user@example.com"]

    session.commit.assert_called_once()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_imap_worker_requires_credentials_without_sensitive_log_names(
    caplog, monkeypatch
):
    worker = ImapSyncWorker()
    config = TenantConfig(
        user_id="imap-user",
        imap_server="imap.example.com",
        imap_port=993,
    )

    imap_client = AsyncMock()
    imap_client.protocol = object()
    imap_client.wait_hello_from_server.return_value = None
    imap_client.logout.return_value = None

    monkeypatch.setattr(
        "services.imap_worker.validate_imap_destination",
        lambda host, port: (host, port),
    )
    monkeypatch.setattr(
        "services.imap_worker.aioimaplib.IMAP4_SSL",
        lambda host, port, **kwargs: imap_client,
    )

    with pytest.raises(Exception, match="IMAP Sync failed for user imap-user"):
        await worker._sync_tenant(config)

    assert "imap_password" not in caplog.text
    assert "password" not in caplog.text.lower()
    assert "imap-secret" not in caplog.text
