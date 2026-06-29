import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.data as data_api
from api.auth import get_auth_context, get_current_user
from core.config import settings
from db.models import (
    Attachment,
    Base,
    ConnectorSignalEvent,
    Document,
    Email,
    ProjectFolder,
    WebdavAccount,
)
from db.session import get_db
from main import app

TEST_SESSION_HMAC_SECRET = "data-quality-surface-hmac-material-32-bytes"  # noqa: S105


class MockResult:
    def __init__(self, obj):
        self.obj = obj

    def scalars(self):
        return self

    def all(self):
        return self.obj if isinstance(self.obj, list) else []

    def scalar_one(self):
        return self.obj

    def scalar_one_or_none(self):
        return self.obj

    def one_or_none(self):
        return self.obj


class MockAsyncSession:
    def __init__(self, results):
        self.results = results
        self.documents: list[Document] = []
        self.queries = []
        self.execute_calls = 0

    async def execute(self, query):
        self.queries.append(query)
        rendered_query = str(query)
        rendered_query_lower = rendered_query.lower()
        if (
            "webdav_accounts.source_uid" in rendered_query_lower
            and "webdav_accounts.account_id" not in rendered_query_lower
        ):
            result = self.results[self.execute_calls]
            self.execute_calls += 1
            return MockResult(
                [
                    (
                        account.source_uid,
                        account.writeback_enabled,
                        account.etag_value,
                    )
                    for account in result
                ]
            )
        if "from workspace_documents" in rendered_query_lower:
            compiled = query.compile()
            params = compiled.params
            document_id = next(
                (
                    value
                    for key, value in params.items()
                    if key.startswith("document_id")
                ),
                None,
            )
            workspace_id = next(
                (
                    value
                    for key, value in params.items()
                    if key.startswith("workspace_id")
                ),
                None,
            )
            rows = [
                document
                for document in self.documents
                if (document_id is None or document.document_id == document_id)
                and (workspace_id is None or document.workspace_id == workspace_id)
            ]
            if "order by" in rendered_query_lower:
                return MockResult(rows)
            return MockResult(rows[0] if rows else None)
        result = self.results[self.execute_calls]
        self.execute_calls += 1
        return MockResult(result)

    def add(self, obj):
        if isinstance(obj, Document):
            if not obj.document_id:
                obj.document_id = f"doc_mock_{len(self.documents) + 1}"
            if not obj.created_at:
                obj.created_at = _now()
            self.documents.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


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
        "groups": ["group-data"],
        "workspace": "workspace-org-acme",
        "exp": int(time.time()) + 300,
    }
    payload.update(overrides)
    return payload


def _now() -> datetime:
    return datetime(2026, 5, 28, 5, 45, tzinfo=timezone.utc)


def _webdav_account(source_uid: str) -> WebdavAccount:
    return WebdavAccount(
        source_uid=source_uid,
        user_id="owner",
        organization_id="org-acme",
        workspace_id="workspace-org-acme",
        server_url="https://files.acme.example/dav",
        username="files@example.com",
        credentials_encrypted="credential secret",
        writeback_enabled=True,
        etag_value="etag-webdav-primary",
        created_at=_now(),
    )


def _email(
    message_id: str,
    *,
    thread_id: str | None,
    subject: str = "Data source package",
) -> Email:
    return Email(
        user_id="owner",
        organization_id="org-acme",
        message_id=message_id,
        thread_id=thread_id,
        fingerprint=f"sha256:{message_id}",
        sender="partner@example.com",
        recipients="owner@example.com",
        subject=subject,
        date=_now(),
        body="source email body",
    )


def _attachment(filename: str, content: str) -> Attachment:
    return Attachment(filename=filename, content=content)


def _project_folder(folder_uid: str) -> ProjectFolder:
    return ProjectFolder(
        folder_uid=folder_uid,
        user_id="owner",
        organization_id="org-acme",
        project_name="Naruon Roadmap 2026",
        webdav_path="/Projects/Naruon_Roadmap_2026",
        created_at=_now(),
    )


def _connector_event(event_uid: str) -> ConnectorSignalEvent:
    return ConnectorSignalEvent(
        event_uid=event_uid,
        organization_id="org-acme",
        workspace_id="workspace-org-acme",
        signal_key="connector_heartbeat",
        state_code="heartbeat",
        detail_text="outbound connector heartbeat received",
        observed_at=_now(),
    )


@pytest.fixture
def mock_db():
    ready_email = _email("<asset-ready@example.com>", thread_id="thread-ready")
    pending_email = _email(
        "<asset-pending@example.com>",
        thread_id=None,
        subject="<script>Quarterly source pack</script>",
    )
    return MockAsyncSession(
        [
            [_webdav_account("webdav_src_primary")],
            [_project_folder("webdav_folder_roadmap")],
            (4, 1, 2, 3),  # email stats
            (3, 1, 1),  # attachment stats
            [_connector_event("connector_evt_data_quality")],
            [
                (_attachment("roadmap.pdf", "extracted attachment text"), ready_email),
                (_attachment("quarterly.md", ""), pending_email),
            ],
        ]
    )


def _with_signed_auth(mock_db, token: str):
    async def override_get_db():
        yield mock_db

    previous_secret = settings.AUTH_SESSION_HMAC_SECRET
    original_overrides = dict(app.dependency_overrides)
    settings.AUTH_SESSION_HMAC_SECRET = SecretStr(TEST_SESSION_HMAC_SECRET)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_auth_context, None)
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    return client, previous_secret, original_overrides


def _restore_overrides(previous_secret, original_overrides):
    settings.AUTH_SESSION_HMAC_SECRET = previous_secret
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)


def test_data_quality_surface_returns_source_backed_counts_without_secrets(mock_db):
    token = _signed_session_token(_valid_session_payload())
    client, previous_secret, original_overrides = _with_signed_auth(mock_db, token)
    try:
        response = client.get("/api/data/quality-surface")
    finally:
        client.close()
        _restore_overrides(previous_secret, original_overrides)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["audit_event"] == "data.quality_surface.viewed"
    assert data["workspace_id"] == "workspace-org-acme"
    assert data["provider_write_executed"] is False
    assert {source["source_id"] for source in data["repositories"]} == {
        "email_repository",
        "attachment_repository",
        "document_repository",
        "webdav_src_primary",
        "webdav_folder_roadmap",
    }
    assert data["pipeline_stages"][1]["detail_text"] == (
        "4 emails and 3 attachments are visible in the signed workspace scope."
    )
    assert data["embedding_collections"][0] == {
        "collection_key": "emails_embedding",
        "display_name": "Email vectors",
        "object_count": 4,
        "embedded_count": 3,
        "embedding_model": settings.OPENAI_EMBEDDING_MODEL,
        "vector_dimensions": 1536,
        "status_code": "running",
        "evidence_source": "emails.embedding",
        "provider_write_executed": False,
    }
    quality_by_key = {check["check_key"]: check for check in data["quality_checks"]}
    assert quality_by_key["thread_id_integrity"]["issue_count"] == 1
    assert quality_by_key["dedupe_fingerprint"]["issue_count"] == 2
    assert quality_by_key["attachment_content"]["issue_count"] == 1
    assert data["connector_events"][0]["event_uid"] == "connector_evt_data_quality"
    assert data["repository_assets"][0] == {
        "asset_key": data["repository_assets"][0]["asset_key"],
        "asset_type": "email_attachment",
        "display_name": "roadmap.pdf",
        "source_label": "Data source package",
        "state_code": "ready",
        "detail_text": "content and thread evidence ready",
        "content_chars": 25,
        "captured_at": "2026-05-28T05:45:00Z",
        "evidence_source": "attachments.content, emails.thread_id",
        "thread_key": data["repository_assets"][0]["thread_key"],
        "provider_write_executed": False,
    }
    assert data["repository_assets"][0]["asset_key"].startswith("asset_")
    assert data["repository_assets"][0]["thread_key"].startswith("thread_")
    assert data["repository_assets"][1]["state_code"] == "needs_attention"
    assert (
        data["repository_assets"][1]["source_label"]
        == "scriptQuarterly source pack/script"
    )

    serialized = response.text
    for forbidden in (
        "account_id",
        "folder_id",
        "credentials_encrypted",
        "credential secret",
        "username",
        "files@example.com",
        "https://files.acme.example",
        "webdav_path",
        "/Projects/Naruon_Roadmap_2026",
        "<asset-ready@example.com>",
        "thread-ready",
    ):
        assert forbidden not in serialized


def test_data_quality_surface_rejects_public_identity_headers_without_signed_session(
    mock_db,
):
    async def override_get_db():
        yield mock_db

    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_auth_context, None)
    app.dependency_overrides.pop(get_current_user, None)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/data/quality-surface",
                headers={
                    "X-User-Id": "admin",
                    "X-User-Role": "tenant_admin",
                    "X-Organization-Id": "org-acme",
                },
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_member_data_quality_queries_are_owner_scoped(mock_db):
    token = _signed_session_token(
        _valid_session_payload(
            sub="member", role="member", workspace="workspace-member"
        )
    )
    client, previous_secret, original_overrides = _with_signed_auth(mock_db, token)
    try:
        response = client.get("/api/data/quality-surface")
    finally:
        client.close()
        _restore_overrides(previous_secret, original_overrides)

    assert response.status_code == 200, response.text
    rendered_queries = "\n".join(str(query) for query in mock_db.queries)
    assert "webdav_accounts.user_id = :user_id_1" in rendered_queries
    assert "webdav_accounts.workspace_id = :workspace_id_1" in rendered_queries
    assert "project_folders.user_id = :user_id_1" in rendered_queries
    assert "email_records.user_id = :user_id_1" in rendered_queries


def test_data_quality_surface_includes_workspace_document_assets(mock_db):
    mock_db.documents.extend(
        [
            Document(
                document_id="doc_owned",
                workspace_id="workspace-org-acme",
                document_name="<b>roadmap.md</b>",
                document_type="text/markdown",
                document_content="# Roadmap",
                document_status="uploaded",
                created_at=_now(),
            ),
            Document(
                document_id="doc_rival",
                workspace_id="workspace-rival",
                document_name="rival.md",
                document_type="text/markdown",
                document_content="rival",
                document_status="uploaded",
                created_at=_now(),
            ),
        ]
    )
    token = _signed_session_token(_valid_session_payload())
    client, previous_secret, original_overrides = _with_signed_auth(mock_db, token)
    try:
        response = client.get("/api/data/quality-surface")
    finally:
        client.close()
        _restore_overrides(previous_secret, original_overrides)

    assert response.status_code == 200, response.text
    data = response.json()
    repositories_by_type = {
        repository["repository_type"]: repository for repository in data["repositories"]
    }
    assert repositories_by_type["document_repository"] == {
        "source_id": "document_repository",
        "repository_type": "document_repository",
        "display_name": "Scoped document repository",
        "object_count": 1,
        "writeback_enabled": None,
        "evidence_source": "documents",
        "provider_write_executed": False,
    }
    document_assets = [
        asset
        for asset in data["repository_assets"]
        if asset["asset_type"] == "workspace_document"
    ]
    assert document_assets == [
        {
            "asset_key": "doc_owned",
            "asset_type": "workspace_document",
            "display_name": "broadmap.md/b",
            "source_label": "Workspace document",
            "state_code": "ready",
            "detail_text": "document status: uploaded",
            "content_chars": 9,
            "captured_at": "2026-05-28T05:45:00Z",
            "evidence_source": "documents.document_status",
            "thread_key": "workspace_document",
            "provider_write_executed": False,
        }
    ]
    assert "doc_rival" not in response.text


def test_data_document_upload_creates_workspace_scoped_document(mock_db):
    token = _signed_session_token(_valid_session_payload(sub="member"))
    client, previous_secret, original_overrides = _with_signed_auth(mock_db, token)
    try:
        response = client.post(
            "/api/data/documents",
            json={
                "document_name": "<b>roadmap.md</b>",
                "document_type": "text/markdown",
                "document_content": "# Roadmap\nPhase 10",
            },
        )
    finally:
        client.close()
        _restore_overrides(previous_secret, original_overrides)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data == {
        "document_id": "doc_mock_1",
        "workspace_id": "workspace-org-acme",
        "document_name": "broadmap.md/b",
        "document_type": "text/markdown",
        "document_status": "uploaded",
        "content_chars": 18,
        "provider_write_executed": False,
        "provenance": "server-authoritative",
        "audit_event": "data.document.uploaded",
        "message": "Document stored in the signed workspace scope.",
    }
    stored_document = mock_db.documents[0]
    assert stored_document.workspace_id == "workspace-org-acme"
    assert stored_document.document_content == "# Roadmap\nPhase 10"


def test_data_document_actions_are_workspace_scoped_and_intent_only(mock_db):
    document = Document(
        document_id="doc_owned",
        workspace_id="workspace-org-acme",
        document_name="source.hwp",
        document_type="application/x-hwp",
        document_content="opaque hwp extraction placeholder",
        document_status="uploaded",
        created_at=_now(),
    )
    rival_document = Document(
        document_id="doc_rival",
        workspace_id="workspace-rival",
        document_name="rival.md",
        document_type="text/markdown",
        document_content="rival",
        document_status="uploaded",
        created_at=_now(),
    )
    mock_db.documents.extend([document, rival_document])
    token = _signed_session_token(_valid_session_payload())
    client, previous_secret, original_overrides = _with_signed_auth(mock_db, token)
    try:
        reparse_response = client.post("/api/data/documents/doc_owned/reparse")
        embedding_response = client.post(
            "/api/data/documents/doc_owned/embedding-regeneration-intent"
        )
        hwp_response = client.post(
            "/api/data/documents/doc_owned/hwp-conversion-intent"
        )
        rival_response = client.post("/api/data/documents/doc_rival/reparse")
    finally:
        client.close()
        _restore_overrides(previous_secret, original_overrides)

    assert reparse_response.status_code == 200, reparse_response.text
    assert reparse_response.json()["document_status"] == "parsed"
    assert reparse_response.json()["provider_write_executed"] is False
    assert reparse_response.json()["audit_event"] == "data.document.reparsed"

    assert embedding_response.status_code == 200, embedding_response.text
    embedding_data = embedding_response.json()
    assert embedding_data["document_status"] == "embedding_pending"
    assert embedding_data["provider_write_executed"] is False
    assert (
        embedding_data["audit_event"] == "data.document.embedding_regeneration_intent"
    )

    assert hwp_response.status_code == 200, hwp_response.text
    hwp_data = hwp_response.json()
    assert hwp_data["document_status"] == "hwp_conversion_pending"
    assert hwp_data["provider_write_executed"] is False
    assert hwp_data["audit_event"] == "data.document.hwp_conversion_intent"

    assert rival_response.status_code == 404
    assert "doc_rival" not in rival_response.text


def test_data_document_webdav_materialization_executes_source_backed_write(
    mock_db,
    monkeypatch,
):
    mock_db.documents.append(
        Document(
            document_id="doc_owned",
            workspace_id="workspace-org-acme",
            document_name="../<b>roadmap.md</b>",
            document_type="text/markdown",
            document_content="# Roadmap\nPhase 10",
            document_status="uploaded",
            created_at=_now(),
        )
    )
    dispatched: list[tuple[str | None, str, dict[str, object]]] = []

    async def fake_dispatch_command(
        organization_id: str | None,
        workspace_id: str,
        command: dict[str, object],
    ) -> dict[str, object]:
        dispatched.append((organization_id, workspace_id, command))
        return {
            "status": "completed",
            "request_id": "runner_req_data_doc_1",
            "provider_status": 201,
            "provider_write_executed": True,
        }

    monkeypatch.setattr(
        data_api.runner_manager, "dispatch_command", fake_dispatch_command
    )
    token = _signed_session_token(_valid_session_payload())
    client, previous_secret, original_overrides = _with_signed_auth(mock_db, token)
    try:
        response = client.post(
            "/api/data/documents/doc_owned/webdav-materialization-intent",
            json={
                "target_source_id": "webdav_src_primary",
                "execute_provider": True,
            },
        )
    finally:
        client.close()
        _restore_overrides(previous_secret, original_overrides)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "intent": "document_webdav_materialization",
        "status": "completed",
        "document_id": "doc_owned",
        "workspace_id": "workspace-org-acme",
        "document_name": "broadmap.md-b",
        "document_type": "text/markdown",
        "source_id": "webdav_src_primary",
        "target_label": "WebDAV source webdav_src_primary",
        "target_path": "/Naruon/Data/broadmap.md-b-d5fe4e8b.md",
        "requires_if_match": True,
        "if_match": "etag-webdav-primary",
        "provenance": "server-authoritative",
        "provider_write_executed": True,
        "audit_event": "data.document.webdav_materialization.executed",
        "runner_request_id": "runner_req_data_doc_1",
        "provider_status": 201,
        "error_code": None,
        "retry_item_uid": None,
        "message": "Workspace document WebDAV materialization executed by the connector.",
    }
    assert dispatched == [
        (
            "org-acme",
            "workspace-org-acme",
            {
                "action": "write_webdav",
                "account": "webdav_src_primary",
                "source_id": "webdav_src_primary",
                "target_path": "/Naruon/Data/broadmap.md-b-d5fe4e8b.md",
                "if_match": "etag-webdav-primary",
                "content_type": "text/markdown; charset=utf-8",
                "content": "# Roadmap\nPhase 10",
            },
        )
    ]
    serialized = response.text
    for forbidden in (
        "../",
        "<b>",
        "server_url",
        "username",
        "credentials_encrypted",
        "credential secret",
        "account_id",
    ):
        assert forbidden not in serialized


def test_data_document_webdav_materialization_rejects_empty_document(mock_db):
    mock_db.documents.append(
        Document(
            document_id="doc_empty",
            workspace_id="workspace-org-acme",
            document_name="empty.md",
            document_type="text/markdown",
            document_content="   ",
            document_status="uploaded",
            created_at=_now(),
        )
    )
    token = _signed_session_token(_valid_session_payload())
    client, previous_secret, original_overrides = _with_signed_auth(mock_db, token)
    try:
        response = client.post(
            "/api/data/documents/doc_empty/webdav-materialization-intent",
            json={
                "target_source_id": "webdav_src_primary",
                "execute_provider": True,
            },
        )
    finally:
        client.close()
        _restore_overrides(previous_secret, original_overrides)

    assert response.status_code == 422
    assert (
        response.json()["detail"] == "Workspace document has no materializable content."
    )


async def _seed_smoke_test_data(conn, ids: dict):
    await conn.execute(text("SELECT 1"))
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await conn.run_sync(Base.metadata.create_all)
    first_email = await conn.execute(
        text(
            """
            INSERT INTO email_records (
                user_id, organization_id, message_id, thread_id,
                fingerprint, sender, recipients, subject, "date", body
            )
            VALUES (
                :user_id, :organization_id, :message_id, :thread_id,
                :fingerprint, :sender, :recipients, :subject, now(), :body
            )
            RETURNING id
            """
        ),
        {
            "user_id": ids["user_id"],
            "organization_id": ids["organization_id"],
            "message_id": f"<data-smoke-{uuid.uuid4().hex}@example.com>",
            "thread_id": "thread-data-smoke",
            "fingerprint": "sha256:data-smoke",
            "sender": "partner@example.com",
            "recipients": "owner@example.com",
            "subject": "Data smoke ready",
            "body": "ready body",
        },
    )
    second_email = await conn.execute(
        text(
            """
            INSERT INTO email_records (
                user_id, organization_id, message_id, sender, recipients,
                subject, "date", body
            )
            VALUES (
                :user_id, :organization_id, :message_id, :sender,
                :recipients, :subject, now(), :body
            )
            RETURNING id
            """
        ),
        {
            "user_id": ids["user_id"],
            "organization_id": ids["organization_id"],
            "message_id": f"<data-smoke-missing-{uuid.uuid4().hex}@example.com>",
            "sender": "partner@example.com",
            "recipients": "owner@example.com",
            "subject": "Data smoke missing",
            "body": "missing body",
        },
    )
    rival_email = await conn.execute(
        text(
            """
            INSERT INTO email_records (
                user_id, organization_id, message_id, thread_id,
                fingerprint, sender, recipients, subject, "date", body
            )
            VALUES (
                :user_id, :organization_id, :message_id, :thread_id,
                :fingerprint, :sender, :recipients, :subject, now(), :body
            )
            RETURNING id
            """
        ),
        {
            "user_id": ids["rival_user_id"],
            "organization_id": ids["rival_organization_id"],
            "message_id": f"<data-rival-{uuid.uuid4().hex}@example.com>",
            "thread_id": "thread-rival",
            "fingerprint": "sha256:rival",
            "sender": "rival@example.com",
            "recipients": "rival@example.com",
            "subject": "Rival",
            "body": "rival body",
        },
    )
    first_email_id = first_email.scalar_one()
    second_email_id = second_email.scalar_one()
    rival_email_id = rival_email.scalar_one()
    await conn.execute(
        text(
            """
            INSERT INTO email_attachments (email_id, filename, content)
            VALUES
            (:first_email_id, 'ready.txt', 'ready attachment'),
            (:second_email_id, 'blank.txt', ''),
            (:rival_email_id, 'rival.txt', 'rival attachment')
            """
        ),
        {
            "first_email_id": first_email_id,
            "second_email_id": second_email_id,
            "rival_email_id": rival_email_id,
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO webdav_accounts (
                source_uid, user_id, organization_id, workspace_id,
                server_url, username, credentials_encrypted,
                writeback_enabled,
                created_at
            )
            VALUES
            (
                :webdav_uid, :user_id, :organization_id, :workspace_id,
                'https://data-files.example/dav', 'data@example.com',
                'encrypted-data-secret', true, now()
            ),
            (
                :rival_webdav_uid, :rival_user_id, :rival_organization_id,
                :rival_workspace_id,
                'https://rival-files.example/dav', 'rival@example.com',
                'encrypted-rival-secret', true, now()
            )
            """
        ),
        {
            "webdav_uid": ids["webdav_uid"],
            "user_id": ids["user_id"],
            "organization_id": ids["organization_id"],
            "workspace_id": ids["workspace_id"],
            "rival_webdav_uid": ids["rival_webdav_uid"],
            "rival_user_id": ids["rival_user_id"],
            "rival_organization_id": ids["rival_organization_id"],
            "rival_workspace_id": ids["rival_workspace_id"],
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO project_folders (
                folder_uid, user_id, organization_id, project_name,
                webdav_path,
                created_at
            )
            VALUES (
                :folder_uid, :user_id, :organization_id,
                'Data Smoke Folder', '/Projects/Data_Smoke', now()
            )
            """
        ),
        {
            "folder_uid": ids["folder_uid"],
            "user_id": ids["user_id"],
            "organization_id": ids["organization_id"],
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO connector_signal_events (
                event_uid, organization_id, workspace_id, signal_key,
                state_code, detail_text, observed_at
            )
            VALUES
            (
                :event_uid, :organization_id, :workspace_id,
                'connector_heartbeat', 'heartbeat',
                'data smoke heartbeat', now()
            ),
            (
                :other_workspace_event_uid, :organization_id,
                'other_workspace', 'connector_heartbeat', 'heartbeat',
                'other workspace heartbeat', now()
            )
            """
        ),
        {
            "event_uid": ids["event_uid"],
            "other_workspace_event_uid": ids["other_workspace_event_uid"],
            "organization_id": ids["organization_id"],
            "workspace_id": ids["workspace_id"],
        },
    )


async def _teardown_smoke_test_data(conn, ids: dict):
    await conn.execute(
        text(
            """
            DELETE FROM email_attachments
            WHERE email_id IN (
                SELECT id FROM email_records
                WHERE user_id IN (:user_id, :rival_user_id)
            )
            """
        ),
        {"user_id": ids["user_id"], "rival_user_id": ids["rival_user_id"]},
    )
    await conn.execute(
        text("DELETE FROM email_records WHERE user_id IN (:user_id, :rival_user_id)"),
        {"user_id": ids["user_id"], "rival_user_id": ids["rival_user_id"]},
    )
    await conn.execute(
        text(
            "DELETE FROM webdav_accounts "
            "WHERE source_uid IN (:webdav_uid, :rival_webdav_uid)"
        ),
        {
            "webdav_uid": ids["webdav_uid"],
            "rival_webdav_uid": ids["rival_webdav_uid"],
        },
    )
    await conn.execute(
        text("DELETE FROM project_folders WHERE folder_uid = :folder_uid"),
        {"folder_uid": ids["folder_uid"]},
    )
    await conn.execute(
        text(
            "DELETE FROM connector_signal_events "
            "WHERE event_uid IN (:event_uid, :other_workspace_event_uid)"
        ),
        {
            "event_uid": ids["event_uid"],
            "other_workspace_event_uid": ids["other_workspace_event_uid"],
        },
    )


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_data_quality_surface_real_postgres_smoke_uses_signed_scope():
    database_url = getattr(settings, "DATABASE_URL", None)
    if not database_url:
        pytest.skip("PostgreSQL smoke path unavailable: DATABASE_URL is not set")

    user_id = f"data_smoke_user_{uuid.uuid4().hex[:12]}"
    organization_id = f"data_smoke_org_{uuid.uuid4().hex[:12]}"
    workspace_id = f"workspace_{organization_id}"
    rival_user_id = f"data_rival_user_{uuid.uuid4().hex[:12]}"
    rival_organization_id = f"data_rival_org_{uuid.uuid4().hex[:12]}"
    rival_workspace_id = f"workspace_{rival_organization_id}"
    webdav_uid = f"webdav_src_data_{uuid.uuid4().hex[:18]}"
    rival_webdav_uid = f"webdav_src_data_rival_{uuid.uuid4().hex[:12]}"
    folder_uid = f"webdav_folder_data_{uuid.uuid4().hex[:18]}"
    event_uid = f"connector_evt_data_{uuid.uuid4().hex[:18]}"
    other_workspace_event_uid = f"connector_evt_other_{uuid.uuid4().hex[:18]}"

    ids = {
        "user_id": user_id,
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "rival_user_id": rival_user_id,
        "rival_organization_id": rival_organization_id,
        "rival_workspace_id": rival_workspace_id,
        "webdav_uid": webdav_uid,
        "rival_webdav_uid": rival_webdav_uid,
        "folder_uid": folder_uid,
        "event_uid": event_uid,
        "other_workspace_event_uid": other_workspace_event_uid,
    }

    engine = create_async_engine(database_url, echo=False)
    try:
        async with engine.begin() as conn:
            await _seed_smoke_test_data(conn, ids)
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

    previous_secret = settings.AUTH_SESSION_HMAC_SECRET
    original_overrides = dict(app.dependency_overrides)
    settings.AUTH_SESSION_HMAC_SECRET = SecretStr(TEST_SESSION_HMAC_SECRET)
    token = _signed_session_token(
        _valid_session_payload(
            sub=user_id,
            org=organization_id,
            workspace=workspace_id,
        )
    )
    app.dependency_overrides[get_db] = override_real_db
    app.dependency_overrides.pop(get_auth_context, None)
    app.dependency_overrides.pop(get_current_user, None)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            response = await client.get("/api/data/quality-surface")
    finally:
        settings.AUTH_SESSION_HMAC_SECRET = previous_secret
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        async with engine.begin() as conn:
            await _teardown_smoke_test_data(conn, ids)
        await engine.dispose()

    assert response.status_code == 200, response.text
    data = response.json()
    source_ids = {source["source_id"] for source in data["repositories"]}
    assert webdav_uid in source_ids
    assert folder_uid in source_ids
    assert rival_webdav_uid not in response.text
    quality_by_key = {check["check_key"]: check for check in data["quality_checks"]}
    assert quality_by_key["thread_id_integrity"]["issue_count"] == 1
    assert quality_by_key["dedupe_fingerprint"]["issue_count"] == 1
    assert quality_by_key["attachment_content"]["issue_count"] == 1
    assert event_uid in {event["event_uid"] for event in data["connector_events"]}
    asset_names = {asset["display_name"] for asset in data["repository_assets"]}
    assert {"ready.txt", "blank.txt"} <= asset_names
    assert "rival.txt" not in response.text
    assets_by_name = {
        asset["display_name"]: asset for asset in data["repository_assets"]
    }
    assert assets_by_name["ready.txt"]["state_code"] == "ready"
    assert assets_by_name["blank.txt"]["state_code"] == "needs_attention"
    assert assets_by_name["ready.txt"]["asset_key"].startswith("asset_")
    assert assets_by_name["ready.txt"]["thread_key"].startswith("thread_")
    assert other_workspace_event_uid not in response.text
    assert "account_id" not in response.text
    assert "encrypted-data-secret" not in response.text
    assert "data@example.com" not in response.text
