import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_webdav_source_label_uses_opaque_source_id():
    from services.webdav_service import safe_webdav_source_label

    assert (
        safe_webdav_source_label("webdav_src_primary")
        == "WebDAV source webdav_src_primary"
    )
    assert safe_webdav_source_label(None) == "WebDAV source"


@pytest.mark.asyncio
async def test_caldav_event_parsing_and_sync():
    from services.caldav_service import sync_caldav_accounts
    
    session_mock = AsyncMock()
    # Mock finding accounts
    account_mock = MagicMock()
    account_mock.id = 1
    account_mock.server_url = "https://alice:secret@caldav.example.com/calendars"
    account_mock.username = "user"
    account_mock.credentials_encrypted = "pass"
    
    execute_res = MagicMock()
    execute_res.scalars.return_value.all.return_value = [account_mock]
    session_mock.execute.return_value = execute_res
    
    with patch("services.caldav_service.logger") as logger_mock:
        await sync_caldav_accounts(session_mock, "user_1")
        # Should have logged parsing
        assert logger_mock.info.called
        logged_url = logger_mock.debug.call_args.args[2]
        assert logged_url == "https://caldav.example.com/calendars"
        assert "secret" not in logged_url

@pytest.mark.asyncio
async def test_webdav_file_listing_and_sync():
    from services.webdav_service import sync_webdav_folders
    
    session_mock = AsyncMock()
    account_mock = MagicMock()
    account_mock.source_uid = "webdav_src_primary"
    account_mock.server_url = "https://webdav.example.com"
    
    execute_res = MagicMock()
    execute_res.scalars.return_value.all.return_value = [account_mock]
    session_mock.execute.return_value = execute_res
    
    with patch("services.webdav_service.logger") as logger_mock:
        await sync_webdav_folders(session_mock, "user_1", "org_1")
        logger_mock.info.assert_any_call(
            "Fetched folder structures for WebDAV source %s",
            "webdav_src_primary",
        )
        logged_args = " ".join(
            str(arg)
            for call in logger_mock.info.call_args_list
            for arg in call.args
        )
        assert "https://webdav.example.com" not in logged_args

    statement_text = str(session_mock.execute.call_args.args[0])
    assert "webdav_accounts.user_id" in statement_text
    assert "webdav_accounts.organization_id" in statement_text


@pytest.mark.asyncio
async def test_webdav_sync_skips_hostless_https_url():
    from services.webdav_service import sync_webdav_folders

    session_mock = AsyncMock()
    account_mock = MagicMock()
    account_mock.source_uid = "webdav_src_primary"
    account_mock.server_url = "https:///missing-host"

    execute_res = MagicMock()
    execute_res.scalars.return_value.all.return_value = [account_mock]
    session_mock.execute.return_value = execute_res

    with patch("services.webdav_service.logger") as logger_mock:
        await sync_webdav_folders(session_mock, "user_1", "org_1")

        logger_mock.warning.assert_called_once()
        success_calls = [
            call.args
            for call in logger_mock.info.call_args_list
            if call.args[:1]
            == ("Fetched folder structures for WebDAV source %s",)
        ]
        assert success_calls == []

    statement_text = str(session_mock.execute.call_args.args[0])
    assert "webdav_accounts.user_id" in statement_text
    assert "webdav_accounts.organization_id" in statement_text
