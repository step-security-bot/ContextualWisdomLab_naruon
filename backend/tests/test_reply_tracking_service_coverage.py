import pytest

from services.reply_tracking_service import (
    _parse_multiple_addresses,
    message_is_from_user,
)


def test_parse_multiple_addresses_empty():
    assert _parse_multiple_addresses("") == frozenset()
    assert _parse_multiple_addresses(None) == frozenset()


def test_message_is_from_user_empty():
    class DummyEmail:
        sender = "test@example.com"
        recipients = ""

    assert message_is_from_user(DummyEmail(), set()) is False


import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from db.models import Email, TenantConfig
from services.reply_tracking_service import (
    check_missing_replies,
    configured_email_addresses,
)


def test_configured_email_addresses():
    assert configured_email_addresses(None) == set()

    class DummyConfig:
        smtp_username = "test@example.com"
        imap_username = "Other <test2@example.com>"

    addresses = configured_email_addresses(DummyConfig())
    assert "test@example.com" in addresses
    assert "test2@example.com" in addresses


@pytest.mark.asyncio
async def test_check_missing_replies_no_config():
    session = AsyncMock()
    # Mock get_scoped_tenant_config to return None
    import services.reply_tracking_service as sut

    sut.get_scoped_tenant_config = AsyncMock(return_value=None)

    result = await check_missing_replies(session, "user1", "org1")
    assert result == []


@pytest.mark.asyncio
async def test_check_missing_replies_with_config():
    session = AsyncMock()

    class DummyConfig:
        smtp_username = "user@example.com"
        imap_username = None

    import services.reply_tracking_service as sut

    sut.get_scoped_tenant_config = AsyncMock(return_value=DummyConfig())

    mock_result = MagicMock()

    class DummyEmail:
        def __init__(self, msg_id, thread_id, date, sender, recipients, body):
            self.message_id = msg_id
            self.thread_id = thread_id
            self.date = date
            self.sender = sender
            self.recipients = recipients
            self.body = body

    now = datetime.datetime.now(datetime.timezone.utc)
    email1 = DummyEmail(
        "msg1", "thread1", now, "user@example.com", "other@example.com", "please reply"
    )

    mock_result.scalars.return_value.all.return_value = [email1]
    session.execute.return_value = mock_result

    result = await check_missing_replies(session, "user1", "org1")
    assert len(result) == 1
    assert result[0].message_id == "msg1"
