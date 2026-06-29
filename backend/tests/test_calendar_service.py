import pytest
from unittest.mock import patch, MagicMock
from services.calendar_service import create_calendar_event
from services.exceptions import CalendarServiceError, UnsafeCalendarTodoError


def _server_owned_google_credentials() -> dict[str, str]:
    return {
        "token": "server-owned-token",
        "refresh_token": "server-owned-refresh-token",
        "client_id": "server-owned-client-id",
        "client_secret": "server-owned-client-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


@pytest.mark.asyncio
async def test_create_calendar_event_unauthorized():
    # Write a test that mocks the build function to simulate an exception
    with patch("services.calendar_service.build") as mock_build:
        mock_build.side_effect = Exception("Invalid credentials")

        with pytest.raises(CalendarServiceError) as exc_info:
            await create_calendar_event("Buy milk", _server_owned_google_credentials())

        assert str(exc_info.value) == "Failed to create event"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_summary",
    ["<script>alert(1)</script>", "`sleep 5`", "bad\x7fsummary", "bad\x85summary"],
)
async def test_create_calendar_event_rejects_unsafe_summary_before_google_build(
    unsafe_summary,
):
    with patch("services.calendar_service.build") as mock_build:
        with pytest.raises(UnsafeCalendarTodoError, match="Unsafe calendar todo text"):
            await create_calendar_event(unsafe_summary, {"token": "dummy"})

        mock_build.assert_not_called()


@pytest.mark.asyncio
async def test_create_calendar_event_rejects_untrusted_oauth_token_uri():
    user_token = _server_owned_google_credentials()
    user_token["token_uri"] = "http://127.0.0.1:8080/token"

    with patch("services.calendar_service.build") as mock_build:
        with pytest.raises(CalendarServiceError, match="Invalid calendar credentials"):
            await create_calendar_event("Buy milk", user_token)

        mock_build.assert_not_called()


@pytest.mark.asyncio
async def test_create_calendar_event_rejects_unexpected_oauth_fields():
    user_token = {"token": "dummy", "token_uri": "https://oauth2.googleapis.com/token"}
    user_token["metadata_url"] = "http://169.254.169.254/latest/meta-data"

    with patch("services.calendar_service.build") as mock_build:
        with pytest.raises(CalendarServiceError, match="Invalid calendar credentials"):
            await create_calendar_event("Buy milk", user_token)

        mock_build.assert_not_called()


@pytest.mark.asyncio
async def test_create_calendar_event_rejects_bearer_token_without_server_oauth_fields():
    user_token = {
        "token": "attacker-forged-access-token",
        "refresh_token": "attacker-refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
    }

    with patch("services.calendar_service.build") as mock_build:
        with pytest.raises(CalendarServiceError, match="Invalid calendar credentials"):
            await create_calendar_event("Buy milk", user_token)

        mock_build.assert_not_called()


@pytest.mark.asyncio
@patch("services.calendar_service.build")
async def test_create_calendar_event_success(mock_build):
    # Mock the calendar service
    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_insert = MagicMock()
    mock_execute = MagicMock()

    # Setup the mock chain
    mock_build.return_value = mock_service
    mock_service.events.return_value = mock_events
    mock_events.insert.return_value = mock_insert
    mock_execute.return_value = {"id": "event_id_123", "summary": "Buy milk"}
    mock_insert.execute = mock_execute

    result = await create_calendar_event("Buy milk", _server_owned_google_credentials())

    assert result == {"id": "event_id_123", "summary": "Buy milk"}
    mock_build.assert_called_once()
    mock_events.insert.assert_called_once()
    args, kwargs = mock_events.insert.call_args
    assert kwargs["calendarId"] == "primary"
    assert kwargs["body"]["summary"] == "Buy milk"
    assert "start" in kwargs["body"]
    assert "end" in kwargs["body"]
