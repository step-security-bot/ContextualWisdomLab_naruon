import uuid
from unittest.mock import patch, AsyncMock

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api import calendar as calendar_api
from api.calendar import WritebackSource
from core.config import settings
from db.models import CalendarWritebackSource
from db.session import get_db
from main import app
from services.exceptions import CalendarServiceError

pytestmark = pytest.mark.usefixtures("dev_auth_dependency_overrides")

client = TestClient(app, headers={"X-User-Id": "testuser"})
workspace_client = TestClient(
    app,
    headers={"X-User-Id": "testuser", "X-Organization-Id": "org-acme"},
)


def _server_owned_google_credentials() -> dict[str, str]:
    return {
        "token": "server-owned-token",
        "refresh_token": "server-owned-refresh-token",
        "client_id": "server-owned-client-id",
        "client_secret": "server-owned-client-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


@pytest.fixture
def writeback_source_override():
    def apply(sources: list[WritebackSource]) -> None:
        async def source_override() -> tuple[WritebackSource, ...]:
            return tuple(sources)

        app.dependency_overrides[calendar_api.get_writeback_sources] = source_override

    yield apply
    if hasattr(calendar_api, "get_writeback_sources"):
        app.dependency_overrides.pop(calendar_api.get_writeback_sources, None)


@pytest.fixture
def calendar_user_token_override():
    def apply(token: dict[str, str]) -> None:
        async def token_override() -> dict[str, str]:
            return token

        app.dependency_overrides[calendar_api.get_calendar_user_token] = token_override

    yield apply
    app.dependency_overrides.pop(calendar_api.get_calendar_user_token, None)


class FakeScalarResult:
    def __init__(self, sources: list[CalendarWritebackSource]):
        self._sources = sources

    def all(self) -> list[CalendarWritebackSource]:
        return self._sources


class FakeExecuteResult:
    def __init__(self, sources: list[CalendarWritebackSource]):
        self._sources = sources

    def scalars(self) -> FakeScalarResult:
        return FakeScalarResult(self._sources)


class FakeCalendarRegistrySession:
    def __init__(self, sources: list[CalendarWritebackSource]):
        self.sources = sources
        self.statement_text = ""

    async def execute(self, statement):
        self.statement_text = str(statement)
        return FakeExecuteResult(self.sources)


def _calendar_writeback_source(
    *,
    source_uid: str = "caldav_src_fastmail_primary",
    user_id: str = "testuser",
    organization_id: str | None = "org-acme",
    workspace_id: str = "workspace-org-acme",
    provider_name: str = "Fastmail",
    source_protocol: str = "caldav",
    writeback_enabled: bool = True,
    etag_value: str | None = "etag-caldav-1",
) -> CalendarWritebackSource:
    return CalendarWritebackSource(
        source_uid=source_uid,
        user_id=user_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        account_ref="caldav-account-ref",
        provider_name=provider_name,
        source_protocol=source_protocol,
        source_host="caldav.fastmail.example",
        writeback_enabled=writeback_enabled,
        etag_value=etag_value,
    )


@patch("api.calendar.create_calendar_events_batch", new_callable=AsyncMock)
def test_calendar_sync_endpoint_success(mock_create, calendar_user_token_override):
    # Setup mock
    mock_create.return_value = [{"id": "123", "summary": "Test todo"}]
    user_token = _server_owned_google_credentials()
    calendar_user_token_override(user_token)

    response = client.post(
        "/api/calendar/sync",
        json={"todos": ["Test todo"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "synced": 1,
        "events": [{"id": "123", "summary": "Test todo"}],
    }
    mock_create.assert_called_once_with(["Test todo"], user_token)


@patch("api.calendar.create_calendar_events_batch", new_callable=AsyncMock)
def test_calendar_sync_rejects_client_supplied_user_token(mock_create):
    mock_create.return_value = [{"id": "attacker-event"}]

    response = client.post(
        "/api/calendar/sync",
        json={"todos": ["Test todo"], "user_token": {"token": "attacker"}},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"
    mock_create.assert_not_called()


@patch("api.calendar.create_calendar_events_batch", new_callable=AsyncMock)
def test_calendar_sync_uses_server_authoritative_calendar_credentials(mock_create):
    mock_create.return_value = [{"id": "123", "summary": "Test todo"}]
    user_token = _server_owned_google_credentials()

    async def token_override():
        return user_token

    app.dependency_overrides[calendar_api.get_calendar_user_token] = token_override
    try:
        response = client.post("/api/calendar/sync", json={"todos": ["Test todo"]})
    finally:
        app.dependency_overrides.pop(calendar_api.get_calendar_user_token, None)

    assert response.status_code == 200
    assert response.json() == {
        "synced": 1,
        "events": [{"id": "123", "summary": "Test todo"}],
    }
    mock_create.assert_called_once_with(["Test todo"], user_token)


@patch("api.calendar.create_calendar_events_batch", new_callable=AsyncMock)
def test_calendar_sync_endpoint_error(mock_create, calendar_user_token_override, caplog):
    mock_create.side_effect = CalendarServiceError("Mocked error")
    calendar_user_token_override(_server_owned_google_credentials())

    with caplog.at_level("WARNING", logger="api.calendar"):
        response = client.post(
            "/api/calendar/sync",
            json={"todos": ["Test todo"]},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "An internal server error occurred while communicating with the calendar service"}
    assert "Calendar service error during sync_todos" in caplog.text
    assert "Mocked error" not in caplog.text


@pytest.mark.parametrize(
    "unsafe_todo",
    [
        "<script>alert('xss')</script>",
        "$(sleep 5)",
    ],
)
@patch("api.calendar.create_calendar_events_batch", new_callable=AsyncMock)
def test_calendar_sync_rejects_unsafe_todo_text_before_writeback(
    mock_create,
    calendar_user_token_override,
    unsafe_todo,
):
    calendar_user_token_override(_server_owned_google_credentials())

    response = client.post("/api/calendar/sync", json={"todos": [unsafe_todo]})

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid or unsafe calendar todo text"}
    mock_create.assert_not_called()


@patch("api.calendar.create_calendar_events_batch", new_callable=AsyncMock)
def test_calendar_sync_rejects_mixed_batch_before_any_writeback(
    mock_create,
    calendar_user_token_override,
):
    mock_create.return_value = [{"id": "created-before-rejection"}]
    calendar_user_token_override(_server_owned_google_credentials())

    response = client.post(
        "/api/calendar/sync",
        json={"todos": ["Buy milk", "<script>alert('xss')</script>"]},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid or unsafe calendar todo text"}
    mock_create.assert_not_called()


def test_calendar_writeback_intent_uses_customer_owned_caldav_account(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="naruon-internal-cache",
                provider="naruon",
                protocol="local",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read"],
                writeback_enabled=False,
            ),
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            ),
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={"action": "create", "summary": "Launch review"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "workspace_id": "workspace-org-acme",
        "target_source_id": "calendar-primary",
        "protocol": "caldav",
        "writeback_mode": "customer_owned",
        "requires_if_match": False,
        "if_match": None,
        "provenance": {
            "created_by": "testuser",
            "source_provider": "fastmail",
            "source_protocol": "caldav",
        },
        "audit_event": "calendar.writeback_intent.created",
        "provider_write_executed": False,
        "status": "intent_ready",
        "runner_request_id": None,
        "provider_status": None,
        "error_code": None,
        "retry_item_uid": None,
    }


def test_calendar_writeback_intent_does_not_dispatch_runner_by_default(
    writeback_source_override,
    monkeypatch,
):
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(calendar_api.runner_manager, "dispatch_command", dispatch_mock)
    writeback_source_override(
        [
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            )
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={"action": "update", "summary": "Launch review"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["provider_write_executed"] is False
    assert response.json()["status"] == "intent_ready"
    dispatch_mock.assert_not_called()


def test_calendar_writeback_execute_provider_dispatches_caldav_runner_command(
    writeback_source_override,
    monkeypatch,
):
    dispatch_mock = AsyncMock(
        return_value={
            "status": "success",
            "request_id": "runner_req_calendar_1",
            "provider_write_executed": True,
            "provider_status": 204,
        }
    )
    monkeypatch.setattr(calendar_api.runner_manager, "dispatch_command", dispatch_mock)
    writeback_source_override(
        [
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            )
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "update",
            "summary": "Launch review",
            "target_source_id": "calendar-primary",
            "execute_provider": True,
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    assert data["provider_write_executed"] is True
    assert data["runner_request_id"] == "runner_req_calendar_1"
    assert data["provider_status"] == 204
    assert data["audit_event"] == "calendar.writeback.executed"
    assert data["retry_item_uid"] is None
    dispatch_mock.assert_awaited_once()
    organization_id, workspace_id, command = dispatch_mock.await_args.args
    assert organization_id == "org-acme"
    assert workspace_id == "workspace-org-acme"
    assert command["action"] == "write_caldav"
    assert command["account"] == "calendar-primary"
    assert command["source_id"] == "calendar-primary"
    assert command["if_match"] == "abc123"
    assert command["content_type"] == "text/calendar; charset=utf-8"
    assert command["target_path"].startswith("/Naruon/Calendar/")
    assert command["target_path"].endswith(".ics")
    assert "BEGIN:VCALENDAR" in command["content"]
    assert "SUMMARY:Launch review" in command["content"]


def test_calendar_writeback_execute_provider_returns_retry_item_for_transient_failure(
    writeback_source_override,
    monkeypatch,
):
    dispatch_mock = AsyncMock(
        return_value={
            "status": "error",
            "error_code": "runner_not_connected",
            "provider_write_executed": False,
            "retry_item_uid": "provider_retry_calendar_1",
        }
    )
    monkeypatch.setattr(calendar_api.runner_manager, "dispatch_command", dispatch_mock)
    writeback_source_override(
        [
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            )
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "update",
            "summary": "Launch review",
            "target_source_id": "calendar-primary",
            "execute_provider": True,
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "error"
    assert data["provider_write_executed"] is False
    assert data["error_code"] == "runner_not_connected"
    assert data["retry_item_uid"] == "provider_retry_calendar_1"


def test_calendar_writeback_execute_provider_requires_if_match_before_dispatch(
    writeback_source_override,
    monkeypatch,
):
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(calendar_api.runner_manager, "dispatch_command", dispatch_mock)
    writeback_source_override(
        [
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            )
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "create",
            "summary": "Launch review",
            "target_source_id": "calendar-primary",
            "execute_provider": True,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "If-Match is required before provider write execution"
    }
    dispatch_mock.assert_not_called()


def test_calendar_writeback_sources_endpoint_lists_authoritative_sources(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            )
        ]
    )

    response = workspace_client.get("/api/calendar/writeback-sources")

    assert response.status_code == 200
    assert response.json() == [
        {
            "source_id": "calendar-primary",
            "provider": "fastmail",
            "protocol": "caldav",
            "owner_id": "testuser",
            "organization_id": "org-acme",
            "capabilities": ["read", "write", "etag"],
            "writeback_enabled": True,
            "etag": "abc123",
        }
    ]


def test_calendar_writeback_update_requires_etag_if_match(writeback_source_override):
    writeback_source_override(
        [
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            )
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={"action": "update", "summary": "Launch review"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["requires_if_match"] is True
    assert data["if_match"] == "abc123"


def test_calendar_writeback_rejects_non_owner_and_naruon_only_storage(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="shared-calendar",
                provider="fastmail",
                protocol="caldav",
                owner_id="other-user",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            )
        ]
    )
    non_owner_response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={"action": "create", "summary": "Launch review"},
    )
    assert non_owner_response.status_code == 422

    writeback_source_override(
        [
            WritebackSource(
                source_id="naruon-cache",
                provider="naruon",
                protocol="local",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write"],
                writeback_enabled=True,
            )
        ]
    )

    naruon_only_response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={"action": "create", "summary": "Launch review"},
    )
    assert naruon_only_response.status_code == 422


def test_calendar_writeback_rejects_targeted_non_owned_source_without_selection(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="shared-calendar",
                provider="fastmail",
                protocol="caldav",
                owner_id="other-user",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="shared-etag",
            ),
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="owned-etag",
            ),
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "create",
            "summary": "Launch review",
            "target_source_id": "shared-calendar",
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Not authorized for requested writeback source"
    }


def test_calendar_writeback_targeted_authorization_hides_source_existence(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="shared-calendar",
                provider="fastmail",
                protocol="caldav",
                owner_id="other-user",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="shared-etag",
            ),
            WritebackSource(
                source_id="cross-org-calendar",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-other",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="cross-org-etag",
            )
        ]
    )

    missing_response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "create",
            "summary": "Launch review",
            "target_source_id": "missing-calendar",
        },
    )
    non_owner_response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "create",
            "summary": "Launch review",
            "target_source_id": "shared-calendar",
        },
    )
    cross_org_response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "create",
            "summary": "Launch review",
            "target_source_id": "cross-org-calendar",
        },
    )

    assert missing_response.status_code == 403
    assert non_owner_response.status_code == 403
    assert cross_org_response.status_code == 403
    assert missing_response.json() == non_owner_response.json()
    assert missing_response.json() == cross_org_response.json()


def test_calendar_writeback_rejects_org_admin_cross_user_targeting(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="shared-calendar",
                provider="fastmail",
                protocol="caldav",
                owner_id="other-user",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="shared-etag",
            )
        ]
    )
    org_admin_client = TestClient(
        app,
        headers={
            "X-User-Id": "org-admin",
            "X-User-Role": "tenant_admin",
            "X-Organization-Id": "org-acme",
        },
    )

    response = org_admin_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "create",
            "summary": "Launch review",
            "target_source_id": "shared-calendar",
        },
    )

    assert response.status_code == 403



def test_calendar_writeback_rejects_system_admin_targeting_cross_org_source(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="cross-org-calendar",
                provider="fastmail",
                protocol="caldav",
                owner_id="other-user",
                organization_id="org-other",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="cross-org-etag",
            )
        ]
    )
    system_admin_client = TestClient(
        app,
        headers={"X-User-Id": "platform-ops", "X-User-Role": "system_admin"},
    )

    response = system_admin_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "create",
            "summary": "Launch review",
            "target_source_id": "cross-org-calendar",
        },
    )

    assert response.status_code == 403


def test_calendar_writeback_selects_owned_source_after_non_owned_candidate(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="shared-calendar",
                provider="fastmail",
                protocol="caldav",
                owner_id="other-user",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="shared-etag",
            ),
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="owned-etag",
            ),
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={"action": "create", "summary": "Launch review"},
    )

    assert response.status_code == 200
    assert response.json()["target_source_id"] == "calendar-primary"


def test_calendar_writeback_rejects_forged_client_source_ownership(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-acme",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            )
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={
            "action": "create",
            "summary": "Launch review",
            "sources": [
                {
                    "source_id": "attacker-controlled-calendar",
                    "provider": "fastmail",
                    "protocol": "caldav",
                    "owner_id": "testuser",
                    "capabilities": ["read", "write", "etag"],
                    "writeback_enabled": True,
                    "etag": "abc123",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"
    assert response.json()["detail"][0]["loc"] == ["body", "sources"]


def test_calendar_writeback_rejects_same_owner_cross_org_source(
    writeback_source_override,
):
    writeback_source_override(
        [
            WritebackSource(
                source_id="calendar-primary",
                provider="fastmail",
                protocol="caldav",
                owner_id="testuser",
                organization_id="org-other",
                capabilities=["read", "write", "etag"],
                writeback_enabled=True,
                etag="abc123",
            )
        ]
    )

    response = workspace_client.post(
        "/api/calendar/writeback-intent",
        json={"action": "create", "summary": "Launch review"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "No customer-owned writeback source is available"
    }


def test_calendar_writeback_sources_use_db_backed_caldav_registry():
    fake_session = FakeCalendarRegistrySession(
        [
            _calendar_writeback_source(
                source_uid="caldav_src_fastmail_primary",
                provider_name="Fastmail",
                etag_value="etag-db-42",
            )
        ]
    )

    async def override_db():
        yield fake_session

    app.dependency_overrides[get_db] = override_db
    try:
        response = workspace_client.post(
            "/api/calendar/writeback-intent",
            json={"action": "update", "summary": "Launch review"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target_source_id"] == "caldav_src_fastmail_primary"
    assert body["protocol"] == "caldav"
    assert body["if_match"] == "etag-db-42"
    assert body["provenance"]["source_provider"] == "Fastmail"
    assert "calendar_writeback_sources.organization_id" in fake_session.statement_text
    assert "calendar_writeback_sources.user_id" in fake_session.statement_text
    assert "calendar_writeback_sources.source_protocol" in fake_session.statement_text


def test_calendar_writeback_db_registry_rejects_cross_org_rows():
    fake_session = FakeCalendarRegistrySession(
        [
            _calendar_writeback_source(
                source_uid="caldav_src_rival_primary",
                organization_id="org-rival",
                provider_name="Rival CalDAV",
            )
        ]
    )

    async def override_db():
        yield fake_session

    app.dependency_overrides[get_db] = override_db
    try:
        response = workspace_client.post(
            "/api/calendar/writeback-intent",
            json={"action": "create", "summary": "Launch review"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "No customer-owned writeback source is available"
    }


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_calendar_writeback_intent_real_postgres_smoke():
    source_uid = f"caldav_src_{uuid.uuid4().hex[:24]}"
    user_id = f"caldav-smoke-{uuid.uuid4().hex[:12]}"
    organization_id = "org-caldav-smoke"

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS calendar_writeback_sources (
                        source_uid VARCHAR PRIMARY KEY,
                        user_id VARCHAR NOT NULL,
                        organization_id VARCHAR,
                        workspace_id VARCHAR NOT NULL,
                        account_ref VARCHAR,
                        provider_name VARCHAR NOT NULL,
                        source_protocol VARCHAR NOT NULL,
                        source_host VARCHAR NOT NULL,
                        writeback_enabled BOOLEAN NOT NULL DEFAULT false,
                        etag_value VARCHAR,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    DELETE FROM calendar_writeback_sources
                    WHERE source_uid = :source_uid
                    """
                ),
                {"source_uid": source_uid},
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO calendar_writeback_sources (
                        source_uid,
                        user_id,
                        organization_id,
                        workspace_id,
                        account_ref,
                        provider_name,
                        source_protocol,
                        source_host,
                        writeback_enabled,
                        etag_value
                    )
                    VALUES (
                        :source_uid,
                        :user_id,
                        :organization_id,
                        :workspace_id,
                        :account_ref,
                        :provider_name,
                        :source_protocol,
                        :source_host,
                        :writeback_enabled,
                        :etag_value
                    )
                    """
                ),
                {
                    "source_uid": source_uid,
                    "user_id": user_id,
                    "organization_id": organization_id,
                    "workspace_id": f"workspace-{organization_id}",
                    "account_ref": "caldav-smoke-account",
                    "provider_name": "Smoke CalDAV",
                    "source_protocol": "caldav",
                    "source_host": "caldav-smoke.example",
                    "writeback_enabled": True,
                    "etag_value": "etag-smoke",
                },
            )
    except (
        ConnectionRefusedError,
        OSError,
        OperationalError,
        asyncpg.CannotConnectNowError,
        asyncpg.InvalidAuthorizationSpecificationError,
        asyncpg.InvalidCatalogNameError,
        asyncpg.InvalidPasswordError,
    ):
        await engine.dispose()
        pytest.skip("PostgreSQL smoke path unavailable")
    except Exception:
        await engine.dispose()
        raise

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_real_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_real_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-User-Id": user_id, "X-Organization-Id": organization_id},
        ) as client:
            response = await client.post(
                "/api/calendar/writeback-intent",
                json={"action": "update", "summary": "Smoke update"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM calendar_writeback_sources "
                    "WHERE source_uid = :source_uid"
                ),
                {"source_uid": source_uid},
            )
        await engine.dispose()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target_source_id"] == source_uid
    assert body["protocol"] == "caldav"
    assert body["if_match"] == "etag-smoke"
    assert body["provenance"]["source_provider"] == "Smoke CalDAV"
