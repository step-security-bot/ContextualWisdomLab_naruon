import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
import uuid

import asyncpg
from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api import runner_ws
from api.auth import AuthContext, get_auth_context, get_current_user
from core.config import settings
from db.models import (
    ConnectorSignalEvent,
    ProviderWritebackRetryItem,
    WorkspaceRunnerConfig,
)
from db.session import get_db
from main import app

pytestmark = pytest.mark.usefixtures("dev_auth_dependency_overrides")
TEST_SESSION_HMAC_SECRET = "observability-hmac-material-32-bytes"  # noqa: S105


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _signed_session_token(payload: dict[str, object]) -> str:
    header_segment = _base64url_encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload_segment = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    )
    signing_input = f"{header_segment}.{payload_segment}"
    signature = hmac.new(
        TEST_SESSION_HMAC_SECRET.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_base64url_encode(signature)}"


def _valid_session_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "ver": 1,
        "iss": "naruon-control-plane",
        "aud": "naruon-api",
        "sub": "admin",
        "role": "member",
        "org": "org-acme",
        "groups": ["group-observability"],
        "workspace": "workspace-org-acme",
        "exp": int(time.time()) + 300,
    }
    payload.update(overrides)
    return payload


class MockResult:
    def __init__(self, obj):
        self.obj = obj

    def scalar_one_or_none(self):
        return self.obj

    def scalars(self):
        return self

    def all(self):
        return self.obj if isinstance(self.obj, list) else []


class MockAsyncSession:
    def __init__(self):
        self.runner = None
        self.events = []
        self.retry_items = []
        self.execute_calls = 0

    async def execute(self, query):
        self.execute_calls += 1
        if self.execute_calls == 1:
            return MockResult(self.runner)
        if self.execute_calls == 2:
            return MockResult(self.events)
        return MockResult(self.retry_items)


@pytest.fixture(autouse=True)
def reset_runner_connections():
    runner_ws.manager.reset()
    yield
    runner_ws.manager.reset()


@pytest.fixture
def mock_db():
    return MockAsyncSession()


@pytest.fixture
def member_client(mock_db):
    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(
            app, headers={"X-User-Id": "member", "X-Organization-Id": "org-acme"}
        ) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def admin_client(mock_db):
    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(
            app,
            headers={
                "X-User-Id": "admin",
                "X-User-Role": "tenant_admin",
                "X-Organization-Id": "org-acme",
            },
        ) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_datetime_to_utc_iso_with_naive_datetime():
    from api.observability import _datetime_to_utc_iso

    dt = datetime(2023, 1, 1, 12, 0, 0)
    iso_str = _datetime_to_utc_iso(dt)
    assert iso_str == "2023-01-01T12:00:00Z"


def test_endpoint_host_without_netloc():
    from api.observability import _endpoint_host

    assert _endpoint_host("invalid-url") is None


def test_member_cannot_read_operational_signals(member_client):
    response = member_client.get("/api/observability/operational-signals")

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "ORG_ADMIN_REQUIRED"


def test_admin_without_org_scope_gets_deterministic_error(mock_db):
    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(
            app,
            headers={
                "X-User-Id": "admin",
                "X-User-Role": "tenant_admin",
            },
        ) as client:
            response = client.get("/api/observability/operational-signals")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "ORG_SCOPE_REQUIRED"


def test_system_admin_without_org_scope_gets_deterministic_error():
    from api.observability import _check_org_admin

    with pytest.raises(HTTPException) as exc_info:
        _check_org_admin(
            AuthContext(
                user_id="admin",
                role="system_admin",
                organization_id=None,
                workspace_id="workspace-admin",
                group_ids=(),
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == "ORG_SCOPE_REQUIRED"


def test_operational_signals_requires_org_id_in_auth_context_explicit(mock_db):
    async def override_get_db():
        yield mock_db

    from api.observability import _check_org_admin

    async def override_check_org_admin():
        # returns an AuthContext with no organization_id
        return AuthContext(
            user_id="admin",
            role="system_admin",
            organization_id=None,
            workspace_id="workspace-admin",
            group_ids=(),
        )

    previous_secret = settings.AUTH_SESSION_HMAC_SECRET
    original_overrides = dict(app.dependency_overrides)
    settings.AUTH_SESSION_HMAC_SECRET = SecretStr(TEST_SESSION_HMAC_SECRET)
    token = _signed_session_token(_valid_session_payload())
    app.dependency_overrides.pop(get_auth_context, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[_check_org_admin] = override_check_org_admin
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/observability/operational-signals",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        settings.AUTH_SESSION_HMAC_SECRET = previous_secret
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "ORG_SCOPE_REQUIRED"


def test_operational_signals_are_truthful_when_unconfigured(admin_client):
    response = admin_client.get("/api/observability/operational-signals")

    assert response.status_code == 200
    data = response.json()
    assert data["workspace_id"] == "workspace-org-acme"
    assert data["audit_event"] == "observability.operational_signals.viewed"
    assert data["telemetry"] == {
        "prometheus_metrics_enabled": False,
        "otel_traces_enabled": False,
        "otel_endpoint_configured": False,
        "otel_endpoint_host": None,
    }
    assert data["connector"]["registration_state"] == "not_registered"
    assert data["connector"]["connection_state"] == "not_connected"
    assert data["connector"]["active_connection_count"] == 0
    assert data["connector"]["last_heartbeat_at"] is None
    assert data["connector"]["recent_events"] == []
    assert data["connector"]["queue_depth_state"] == "clear"
    assert data["connector"]["queue_depth"] == {
        "pending_count": 0,
        "running_count": 0,
        "failed_count": 0,
        "total_count": 0,
        "next_retry_at": None,
    }
    assert data["connector"]["control_plane_domain"] == "naruon.net"
    signals = {signal["signal_key"]: signal for signal in data["signals"]}
    assert signals["prometheus_metrics"]["state"] == "not_configured"
    assert signals["otel_traces"]["state"] == "not_configured"
    assert signals["connector_heartbeat"]["state"] == "not_registered"
    assert signals["sync_lag"]["state"] == "instrumentation_pending"
    assert signals["writeback_conflicts"]["state"] == "intent_only"
    assert all(signal["provider_write_executed"] is False for signal in data["signals"])


def test_operational_signals_reflect_registered_connector_and_otel(
    admin_client, mock_db, monkeypatch
):
    previous_metrics = settings.ENABLE_PROMETHEUS_METRICS
    settings.ENABLE_PROMETHEUS_METRICS = True
    monkeypatch.setenv("ENABLE_OTEL", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    mock_db.runner = WorkspaceRunnerConfig(
        organization_id="org-acme",
        workspace_id="workspace-org-acme",
        registration_token="nrn_registered-token",
    )
    runner_ws.manager.connection_records["org-acme:token-fingerprint"] = (
        runner_ws.RunnerConnectionRecord(
            organization_id="org-acme",
            workspace_id="workspace-org-acme",
            connected_at="2026-05-27T12:00:00Z",
        )
    )
    try:
        response = admin_client.get("/api/observability/operational-signals")
    finally:
        settings.ENABLE_PROMETHEUS_METRICS = previous_metrics

    assert response.status_code == 200
    data = response.json()
    assert data["telemetry"]["prometheus_metrics_enabled"] is True
    assert data["telemetry"]["otel_traces_enabled"] is True
    assert data["telemetry"]["otel_endpoint_host"] == "otel-collector:4317"
    assert data["connector"]["registration_state"] == "registration_configured"
    assert data["connector"]["connection_state"] == "connected"
    assert data["connector"]["active_connection_count"] == 1
    assert data["connector"]["last_heartbeat_at"] == "2026-05-27T12:00:00Z"
    assert "nrn_registered-token" not in str(data)
    signals = {signal["signal_key"]: signal for signal in data["signals"]}
    assert signals["prometheus_metrics"]["state"] == "enabled"
    assert signals["otel_traces"]["state"] == "enabled"
    assert signals["connector_heartbeat"]["state"] == "enabled"


def test_operational_signals_include_durable_connector_history(admin_client, mock_db):
    mock_db.runner = WorkspaceRunnerConfig(
        organization_id="org-acme",
        workspace_id="workspace-org-acme",
        registration_token="nrn_registered-token",
    )
    mock_db.events = [
        ConnectorSignalEvent(
            event_uid="connector_evt_other_signal",
            organization_id="org-acme",
            workspace_id="workspace-org-acme",
            signal_key="sync_lag",
            state_code="heartbeat",
            detail_text="non-heartbeat signal must not backfill heartbeat time",
            observed_at=datetime(2026, 5, 27, 12, 3, tzinfo=timezone.utc),
        ),
        ConnectorSignalEvent(
            event_uid="connector_evt_disconnect",
            organization_id="org-acme",
            workspace_id="workspace-org-acme",
            signal_key="connector_heartbeat",
            state_code="disconnected",
            detail_text="outbound runner socket disconnected",
            observed_at=datetime(2026, 5, 27, 12, 2, tzinfo=timezone.utc),
        ),
        ConnectorSignalEvent(
            event_uid="connector_evt_heartbeat",
            organization_id="org-acme",
            workspace_id="workspace-org-acme",
            signal_key="connector_heartbeat",
            state_code="heartbeat",
            detail_text="outbound runner heartbeat received",
            observed_at=datetime(2026, 5, 27, 12, 1, tzinfo=timezone.utc),
        ),
    ]

    response = admin_client.get("/api/observability/operational-signals")

    assert response.status_code == 200
    data = response.json()
    assert data["connector"]["connection_state"] == "not_connected"
    assert data["connector"]["registration_state"] == "registration_configured"
    assert data["connector"]["last_heartbeat_at"] == "2026-05-27T12:01:00Z"
    assert data["connector"]["last_disconnect_at"] == "2026-05-27T12:02:00Z"
    assert data["connector"]["recent_events"] == [
        {
            "event_uid": "connector_evt_other_signal",
            "signal_key": "sync_lag",
            "state_code": "heartbeat",
            "detail_text": "non-heartbeat signal must not backfill heartbeat time",
            "observed_at": "2026-05-27T12:03:00Z",
        },
        {
            "event_uid": "connector_evt_disconnect",
            "signal_key": "connector_heartbeat",
            "state_code": "disconnected",
            "detail_text": "outbound runner socket disconnected",
            "observed_at": "2026-05-27T12:02:00Z",
        },
        {
            "event_uid": "connector_evt_heartbeat",
            "signal_key": "connector_heartbeat",
            "state_code": "heartbeat",
            "detail_text": "outbound runner heartbeat received",
            "observed_at": "2026-05-27T12:01:00Z",
        },
    ]


def test_operational_signals_include_writeback_retry_queue_depth(admin_client, mock_db):
    mock_db.runner = WorkspaceRunnerConfig(
        organization_id="org-acme",
        workspace_id="workspace-org-acme",
        registration_token="nrn_registered-token",
    )
    mock_db.retry_items = [
        ProviderWritebackRetryItem(
            retry_item_uid="provider_retry_pending",
            organization_id="org-acme",
            workspace_id="workspace-org-acme",
            source_uid="webdav_src_primary",
            command_action="write_webdav",
            command_payload_encrypted="{}",
            retry_state="pending",
            last_error_code="runner_not_connected",
            runner_request_uid="runner_req_pending",
            attempt_count=1,
            next_retry_at=datetime(2026, 6, 15, 12, 5, tzinfo=timezone.utc),
            created_at=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
        ),
        ProviderWritebackRetryItem(
            retry_item_uid="provider_retry_running",
            organization_id="org-acme",
            workspace_id="workspace-org-acme",
            source_uid="calendar-primary",
            command_action="write_caldav",
            command_payload_encrypted="{}",
            retry_state="running",
            last_error_code="runner_response_timeout",
            runner_request_uid="runner_req_running",
            attempt_count=2,
            next_retry_at=datetime(2026, 6, 15, 12, 6, tzinfo=timezone.utc),
            created_at=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 15, 12, 1, tzinfo=timezone.utc),
        ),
        ProviderWritebackRetryItem(
            retry_item_uid="provider_retry_failed",
            organization_id="org-acme",
            workspace_id="workspace-org-acme",
            source_uid="calendar-primary",
            command_action="write_caldav",
            command_payload_encrypted="{}",
            retry_state="failed_exhausted",
            last_error_code="retry_attempts_exhausted",
            runner_request_uid="runner_req_failed",
            attempt_count=3,
            next_retry_at=datetime(2026, 6, 15, 12, 7, tzinfo=timezone.utc),
            created_at=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 15, 12, 2, tzinfo=timezone.utc),
        ),
    ]

    response = admin_client.get("/api/observability/operational-signals")

    assert response.status_code == 200
    data = response.json()
    assert data["connector"]["queue_depth_state"] == "degraded"
    assert data["connector"]["queue_depth"] == {
        "pending_count": 1,
        "running_count": 1,
        "failed_count": 1,
        "total_count": 3,
        "next_retry_at": "2026-06-15T12:05:00Z",
    }
    signals = {signal["signal_key"]: signal for signal in data["signals"]}
    assert signals["writeback_retry_queue"]["state"] == "enabled"
    assert signals["writeback_retry_queue"]["evidence_source"] == (
        "provider_writeback_retry_items"
    )
    assert "3 queued" in signals["writeback_retry_queue"]["detail"]


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_operational_signals_real_postgres_connector_history_smoke():
    smoke_uid = uuid.uuid4().hex[:16]
    event_uid = f"connector_evt_pg_{smoke_uid}"
    organization_id = f"org-pg-smoke-{smoke_uid}"
    workspace_id = f"workspace-{organization_id}"
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_runner_configs (
                        id SERIAL PRIMARY KEY,
                        organization_id VARCHAR UNIQUE,
                        workspace_id VARCHAR UNIQUE,
                        registration_token VARCHAR,
                        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS connector_signal_events (
                        event_uid VARCHAR PRIMARY KEY,
                        organization_id VARCHAR NOT NULL,
                        workspace_id VARCHAR NOT NULL,
                        signal_key VARCHAR NOT NULL,
                        state_code VARCHAR NOT NULL,
                        detail_text TEXT,
                        observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM connector_signal_events "
                    "WHERE organization_id = :organization_id "
                    "AND workspace_id = :workspace_id"
                ),
                {
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                },
            )
            await conn.execute(
                text(
                    "DELETE FROM workspace_runner_configs "
                    "WHERE organization_id = :organization_id "
                    "OR workspace_id = :workspace_id"
                ),
                {
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO connector_signal_events (
                        event_uid,
                        organization_id,
                        workspace_id,
                        signal_key,
                        state_code,
                        detail_text,
                        observed_at
                    )
                    VALUES (
                        :event_uid,
                        :organization_id,
                        :workspace_id,
                        'connector_heartbeat',
                        'heartbeat',
                        'outbound runner heartbeat received',
                        '2026-05-27T12:03:00Z'
                    )
                    """
                ),
                {
                    "event_uid": event_uid,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
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
            headers={
                "X-User-Id": "admin",
                "X-User-Role": "tenant_admin",
                "X-Organization-Id": organization_id,
            },
        ) as client:
            response = await client.get("/api/observability/operational-signals")
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM connector_signal_events "
                    "WHERE organization_id = :organization_id "
                    "AND workspace_id = :workspace_id"
                ),
                {
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                },
            )
            await conn.execute(
                text(
                    "DELETE FROM workspace_runner_configs "
                    "WHERE organization_id = :organization_id "
                    "OR workspace_id = :workspace_id"
                ),
                {
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                },
            )
        await engine.dispose()

    assert response.status_code == 200
    data = response.json()
    assert data["connector"]["last_heartbeat_at"] == "2026-05-27T12:03:00Z"
    assert data["connector"]["recent_events"][0]["event_uid"] == event_uid
    assert "nrn_registered-token" not in str(data)
