import base64
import dataclasses
import datetime
import hashlib
import hmac
import json
import time
import uuid
from contextlib import asynccontextmanager

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.auth import SESSION_AUDIENCE, SESSION_ISSUER
from core.config import settings
from db.models import (
    AgentRunRecord,
    Base,
    LLMProvider,
    PromptTemplate,
    SecurityAuditEvent,
    WorkflowDefinition,
)
from db.session import get_db
from main import app

TEST_SESSION_HMAC_SECRET = "ai-hub-surface-hmac-value-20260529-32"  # noqa: S105


class MockScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class MockResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return MockScalars(self._rows)


class MockSession:
    def __init__(self):
        self.prompts: list[PromptTemplate] = []
        self.providers: list[LLMProvider] = []
        self.audit_events: list[SecurityAuditEvent] = []
        self.workflow_definitions: list[WorkflowDefinition] = []
        self.agent_run_records: list[AgentRunRecord] = []

    async def execute(self, stmt):
        descriptions = getattr(stmt, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        params = stmt.compile().params
        if entity is PromptTemplate:
            owner_id = params.get("created_by_1")
            organization_id = params.get("organization_id_1")
            workspace_id = params.get("workspace_id_1")
            return MockResult(
                [
                    prompt
                    for prompt in self.prompts
                    if prompt.organization_id == organization_id
                    and prompt.workspace_id == workspace_id
                    and (prompt.created_by == owner_id or prompt.is_shared is True)
                ]
            )
        if entity is LLMProvider:
            organization_id = params.get("organization_id_1")
            return MockResult(
                [
                    provider
                    for provider in self.providers
                    if provider.organization_id == organization_id
                ]
            )
        if entity is SecurityAuditEvent:
            organization_id = params.get("organization_id_1")
            workspace_id = params.get("workspace_id_1")
            actor_user_id = params.get("actor_user_id_1")
            rows = [
                event
                for event in self.audit_events
                if event.organization_id == organization_id
                and event.workspace_id == workspace_id
                and event.resource_type == "llm_provider"
            ]
            if actor_user_id:
                rows = [event for event in rows if event.actor_user_id == actor_user_id]
            return MockResult(rows)
        if entity is WorkflowDefinition:
            organization_id = params.get("organization_id_1")
            workspace_id = params.get("workspace_id_1")
            user_id = params.get("user_id_1")
            return MockResult(
                [
                    workflow
                    for workflow in self.workflow_definitions
                    if workflow.organization_id == organization_id
                    and workflow.workspace_id == workspace_id
                    and workflow.user_id == user_id
                ]
            )
        if entity is AgentRunRecord:
            organization_id = params.get("organization_id_1")
            workspace_id = params.get("workspace_id_1")
            user_id = params.get("user_id_1")
            return MockResult(
                [
                    run_record
                    for run_record in self.agent_run_records
                    if run_record.organization_id == organization_id
                    and run_record.workspace_id == workspace_id
                    and run_record.user_id == user_id
                ]
            )
        return MockResult([])

    def add(self, row):
        if isinstance(row, WorkflowDefinition):
            self.workflow_definitions.append(row)
            return
        if isinstance(row, AgentRunRecord):
            self.agent_run_records.append(row)
            return
        raise AssertionError(f"Unexpected mock row type: {type(row)!r}")

    def add_all(self, rows):
        for row in rows:
            self.add(row)

    async def commit(self):
        return None

    async def refresh(self, row):
        return None


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _signed_session_token(
    payload: dict[str, object],
    *,
    header: dict[str, object] | None = None,
) -> str:
    header_segment = _base64url_encode(
        json.dumps(
            header or {"alg": "HS256", "typ": "JWT"},
            separators=(",", ":"),
        ).encode()
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
        "iss": SESSION_ISSUER,
        "aud": SESSION_AUDIENCE,
        "sub": "alice",
        "role": "member",
        "org": "org-acme",
        "groups": ["group-ai"],
        "workspace": "workspace-org-acme",
        "exp": int(time.time()) + 300,
    }
    payload.update(overrides)
    return payload


def _now() -> datetime.datetime:
    return datetime.datetime(2026, 5, 29, 9, 30, tzinfo=datetime.timezone.utc)


def _prompt(
    prompt_id: int,
    title: str,
    owner_id: str = "alice",
    *,
    organization_id: str | None = "org-acme",
    workspace_id: str | None = "workspace-org-acme",
) -> PromptTemplate:
    prompt = PromptTemplate(
        prompt_uid=f"prompt_test_{prompt_id}",
        title=title,
        description="메일에서 판단 포인트를 추출합니다.",
        content="Summarize {{email}}",
        is_shared=False,
        created_by=owner_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    prompt.id = prompt_id
    prompt.created_at = _now()
    prompt.updated_at = _now()
    return prompt


def _provider(provider_id: int, *, active: bool = True) -> LLMProvider:
    provider = LLMProvider(
        user_id="alice",
        organization_id="org-acme",
        name="Primary OpenAI",
        provider_type="openai",
        api_key="credential material",
        is_active=active,
    )
    provider.id = provider_id
    provider.updated_at = _now()
    return provider


def _audit_event() -> SecurityAuditEvent:
    return SecurityAuditEvent(
        event_uid="audit_evt_provider_update",
        actor_user_id="alice",
        actor_role="tenant_admin",
        organization_id="org-acme",
        workspace_id="workspace-org-acme",
        event_action="update",
        resource_type="llm_provider",
        resource_uid="llm_provider:abc123",
        evidence_source="api.llm_providers",
        detail_text="Updated provider configuration",
        observed_at=_now(),
    )


def _workflow_definition(
    workflow_uid: str = "workflow_test_actual",
    *,
    user_id: str = "alice",
    organization_id: str = "org-acme",
    workspace_id: str = "workspace-org-acme",
) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_uid=workflow_uid,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        workflow_name="주간 리포트 자동 작성",
        workflow_description="durable workflow definition",
        steps_json=[
            {"step_key": "mail_collect", "step_label": "메일 수집"},
            {"step_key": "summary_write", "step_label": "요약 작성"},
        ],
        state_code="ready",
        created_at=_now(),
        updated_at=_now(),
    )


def _agent_run_record(
    run_uid: str = "agent_run_test_actual",
    *,
    workflow_uid: str = "workflow_test_actual",
    user_id: str = "alice",
    organization_id: str = "org-acme",
    workspace_id: str = "workspace-org-acme",
) -> AgentRunRecord:
    return AgentRunRecord(
        run_uid=run_uid,
        workflow_uid=workflow_uid,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        status_code="completed",
        started_at=_now(),
        completed_at=_now() + datetime.timedelta(minutes=3),
        result_summary="3개 판단 포인트를 추출했습니다.",
    )


def _request_with_signed_session(
    db_session: MockSession,
    header: dict[str, object] | None = None,
    *,
    method: str = "GET",
    path: str = "/api/ai-hub/surface",
    json_body: dict[str, object] | None = None,
    **payload_overrides: object,
):
    previous_secret = settings.AUTH_SESSION_HMAC_SECRET
    original_overrides = dict(app.dependency_overrides)

    async def scoped_db():
        yield db_session

    settings.AUTH_SESSION_HMAC_SECRET = SecretStr(TEST_SESSION_HMAC_SECRET)
    app.dependency_overrides[get_db] = scoped_db
    try:
        token = _signed_session_token(
            _valid_session_payload(**payload_overrides),
            header=header,
        )
        with TestClient(app) as client:
            request = getattr(client, method.lower())
            kwargs = {"headers": {"Authorization": f"Bearer {token}"}}
            if json_body is not None:
                kwargs["json"] = json_body
            return request(path, **kwargs)
    finally:
        settings.AUTH_SESSION_HMAC_SECRET = previous_secret
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def test_ai_hub_surface_uses_signed_source_evidence():
    session = MockSession()
    session.prompts = [
        _prompt(1, "의사결정 로그 맥락 종합"),
        _prompt(2, "공유 프롬프트", owner_id="other-user"),
        _prompt(
            3,
            "다른 조직 공유 프롬프트",
            owner_id="rival-user",
            organization_id="org-rival",
            workspace_id="workspace-org-rival",
        ),
        _prompt(
            4,
            "무스코프 레거시 공유 프롬프트",
            owner_id="legacy-user",
            organization_id=None,
            workspace_id=None,
        ),
    ]
    session.prompts[1].is_shared = True
    session.prompts[2].is_shared = True
    session.prompts[3].is_shared = True
    session.providers = [_provider(1)]
    session.audit_events = [_audit_event()]

    response = _request_with_signed_session(session)

    assert response.status_code == 200
    data = response.json()
    assert data["summary_cards"][0]["value_text"] == "2"
    assert data["prompt_cards"][0]["prompt_title"] == "의사결정 로그 맥락 종합"
    assert data["prompt_cards"][1]["prompt_title"] == "공유 프롬프트"
    assert data["prompt_cards"][1]["owner_label"] == "other-user"
    assert data["prompt_cards"][0]["prompt_key"] == "prompt_test_1"
    assert "다른 조직 공유 프롬프트" not in response.text
    assert "무스코프 레거시 공유 프롬프트" not in response.text
    assert "id" not in data["prompt_cards"][0]
    assert data["workflow_cards"][0]["state_code"] == "needs_provider"

    assert data["evaluation_metrics"][1]["score_value"] == 0
    assert data["run_events"][0]["evidence_source"] == "api.llm_providers"
    assert "credential material" not in response.text


def test_ai_hub_surface_hides_provider_metadata_for_members():
    session = MockSession()
    session.prompts = [_prompt(1, "멤버 프롬프트")]
    session.providers = [_provider(1)]

    response = _request_with_signed_session(session, role="member")

    assert response.status_code == 200
    data = response.json()
    assert data["prompt_cards"][0]["prompt_title"] == "멤버 프롬프트"
    assert data["agent_cards"] == []
    assert data["summary_cards"][2]["value_text"] == "0/0"


def test_ai_hub_surface_prefers_durable_workflows_and_agent_runs():
    session = MockSession()
    session.prompts = [_prompt(1, "Fallback prompt")]
    session.workflow_definitions = [_workflow_definition()]
    session.agent_run_records = [_agent_run_record()]

    response = _request_with_signed_session(session)

    assert response.status_code == 200
    data = response.json()
    assert data["workflow_cards"][0]["workflow_key"] == "workflow_test_actual"
    assert data["workflow_cards"][0]["workflow_title"] == "주간 리포트 자동 작성"
    assert data["workflow_cards"][0]["trigger_source"] == "workflow_definition"
    assert data["workflow_cards"][0]["evidence_text"] == "2 persisted workflow steps"
    assert data["run_events"][0]["event_key"] == "agent_run_test_actual"
    assert data["run_events"][0]["evidence_source"] == "agent_run_records"
    assert data["run_events"][0]["state_code"] == "completed"
    assert "prompt template updated" not in response.text


def test_ai_hub_workflow_api_creates_and_lists_scoped_workflows():
    session = MockSession()

    create_response = _request_with_signed_session(
        session,
        method="POST",
        path="/api/ai-hub/workflows",
        json_body={
            "workflow_name": " 신규 워크플로우 ",
            "workflow_description": " 신규 실행 흐름 ",
            "steps_json": [{"step_key": "collect"}, {"step_key": "summarize"}],
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["workflow_key"].startswith("workflow_")
    assert created["workflow_title"] == "신규 워크플로우"
    assert created["trigger_source"] == "workflow_definition"
    assert created["state_code"] == "draft"
    assert "id" not in created
    assert len(session.workflow_definitions) == 1
    stored_workflow = session.workflow_definitions[0]
    assert stored_workflow.organization_id == "org-acme"
    assert stored_workflow.workspace_id == "workspace-org-acme"
    assert stored_workflow.user_id == "alice"
    assert stored_workflow.workflow_description == "신규 실행 흐름"

    list_response = _request_with_signed_session(
        session,
        path="/api/ai-hub/workflows",
    )

    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed == [created]


@pytest.mark.parametrize(
    "json_body",
    [
        {
            "workflow_name": "   ",
            "workflow_description": "blank names are rejected",
            "steps_json": [{"step_key": "collect"}],
        },
        {
            "workflow_name": "잘못된 단계",
            "workflow_description": "steps_json must be a list",
            "steps_json": {"step_key": "collect"},
        },
    ],
)
def test_ai_hub_workflow_api_rejects_invalid_create_payloads(json_body):
    session = MockSession()

    response = _request_with_signed_session(
        session,
        method="POST",
        path="/api/ai-hub/workflows",
        json_body=json_body,
    )

    assert response.status_code == 422
    assert session.workflow_definitions == []


def test_ai_hub_workflow_api_requires_signed_session():
    session = MockSession()
    original_overrides = dict(app.dependency_overrides)

    async def scoped_db():
        yield session

    app.dependency_overrides[get_db] = scoped_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/ai-hub/workflows",
                json={
                    "workflow_name": "인증 없는 생성",
                    "steps_json": [{"step_key": "collect"}],
                },
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert session.workflow_definitions == []


def test_ai_hub_run_api_lists_only_signed_session_scope():
    session = MockSession()
    session.agent_run_records = [
        _agent_run_record(),
        _agent_run_record(
            run_uid="agent_run_rival",
            workflow_uid="workflow_rival",
            organization_id="org-rival",
            workspace_id="workspace-org-rival",
        ),
    ]

    response = _request_with_signed_session(
        session,
        path="/api/ai-hub/runs",
    )

    assert response.status_code == 200
    data = response.json()
    assert [event["event_key"] for event in data] == ["agent_run_test_actual"]
    assert data[0]["evidence_source"] == "agent_run_records"


def test_ai_hub_surface_rejects_public_identity_headers_without_signed_session():
    session = MockSession()
    original_overrides = dict(app.dependency_overrides)

    async def scoped_db():
        yield session

    app.dependency_overrides[get_db] = scoped_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/ai-hub/surface",
                headers={
                    "X-User-Id": "alice",
                    "X-User-Role": "tenant_admin",
                    "X-Organization-Id": "org-acme",
                },
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_ai_hub_surface_rejects_unsupported_signed_session_crit_header():
    session = MockSession()

    response = _request_with_signed_session(
        session,
        header={
            "alg": "HS256",
            "typ": "JWT",
            "crit": ["x-custom-policy"],
            "x-custom-policy": "require-mfa",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


@dataclasses.dataclass
class SmokeDataIDs:
    user_id: str
    organization_id: str
    workspace_id: str
    event_uid: str
    workflow_uid: str
    run_uid: str


@asynccontextmanager
async def _setup_postgres_smoke_data(database_url: str):
    user_id = f"ai_hub_user_{uuid.uuid4().hex[:12]}"
    organization_id = f"ai_hub_org_{uuid.uuid4().hex[:12]}"
    workspace_id = f"workspace_{organization_id}"
    event_uid = f"audit_evt_ai_hub_{uuid.uuid4().hex[:18]}"
    workflow_uid = f"workflow_{uuid.uuid4().hex}"
    run_uid = f"agent_run_{uuid.uuid4().hex}"

    ids = SmokeDataIDs(
        user_id=user_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        event_uid=event_uid,
        workflow_uid=workflow_uid,
        run_uid=run_uid,
    )

    engine = create_async_engine(database_url, echo=False)
    session_factory = None
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
    except (
        ConnectionRefusedError,
        OSError,
        OperationalError,
        asyncpg.CannotConnectNowError,
        asyncpg.InvalidAuthorizationSpecificationError,
        asyncpg.InvalidCatalogNameError,
        asyncpg.InvalidPasswordError,
    ) as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL smoke path unavailable: {exc}")
    except Exception as exc:
        if "Multiple exceptions:" in str(exc) or "Connect call failed" in str(exc):
            await engine.dispose()
            pytest.skip(f"PostgreSQL smoke path unavailable: {exc}")
        await engine.dispose()
        raise

    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            prompt = PromptTemplate(
                prompt_uid=f"prompt_{uuid.uuid4().hex}",
                title="Postgres AI Hub prompt",
                description="source-backed postgres smoke prompt",
                content="Summarize {{email}}",
                is_shared=False,
                created_by=user_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
            provider = LLMProvider(
                user_id=user_id,
                organization_id=organization_id,
                name="Postgres Provider",
                provider_type="openai",
                api_key=None,
                is_active=True,
            )
            audit_event = SecurityAuditEvent(
                event_uid=event_uid,
                actor_user_id=user_id,
                actor_role="tenant_admin",
                organization_id=organization_id,
                workspace_id=workspace_id,
                event_action="update",
                resource_type="llm_provider",
                resource_uid="llm_provider:postgres",
                evidence_source="api.llm_providers",
                detail_text="Postgres provider evidence",
                observed_at=_now(),
            )
            workflow = WorkflowDefinition(
                workflow_uid=workflow_uid,
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                workflow_name="Postgres workflow",
                workflow_description="source-backed workflow smoke",
                steps_json=[{"step_key": "postgres_smoke"}],
                state_code="ready",
                created_at=_now(),
                updated_at=_now(),
            )
            run_record = AgentRunRecord(
                run_uid=run_uid,
                workflow_uid=workflow_uid,
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                status_code="completed",
                started_at=_now(),
                completed_at=_now() + datetime.timedelta(minutes=1),
                result_summary="Postgres run evidence",
            )
            session.add_all([prompt, provider, audit_event, workflow, run_record])
            await session.commit()

        yield session_factory, ids

    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM agent_run_records WHERE run_uid = :run_uid"),
                {"run_uid": run_uid},
            )
            await conn.execute(
                text(
                    "DELETE FROM workflow_definitions "
                    "WHERE workflow_uid = :workflow_uid"
                ),
                {"workflow_uid": workflow_uid},
            )
            await conn.execute(
                text("DELETE FROM security_audit_events WHERE event_uid = :event_uid"),
                {"event_uid": event_uid},
            )
            await conn.execute(
                text(
                    """
                    DELETE FROM llm_providers
                    WHERE user_id = :user_id AND organization_id = :organization_id
                    """
                ),
                {"user_id": user_id, "organization_id": organization_id},
            )
            await conn.execute(
                text("DELETE FROM prompt_templates WHERE created_by = :user_id"),
                {"user_id": user_id},
            )
        await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_ai_hub_surface_postgres_smoke_uses_signed_scope():
    database_url = getattr(settings, "DATABASE_URL", None)
    if not database_url:
        pytest.skip("PostgreSQL smoke path unavailable: DATABASE_URL is not set")

    async with _setup_postgres_smoke_data(database_url) as (session_factory, ids):
        assert session_factory is not None

        async def override_real_db():
            async with session_factory() as session:
                yield session

        previous_secret = settings.AUTH_SESSION_HMAC_SECRET
        original_overrides = dict(app.dependency_overrides)
        settings.AUTH_SESSION_HMAC_SECRET = SecretStr(TEST_SESSION_HMAC_SECRET)
        token = _signed_session_token(
            _valid_session_payload(
                sub=ids.user_id,
                org=ids.organization_id,
                workspace=ids.workspace_id,
            )
        )
        app.dependency_overrides[get_db] = override_real_db
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                response = await client.get("/api/ai-hub/surface")
        finally:
            settings.AUTH_SESSION_HMAC_SECRET = previous_secret
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original_overrides)

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["prompt_cards"][0]["prompt_title"] == "Postgres AI Hub prompt"
        assert data["workflow_cards"][0]["workflow_key"] == ids.workflow_uid
        assert data["workflow_cards"][0]["trigger_source"] == "workflow_definition"
        assert data["agent_cards"][0]["agent_title"] == "Postgres Provider"
        assert data["agent_cards"][0]["configured"] is False
        assert data["run_events"][0]["event_key"] == ids.run_uid
        assert data["run_events"][0]["evidence_source"] == "agent_run_records"
