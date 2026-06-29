import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import (
    APIRouter,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from api.auth import AuthContext, build_auth_context
from db.models import ConnectorSignalEvent, WorkspaceRunnerConfig
from db.session import AsyncSessionLocal
from services.provider_writeback_retry_service import (
    is_retryable_provider_writeback_failure,
    schedule_provider_writeback_retry_safely,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["runner"])


@dataclass(frozen=True)
class RunnerConnectionRecord:
    organization_id: str
    workspace_id: str
    connected_at: str


@dataclass(frozen=True)
class RunnerConnectionSnapshot:
    organization_id: str
    workspace_id: str
    connection_state: str
    active_connection_count: int
    last_seen_at: str | None
    last_disconnect_at: str | None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.connection_records: dict[str, RunnerConnectionRecord] = {}
        self.last_seen_by_org: dict[str, str] = {}
        self.last_disconnect_by_org: dict[str, str] = {}
        self.pending_responses: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def connect(
        self,
        ws: WebSocket,
        connection_key: str,
        auth_context: AuthContext,
    ):
        await ws.accept()
        organization_id = auth_context.organization_id
        if not organization_id:
            raise _policy_violation()
        now = _utc_now_iso()
        self.active_connections[connection_key] = ws
        self.connection_records[connection_key] = RunnerConnectionRecord(
            organization_id=organization_id,
            workspace_id=auth_context.workspace_id,
            connected_at=now,
        )
        self.last_seen_by_org[organization_id] = now
        logger.info(
            "Runner connected for organization %s workspace %s",
            organization_id,
            auth_context.workspace_id,
        )
        await _record_connector_signal_event_safely(
            organization_id=organization_id,
            workspace_id=auth_context.workspace_id,
            signal_key="connector_heartbeat",
            state_code="connected",
            detail_text="outbound runner socket connected",
        )

    async def disconnect(self, connection_key: str):
        record = self.connection_records.pop(connection_key, None)
        if connection_key in self.active_connections:
            del self.active_connections[connection_key]
        if record:
            disconnected_at = _utc_now_iso()
            self.last_disconnect_by_org[record.organization_id] = disconnected_at
            logger.info(
                "Runner disconnected for organization %s workspace %s",
                record.organization_id,
                record.workspace_id,
            )
            await _record_connector_signal_event_safely(
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                signal_key="connector_heartbeat",
                state_code="disconnected",
                detail_text="outbound runner socket disconnected",
            )

    async def touch(self, connection_key: str):
        record = self.connection_records.get(connection_key)
        if record:
            self.last_seen_by_org[record.organization_id] = _utc_now_iso()
            await _record_connector_signal_event_safely(
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                signal_key="connector_heartbeat",
                state_code="heartbeat",
                detail_text="outbound runner heartbeat received",
            )

    async def dispatch_command(
        self,
        organization_id: str,
        workspace_id: str,
        command: dict[str, Any],
        *,
        timeout_seconds: float = 30,
        schedule_retry: bool = True,
    ) -> dict[str, Any]:
        connection = self._active_connection_for_scope(organization_id, workspace_id)
        if connection is None:
            await _record_connector_command_event_safely(
                organization_id=organization_id,
                workspace_id=workspace_id,
                state_code="runner_not_connected",
                detail_text="runner command dispatch failed",
            )
            return await _dispatch_error_with_retry(
                organization_id=organization_id,
                workspace_id=workspace_id,
                command=command,
                error_code="runner_not_connected",
                runner_request_id=None,
                schedule_retry=schedule_retry,
            )

        request_id = _valid_request_id(command.get("request_id")) or (
            f"runner_req_{uuid.uuid4().hex}"
        )
        outbound_command = dict(command)
        outbound_command["request_id"] = request_id
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending_responses[request_id] = response_future
        try:
            await connection.send_text(
                json.dumps(outbound_command, separators=(",", ":"), sort_keys=True)
            )
            await _record_connector_signal_event_safely(
                organization_id=organization_id,
                workspace_id=workspace_id,
                signal_key="connector_command",
                state_code="dispatched",
                detail_text=f"runner command dispatched: {outbound_command.get('action', 'unknown')}",
            )
            response = await asyncio.wait_for(response_future, timeout=timeout_seconds)
            return await _dispatch_response_with_retry(
                organization_id=organization_id,
                workspace_id=workspace_id,
                command=outbound_command,
                response=response,
                runner_request_id=request_id,
                schedule_retry=schedule_retry,
            )
        except asyncio.TimeoutError:
            await _record_connector_command_event_safely(
                organization_id=organization_id,
                workspace_id=workspace_id,
                state_code="runner_response_timeout",
                detail_text="runner command response timed out",
            )
            return await _dispatch_error_with_retry(
                organization_id=organization_id,
                workspace_id=workspace_id,
                command=outbound_command,
                error_code="runner_response_timeout",
                runner_request_id=request_id,
                schedule_retry=schedule_retry,
            )
        except Exception:
            logger.exception("Runner command dispatch failed.")
            await _record_connector_command_event_safely(
                organization_id=organization_id,
                workspace_id=workspace_id,
                state_code="runner_dispatch_failed",
                detail_text="runner command dispatch failed",
            )
            return await _dispatch_error_with_retry(
                organization_id=organization_id,
                workspace_id=workspace_id,
                command=outbound_command,
                error_code="runner_dispatch_failed",
                runner_request_id=request_id,
                schedule_retry=schedule_retry,
            )
        finally:
            self.pending_responses.pop(request_id, None)

    async def handle_runner_message(self, connection_key: str, data: str) -> bool:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        request_id = _valid_request_id(payload.get("request_id"))
        if request_id is None:
            return False
        response_future = self.pending_responses.get(request_id)
        if response_future is None or response_future.done():
            return False
        response_future.set_result(payload)
        record = self.connection_records.get(connection_key)
        if record:
            await _record_connector_command_event_safely(
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                state_code=_runner_response_state_code(payload),
                detail_text="runner command response received",
            )
        return True

    def snapshot(
        self, organization_id: str, workspace_id: str
    ) -> RunnerConnectionSnapshot:
        active_records = [
            record
            for record in self.connection_records.values()
            if record.organization_id == organization_id
        ]
        active_count = len(active_records)
        last_seen_candidates = [
            candidate
            for candidate in [self.last_seen_by_org.get(organization_id)]
            if candidate
        ]
        if active_records:
            last_seen_candidates.extend(record.connected_at for record in active_records)
        last_seen_at = max(last_seen_candidates) if last_seen_candidates else None
        return RunnerConnectionSnapshot(
            organization_id=organization_id,
            workspace_id=active_records[0].workspace_id if active_records else workspace_id,
            connection_state="connected" if active_count else "not_connected",
            active_connection_count=active_count,
            last_seen_at=last_seen_at,
            last_disconnect_at=self.last_disconnect_by_org.get(organization_id),
        )

    def reset(self):
        self.active_connections.clear()
        self.connection_records.clear()
        self.last_seen_by_org.clear()
        self.last_disconnect_by_org.clear()
        for response_future in self.pending_responses.values():
            if not response_future.done():
                response_future.cancel()
        self.pending_responses.clear()

    def _active_connection_for_scope(
        self, organization_id: str, workspace_id: str
    ) -> WebSocket | None:
        for connection_key, record in self.connection_records.items():
            if (
                record.organization_id == organization_id
                and record.workspace_id == workspace_id
            ):
                return self.active_connections.get(connection_key)
        return None


manager = ConnectionManager()


def _policy_violation() -> WebSocketException:
    return WebSocketException(code=status.WS_1008_POLICY_VIOLATION)


def _dispatch_error(error_code: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": error_code,
        "error_code": error_code,
        "provider_write_executed": False,
    }


async def _dispatch_error_with_retry(
    *,
    organization_id: str,
    workspace_id: str,
    command: dict[str, Any],
    error_code: str,
    runner_request_id: str | None,
    schedule_retry: bool,
) -> dict[str, Any]:
    result = _dispatch_error(error_code)
    return await _dispatch_response_with_retry(
        organization_id=organization_id,
        workspace_id=workspace_id,
        command=command,
        response=result,
        runner_request_id=runner_request_id,
        schedule_retry=schedule_retry,
    )


async def _dispatch_response_with_retry(
    *,
    organization_id: str,
    workspace_id: str,
    command: dict[str, Any],
    response: dict[str, Any],
    runner_request_id: str | None,
    schedule_retry: bool,
) -> dict[str, Any]:
    if not schedule_retry:
        return response
    error_code = _dispatch_response_error_code(response)
    if error_code is None:
        return response
    if not is_retryable_provider_writeback_failure(command, error_code):
        return response
    retry_item_uid = await schedule_provider_writeback_retry_safely(
        organization_id=organization_id,
        workspace_id=workspace_id,
        command=command,
        error_code=error_code,
        runner_request_id=runner_request_id,
    )
    if retry_item_uid is None:
        return response
    response_with_retry = dict(response)
    response_with_retry["retry_item_uid"] = retry_item_uid
    return response_with_retry


def _dispatch_response_error_code(response: dict[str, Any]) -> str | None:
    if response.get("provider_write_executed") is True:
        return None
    if response.get("status") != "error":
        return None
    error_code = response.get("error_code") or response.get("error")
    if isinstance(error_code, str) and error_code.strip():
        return error_code.strip()
    return None


def _runner_response_state_code(payload: dict[str, Any]) -> str:
    if payload.get("status") == "error":
        error_code = payload.get("error_code") or payload.get("error")
        if isinstance(error_code, str) and 0 < len(error_code.strip()) <= 128:
            return error_code.strip()
    status_code = payload.get("status")
    if isinstance(status_code, str) and 0 < len(status_code.strip()) <= 128:
        return status_code.strip()
    return "response"


def _valid_request_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 128:
        return None
    return value


def _auth_context_from_websocket(websocket: WebSocket) -> AuthContext:
    try:
        return build_auth_context(websocket.headers.get("authorization"))
    except HTTPException as exc:
        raise _policy_violation() from exc


async def _registered_runner_token(organization_id: str) -> str | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkspaceRunnerConfig.registration_token).where(
                WorkspaceRunnerConfig.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none()


async def record_connector_signal_event(
    *,
    organization_id: str,
    workspace_id: str,
    signal_key: str,
    state_code: str,
    detail_text: str,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ConnectorSignalEvent(
                organization_id=organization_id,
                workspace_id=workspace_id,
                signal_key=signal_key,
                state_code=state_code,
                detail_text=detail_text,
            )
        )
        await db.commit()


async def _record_connector_signal_event_safely(
    *,
    organization_id: str,
    workspace_id: str,
    signal_key: str,
    state_code: str,
    detail_text: str,
) -> None:
    try:
        await record_connector_signal_event(
            organization_id=organization_id,
            workspace_id=workspace_id,
            signal_key=signal_key,
            state_code=state_code,
            detail_text=detail_text,
        )
    except SQLAlchemyError:
        logger.debug("Runner signal event persistence skipped", exc_info=True)


async def _record_connector_command_event_safely(
    *,
    organization_id: str,
    workspace_id: str,
    state_code: str,
    detail_text: str,
) -> None:
    await _record_connector_signal_event_safely(
        organization_id=organization_id,
        workspace_id=workspace_id,
        signal_key="connector_command",
        state_code=state_code,
        detail_text=detail_text,
    )


async def _runner_connection_key(token: str, auth_context: AuthContext) -> str:
    if not token or not auth_context.organization_id:
        raise _policy_violation()

    registered_token = await _registered_runner_token(auth_context.organization_id)
    if not registered_token or not hmac.compare_digest(registered_token, token):
        raise _policy_violation()

    token_fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"{auth_context.organization_id}:{token_fingerprint}"


@router.websocket("/ws/runner/{token}")
async def runner_endpoint(websocket: WebSocket, token: str):
    auth_context = _auth_context_from_websocket(websocket)
    connection_key = await _runner_connection_key(token, auth_context)
    await manager.connect(websocket, connection_key, auth_context)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.touch(connection_key)
            if await manager.handle_runner_message(connection_key, data):
                continue
            await websocket.send_text(f"Naruon ack: {data}")
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(connection_key)
