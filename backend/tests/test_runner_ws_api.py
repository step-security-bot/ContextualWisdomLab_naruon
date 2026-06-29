import base64
import asyncio
import hashlib
import hmac
import json
import os
import time

import pytest
from fastapi import WebSocketException, status
from fastapi.routing import APIWebSocketRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from api import runner_ws
from api.auth import AuthContext, get_auth_context
from core.config import settings
from main import app

TEST_SESSION_HMAC_SECRET = os.environ["AUTH_SESSION_HMAC_SECRET"]


class _MockResult:
    def __init__(self, token: str | None):
        self.token = token

    def scalar_one_or_none(self):
        return self.token


class _MockRunnerSession:
    def __init__(self, token: str | None):
        self.token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def execute(self, query):
        return _MockResult(self.token)


class _FailingSendWebSocket:
    headers: dict[str, str]

    def __init__(self):
        authorization = _valid_session_headers()["Authorization"]
        self.headers = {"authorization": authorization}

    async def accept(self):
        return None

    async def receive_text(self):
        return "ping"

    async def send_text(self, text: str):
        raise RuntimeError("simulated runner send failure")


class _AcceptOnlyWebSocket:
    async def accept(self):
        return None


class _DispatchWebSocket:
    def __init__(self):
        self.sent_texts: list[str] = []

    async def accept(self):
        return None

    async def send_text(self, text: str):
        self.sent_texts.append(text)


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _signed_session_token(payload: dict[str, object]) -> str:
    header_segment = _base64url_encode(
        json.dumps(
            {"alg": "HS256", "typ": "JWT"},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    payload_segment = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}"
    signature = hmac.new(
        TEST_SESSION_HMAC_SECRET.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{header_segment}.{payload_segment}.{_base64url_encode(signature)}"


def _valid_session_headers() -> dict[str, str]:
    settings.AUTH_SESSION_HMAC_SECRET = SecretStr(TEST_SESSION_HMAC_SECRET)
    token = _signed_session_token(
        {
            "ver": 1,
            "iss": "naruon-control-plane",
            "aud": "naruon-api",
            "sub": "alice",
            "role": "member",
            "org": "org-acme",
            "groups": ["group-1"],
            "workspace": "workspace-org-acme",
            "exp": int(time.time()) + 300,
        }
    )
    return {"Authorization": f"Bearer {token}"}


def _auth_context() -> AuthContext:
    return AuthContext(
        user_id="alice",
        role="organization_admin",
        organization_id="org-acme",
        group_ids=("group-1",),
        workspace_id="workspace-org-acme",
    )


@pytest.fixture(autouse=True)
def restore_session_secret(monkeypatch):
    previous_secret = settings.AUTH_SESSION_HMAC_SECRET
    runner_ws.manager.reset()

    async def noop_record_connector_signal_event(**kwargs):
        return None

    monkeypatch.setattr(
        runner_ws,
        "record_connector_signal_event",
        noop_record_connector_signal_event,
    )
    yield
    runner_ws.manager.reset()
    settings.AUTH_SESSION_HMAC_SECRET = previous_secret


@pytest.mark.asyncio
async def test_runner_connection_key_validates_registered_token(monkeypatch):
    monkeypatch.setattr(
        runner_ws,
        "AsyncSessionLocal",
        lambda: _MockRunnerSession("nrn_registered-token"),
    )

    connection_key = await runner_ws._runner_connection_key(
        "nrn_registered-token", _auth_context()
    )

    assert connection_key.startswith("org-acme:")
    assert "nrn_registered-token" not in connection_key


@pytest.mark.asyncio
async def test_runner_connection_key_rejects_unknown_token(monkeypatch):
    monkeypatch.setattr(
        runner_ws,
        "AsyncSessionLocal",
        lambda: _MockRunnerSession("nrn_registered-token"),
    )

    with pytest.raises(WebSocketException) as exc:
        await runner_ws._runner_connection_key("nrn_other-token", _auth_context())

    assert exc.value.code == status.WS_1008_POLICY_VIOLATION


def test_runner_ws_rejects_missing_auth():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/runner/nrn_registered-token"):
                pass

    assert exc.value.status_code == 401


def test_runner_ws_route_uses_signed_session_dependency():
    for route in app.routes:
        if isinstance(route, APIWebSocketRoute) and route.path == "/ws/runner/{token}":
            dependencies = {dependency.dependency for dependency in route.dependencies}
            assert get_auth_context in dependencies
            return

    raise AssertionError("Runner WebSocket route is not registered")


def test_runner_ws_accepts_signed_session_and_registered_token(monkeypatch):
    async def registered_key(token: str, auth_context: AuthContext) -> str:
        assert token == "nrn_registered-token"
        assert auth_context.organization_id == "org-acme"
        return "org-acme:registered"

    monkeypatch.setattr(runner_ws, "_runner_connection_key", registered_key)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/runner/nrn_registered-token", headers=_valid_session_headers()
        ) as websocket:
            websocket.send_text("ping")
            assert websocket.receive_text() == "Naruon ack: ping"
            snapshot = runner_ws.manager.snapshot("org-acme", "workspace-org-acme")
            assert snapshot.connection_state == "connected"
            assert snapshot.active_connection_count == 1
            assert snapshot.last_seen_at is not None
            assert snapshot.last_disconnect_at is None
            assert "nrn_registered-token" not in str(runner_ws.manager.connection_records)

    snapshot = runner_ws.manager.snapshot("org-acme", "workspace-org-acme")
    assert snapshot.connection_state == "not_connected"
    assert snapshot.active_connection_count == 0
    assert snapshot.last_disconnect_at is not None


def test_runner_snapshot_keeps_latest_touch_after_connected_at():
    runner_ws.manager.connection_records["org-acme:token-fingerprint"] = (
        runner_ws.RunnerConnectionRecord(
            organization_id="org-acme",
            workspace_id="workspace-org-acme",
            connected_at="2026-05-27T12:00:00Z",
        )
    )
    runner_ws.manager.last_seen_by_org["org-acme"] = "2026-05-27T12:01:00Z"

    snapshot = runner_ws.manager.snapshot("org-acme", "workspace-org-acme")

    assert snapshot.last_seen_at == "2026-05-27T12:01:00Z"


@pytest.mark.asyncio
async def test_runner_manager_records_durable_signal_events(monkeypatch):
    recorded_events: list[dict[str, str]] = []

    async def capture_connector_signal_event(**event):
        recorded_events.append(event)

    monkeypatch.setattr(
        runner_ws,
        "record_connector_signal_event",
        capture_connector_signal_event,
    )

    await runner_ws.manager.connect(
        _AcceptOnlyWebSocket(),
        "org-acme:registered",
        _auth_context(),
    )
    await runner_ws.manager.touch("org-acme:registered")
    await runner_ws.manager.disconnect("org-acme:registered")

    assert [event["state_code"] for event in recorded_events] == [
        "connected",
        "heartbeat",
        "disconnected",
    ]
    assert {event["signal_key"] for event in recorded_events} == {
        "connector_heartbeat"
    }
    assert all(event["organization_id"] == "org-acme" for event in recorded_events)
    assert all(
        event["workspace_id"] == "workspace-org-acme" for event in recorded_events
    )
    assert "nrn_registered-token" not in str(recorded_events)


@pytest.mark.asyncio
async def test_runner_manager_dispatch_waits_for_matching_response(monkeypatch):
    recorded_events: list[dict[str, str]] = []

    async def capture_connector_signal_event(**event):
        recorded_events.append(event)

    monkeypatch.setattr(
        runner_ws,
        "record_connector_signal_event",
        capture_connector_signal_event,
    )
    websocket = _DispatchWebSocket()
    await runner_ws.manager.connect(
        websocket,
        "org-acme:registered",
        _auth_context(),
    )

    dispatch_task = asyncio.create_task(
        runner_ws.manager.dispatch_command(
            "org-acme",
            "workspace-org-acme",
            {
                "action": "write_webdav",
                "account": "webdav-primary",
                "source_id": "webdav_src_1",
            },
            timeout_seconds=1,
        )
    )
    for _ in range(20):
        if websocket.sent_texts:
            break
        await asyncio.sleep(0)

    assert len(websocket.sent_texts) == 1
    sent_payload = json.loads(websocket.sent_texts[0])
    assert sent_payload["action"] == "write_webdav"
    assert sent_payload["account"] == "webdav-primary"
    assert sent_payload["source_id"] == "webdav_src_1"
    assert sent_payload["request_id"].startswith("runner_req_")

    handled = await runner_ws.manager.handle_runner_message(
        "org-acme:registered",
        json.dumps(
            {
                "request_id": sent_payload["request_id"],
                "status": "success",
                "provider_write_executed": True,
                "etag": "etag-after-write",
            }
        ),
    )

    assert handled is True
    assert await dispatch_task == {
        "request_id": sent_payload["request_id"],
        "status": "success",
        "provider_write_executed": True,
        "etag": "etag-after-write",
    }
    assert any(
        event["signal_key"] == "connector_command"
        and event["state_code"] == "dispatched"
        for event in recorded_events
    )


@pytest.mark.asyncio
async def test_runner_manager_records_runner_error_code_response(monkeypatch):
    recorded_events: list[dict[str, str]] = []
    scheduled_retries: list[dict[str, object]] = []

    async def capture_connector_signal_event(**event):
        recorded_events.append(event)

    async def capture_provider_writeback_retry(**retry):
        scheduled_retries.append(retry)
        return "provider_retry_should_not_schedule_adapter_error"

    monkeypatch.setattr(
        runner_ws,
        "record_connector_signal_event",
        capture_connector_signal_event,
    )
    monkeypatch.setattr(
        runner_ws,
        "schedule_provider_writeback_retry_safely",
        capture_provider_writeback_retry,
        raising=False,
    )
    websocket = _DispatchWebSocket()
    await runner_ws.manager.connect(
        websocket,
        "org-acme:registered",
        _auth_context(),
    )

    dispatch_task = asyncio.create_task(
        runner_ws.manager.dispatch_command(
            "org-acme",
            "workspace-org-acme",
            {"action": "write_caldav", "source_id": "caldav_src_1"},
            timeout_seconds=1,
        )
    )
    for _ in range(20):
        if websocket.sent_texts:
            break
        await asyncio.sleep(0)

    sent_payload = json.loads(websocket.sent_texts[0])
    handled = await runner_ws.manager.handle_runner_message(
        "org-acme:registered",
        json.dumps(
            {
                "request_id": sent_payload["request_id"],
                "status": "error",
                "error_code": "adapter_not_configured",
                "provider_write_executed": False,
            }
        ),
    )

    assert handled is True
    assert (await dispatch_task)["error_code"] == "adapter_not_configured"
    assert scheduled_retries == []
    assert any(
        event["signal_key"] == "connector_command"
        and event["state_code"] == "adapter_not_configured"
        and "write_caldav" not in event["detail_text"]
        for event in recorded_events
    )


@pytest.mark.asyncio
async def test_runner_manager_dispatch_fails_closed_without_active_runner(monkeypatch):
    recorded_events: list[dict[str, str]] = []
    scheduled_retries: list[dict[str, object]] = []

    async def capture_connector_signal_event(**event):
        recorded_events.append(event)

    async def capture_provider_writeback_retry(**retry):
        scheduled_retries.append(retry)
        return "provider_retry_no_runner"

    monkeypatch.setattr(
        runner_ws,
        "record_connector_signal_event",
        capture_connector_signal_event,
    )
    monkeypatch.setattr(
        runner_ws,
        "schedule_provider_writeback_retry_safely",
        capture_provider_writeback_retry,
        raising=False,
    )

    result = await runner_ws.manager.dispatch_command(
        "org-acme",
        "workspace-org-acme",
        {"action": "write_webdav"},
        timeout_seconds=1,
    )

    assert result == {
        "status": "error",
        "error": "runner_not_connected",
        "error_code": "runner_not_connected",
        "provider_write_executed": False,
        "retry_item_uid": "provider_retry_no_runner",
    }
    assert scheduled_retries == [
        {
            "organization_id": "org-acme",
            "workspace_id": "workspace-org-acme",
            "command": {"action": "write_webdav"},
            "error_code": "runner_not_connected",
            "runner_request_id": None,
        }
    ]
    assert recorded_events == [
        {
            "organization_id": "org-acme",
            "workspace_id": "workspace-org-acme",
            "signal_key": "connector_command",
            "state_code": "runner_not_connected",
            "detail_text": "runner command dispatch failed",
        }
    ]


@pytest.mark.asyncio
async def test_runner_manager_schedules_retry_when_runner_response_times_out(monkeypatch):
    scheduled_retries: list[dict[str, object]] = []

    async def capture_provider_writeback_retry(**retry):
        scheduled_retries.append(retry)
        return "provider_retry_timeout"

    monkeypatch.setattr(
        runner_ws,
        "schedule_provider_writeback_retry_safely",
        capture_provider_writeback_retry,
        raising=False,
    )
    websocket = _DispatchWebSocket()
    await runner_ws.manager.connect(
        websocket,
        "org-acme:registered",
        _auth_context(),
    )

    result = await runner_ws.manager.dispatch_command(
        "org-acme",
        "workspace-org-acme",
        {"action": "write_caldav", "source_id": "calendar-primary"},
        timeout_seconds=0.001,
    )

    assert result == {
        "status": "error",
        "error": "runner_response_timeout",
        "error_code": "runner_response_timeout",
        "provider_write_executed": False,
        "retry_item_uid": "provider_retry_timeout",
    }
    assert scheduled_retries == [
        {
            "organization_id": "org-acme",
            "workspace_id": "workspace-org-acme",
            "command": {
                "action": "write_caldav",
                "source_id": "calendar-primary",
                "request_id": json.loads(websocket.sent_texts[0])["request_id"],
            },
            "error_code": "runner_response_timeout",
            "runner_request_id": json.loads(websocket.sent_texts[0])["request_id"],
        }
    ]


@pytest.mark.asyncio
async def test_runner_endpoint_disconnects_on_send_errors(monkeypatch):
    async def registered_key(token: str, auth_context: AuthContext) -> str:
        assert token == "nrn_registered-token"
        assert auth_context.organization_id == "org-acme"
        return "org-acme:registered"

    monkeypatch.setattr(runner_ws, "_runner_connection_key", registered_key)

    with pytest.raises(RuntimeError, match="simulated runner send failure"):
        await runner_ws.runner_endpoint(_FailingSendWebSocket(), "nrn_registered-token")

    snapshot = runner_ws.manager.snapshot("org-acme", "workspace-org-acme")
    assert snapshot.connection_state == "not_connected"
    assert snapshot.active_connection_count == 0
    assert snapshot.last_disconnect_at is not None
