import pytest
from unittest.mock import patch, MagicMock
from services.calendar_service import create_calendar_event, create_calendar_events_batch
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


class _FakeCalendarBatch:
    def __init__(self, callback, missing_response_ids: set[str] | None = None):
        self.callback = callback
        self.missing_response_ids = missing_response_ids or set()
        self.requests: list[tuple[object, str]] = []
        self.execute_count = 0

    def add(self, request, request_id: str):
        self.requests.append((request, request_id))

    def execute(self):
        self.execute_count += 1
        for request, request_id in self.requests:
            response = None
            if request_id not in self.missing_response_ids:
                response = {
                    "id": f"event-{request_id}",
                    "summary": request["body"]["summary"],
                }
            self.callback(request_id, response, None)


class _FakeCalendarService:
    def __init__(self, missing_response_ids: set[str] | None = None):
        self.batches: list[_FakeCalendarBatch] = []
        self.insert_calls: list[dict] = []
        self.missing_response_ids = missing_response_ids or set()

    def events(self):
        return self

    def insert(self, *, calendarId: str, body: dict):
        self.insert_calls.append({"calendarId": calendarId, "body": body})
        return {"calendarId": calendarId, "body": body}

    def new_batch_http_request(self, *, callback):
        batch = _FakeCalendarBatch(callback, self.missing_response_ids)
        self.batches.append(batch)
        return batch


@pytest.mark.asyncio
@patch("services.calendar_service.build")
async def test_create_calendar_events_batch_success(mock_build):
    fake_service = _FakeCalendarService()
    mock_build.return_value = fake_service

    result = await create_calendar_events_batch(
        [" Buy milk ", "Call Alice"],
        _server_owned_google_credentials(),
    )

    assert result == [
        {"id": "event-0", "summary": "Buy milk"},
        {"id": "event-1", "summary": "Call Alice"},
    ]
    assert len(fake_service.batches) == 1
    assert [call["body"]["summary"] for call in fake_service.insert_calls] == [
        "Buy milk",
        "Call Alice",
    ]


@pytest.mark.asyncio
@patch("services.calendar_service.build")
async def test_create_calendar_events_batch_chunks_large_batches(
    mock_build,
    monkeypatch,
):
    fake_service = _FakeCalendarService()
    mock_build.return_value = fake_service
    monkeypatch.setattr(
        "services.calendar_service.GOOGLE_CALENDAR_BATCH_MAX_REQUESTS",
        2,
    )

    result = await create_calendar_events_batch(
        ["One", "Two", "Three"],
        _server_owned_google_credentials(),
    )

    assert [event["summary"] for event in result] == ["One", "Two", "Three"]
    assert [len(batch.requests) for batch in fake_service.batches] == [2, 1]
    assert [batch.execute_count for batch in fake_service.batches] == [1, 1]


@pytest.mark.asyncio
async def test_create_calendar_events_batch_rejects_unsafe_summary_before_google_build():
    with patch("services.calendar_service.build") as mock_build:
        with pytest.raises(UnsafeCalendarTodoError, match="Unsafe calendar todo text"):
            await create_calendar_events_batch(
                ["Buy milk", "<script>alert(1)</script>"],
                _server_owned_google_credentials(),
            )

        mock_build.assert_not_called()


@pytest.mark.asyncio
@patch("services.calendar_service.build")
async def test_create_calendar_events_batch_rejects_missing_callback_response(
    mock_build,
):
    mock_build.return_value = _FakeCalendarService(missing_response_ids={"1"})

    with pytest.raises(CalendarServiceError, match="Failed to create event in batch"):
        await create_calendar_events_batch(
            ["Buy milk", "Call Alice"],
            _server_owned_google_credentials(),
        )
