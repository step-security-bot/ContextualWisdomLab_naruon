from datetime import datetime, timezone
import hashlib
from typing import Literal, NamedTuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from api.auth import AuthContext, get_auth_context, is_admin_role
from api.common.scopes import connector_scope_statement
from api.runner_ws import manager as runner_manager
from core.config import settings
from db.models import (
    Attachment,
    ConnectorSignalEvent,
    Document,
    Email,
    ProjectFolder,
    WebdavAccount,
)
from db.session import get_db
from services.webdav_service import webdav_service

router = APIRouter(prefix="/api/data", tags=["data"])

DATA_VECTOR_DIMENSIONS = 1536
WEB_DAV_ERROR_STATUS_CODES = {
    "no_webdav_account": 422,
    "webdav_account_not_found": 422,
}
SurfaceStatus = Literal[
    "ready",
    "running",
    "needs_attention",
    "pending",
    "no_source",
]
QualityStatus = Literal["pass", "needs_attention", "pending"]
RepositoryAssetState = Literal["ready", "needs_attention"]
RepositoryType = Literal[
    "webdav_account",
    "project_folder",
    "email_repository",
    "attachment_repository",
    "document_repository",
]
EmailScopeFilter = tuple[ColumnElement[bool], ColumnElement[bool]]
AttachmentAssetRow = Row[tuple[Attachment, Email]]


class EmailQualityStats(NamedTuple):
    count: int
    missing_thread_count: int
    missing_fingerprint_count: int
    embedded_count: int


class AttachmentQualityStats(NamedTuple):
    count: int
    blank_content_count: int
    embedded_count: int


class DataRepositorySummary(BaseModel):
    source_id: str
    repository_type: RepositoryType
    display_name: str
    object_count: int
    writeback_enabled: bool | None
    evidence_source: str
    provider_write_executed: bool


class DataRepositoryAsset(BaseModel):
    asset_key: str
    asset_type: Literal["email_attachment", "workspace_document"]
    display_name: str
    source_label: str
    state_code: RepositoryAssetState
    detail_text: str
    content_chars: int
    captured_at: str
    evidence_source: str
    thread_key: str
    provider_write_executed: bool


class DataPipelineStage(BaseModel):
    stage_key: str
    display_name: str
    status_code: SurfaceStatus
    progress_percent: int
    evidence_source: str
    detail_text: str
    provider_write_executed: bool


class DataEmbeddingCollection(BaseModel):
    collection_key: str
    display_name: str
    object_count: int
    embedded_count: int
    embedding_model: str
    vector_dimensions: int
    status_code: SurfaceStatus
    evidence_source: str
    provider_write_executed: bool


class DataQualityCheck(BaseModel):
    check_key: str
    display_name: str
    status_code: QualityStatus
    issue_count: int
    total_count: int
    evidence_source: str
    detail_text: str
    provider_write_executed: bool


class DataConnectorEvent(BaseModel):
    event_uid: str
    signal_key: str
    state_code: str
    detail_text: str | None
    observed_at: str


class DataDocumentUploadRequest(BaseModel):
    document_name: str = Field(min_length=1, max_length=240)
    document_type: str = Field(min_length=1, max_length=120)
    document_content: str = Field(default="", max_length=2_000_000)


class DataDocumentWebdavMaterializationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_source_id: str | None = None
    execute_provider: bool = False


class DataDocumentActionResponse(BaseModel):
    document_id: str
    workspace_id: str
    document_name: str
    document_type: str
    document_status: str
    content_chars: int
    provider_write_executed: bool
    provenance: Literal["server-authoritative"]
    audit_event: str
    message: str


class DataDocumentWebdavMaterializationResponse(BaseModel):
    intent: Literal["document_webdav_materialization"]
    status: str
    document_id: str
    workspace_id: str
    document_name: str
    document_type: str
    source_id: str | None
    target_label: str | None
    target_path: str
    requires_if_match: bool
    if_match: str | None = None
    provenance: Literal["server-authoritative"]
    provider_write_executed: bool
    audit_event: str
    runner_request_id: str | None = None
    provider_status: int | None = None
    error_code: str | None = None
    retry_item_uid: str | None = None
    message: str


class DataQualitySurfaceResponse(BaseModel):
    workspace_id: str
    organization_id: str | None
    audit_event: Literal["data.quality_surface.viewed"]
    provider_write_executed: bool
    repositories: list[DataRepositorySummary]
    repository_assets: list[DataRepositoryAsset]
    pipeline_stages: list[DataPipelineStage]
    embedding_collections: list[DataEmbeddingCollection]
    quality_checks: list[DataQualityCheck]
    connector_events: list[DataConnectorEvent]


def _datetime_to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_display_text(value: str | None, fallback: str) -> str:
    cleaned = (value or fallback).replace("<", "").replace(">", "").strip()
    return " ".join(cleaned.split())[:120] or fallback


def _safe_document_type(value: str) -> str:
    return _safe_display_text(value, "application/octet-stream")[:120]


def _safe_path_segment(value: str | None, fallback: str) -> str:
    cleaned = _safe_display_text(value, fallback)
    cleaned = cleaned.replace("\x00", "").replace("/", "-").replace("\\", "-")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    cleaned = cleaned.strip(" .-_")
    return cleaned[:96] or fallback


def _materialized_document_name(document: Document) -> str:
    return _safe_path_segment(document.document_name, "workspace-document")


def _materialized_document_target_path(document: Document) -> str:
    digest = hashlib.sha256(document.document_id.encode("utf-8")).hexdigest()[:8]
    filename = f"{_materialized_document_name(document)}-{digest}.md"
    return f"/Naruon/Data/{filename}"


def _materialized_document_content(document: Document) -> str:
    return (document.document_content or "").strip()


def _document_content_chars(document: Document) -> int:
    return len((document.document_content or "").strip())


def _document_response(
    document: Document,
    *,
    audit_event: str,
    message: str,
) -> DataDocumentActionResponse:
    return DataDocumentActionResponse(
        document_id=document.document_id,
        workspace_id=document.workspace_id,
        document_name=document.document_name,
        document_type=document.document_type,
        document_status=document.document_status,
        content_chars=_document_content_chars(document),
        provider_write_executed=False,
        provenance="server-authoritative",
        audit_event=audit_event,
        message=message,
    )


def _document_webdav_materialization_response(
    document: Document,
    source_result: dict,
) -> dict:
    return {
        "intent": "document_webdav_materialization",
        "status": "intent_ready",
        "document_id": document.document_id,
        "workspace_id": document.workspace_id,
        "document_name": _materialized_document_name(document),
        "document_type": document.document_type,
        "source_id": source_result["source_id"],
        "target_label": source_result["target_label"],
        "target_path": _materialized_document_target_path(document),
        "requires_if_match": source_result["requires_if_match"],
        "if_match": source_result.get("if_match"),
        "provenance": "server-authoritative",
        "provider_write_executed": False,
        "audit_event": "data.document.webdav_materialization_intent.created",
        "runner_request_id": None,
        "provider_status": None,
        "error_code": None,
        "retry_item_uid": None,
        "message": (
            "Workspace document WebDAV materialization intent recorded; "
            "no provider write executed."
        ),
    }


def _document_webdav_runner_command(
    document: Document, intent_result: dict
) -> dict[str, object]:
    return {
        "action": "write_webdav",
        "account": intent_result["source_id"],
        "source_id": intent_result["source_id"],
        "target_path": intent_result["target_path"],
        "if_match": intent_result.get("if_match"),
        "content_type": "text/markdown; charset=utf-8",
        "content": _materialized_document_content(document),
    }


def _merge_document_webdav_dispatch_result(
    intent_result: dict,
    dispatch_result: dict,
) -> dict:
    result = dict(intent_result)
    result["status"] = str(dispatch_result.get("status") or "error")
    result["provider_write_executed"] = bool(
        dispatch_result.get("provider_write_executed", False)
    )
    result["runner_request_id"] = dispatch_result.get("request_id")
    result["provider_status"] = dispatch_result.get("provider_status")
    result["error_code"] = dispatch_result.get("error_code")
    result["retry_item_uid"] = dispatch_result.get("retry_item_uid")
    result["audit_event"] = (
        "data.document.webdav_materialization.executed"
        if result["provider_write_executed"]
        else "data.document.webdav_materialization.dispatch_failed"
    )
    result["message"] = (
        "Workspace document WebDAV materialization executed by the connector."
        if result["provider_write_executed"]
        else "Workspace document WebDAV materialization dispatch failed."
    )
    return result


def _opaque_asset_key(email: Email, attachment: Attachment) -> str:
    digest = hashlib.sha256(
        "|".join(
            [
                email.user_id,
                email.organization_id,
                email.message_id,
                attachment.filename,
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"asset_{digest[:24]}"


def _opaque_thread_key(email: Email) -> str:
    if not email.thread_id:
        return "thread_missing"
    digest = hashlib.sha256(email.thread_id.encode("utf-8")).hexdigest()
    return f"thread_{digest[:16]}"


def _can_read_org_scope(auth_context: AuthContext) -> bool:
    return is_admin_role(auth_context.role) and auth_context.organization_id is not None


def _owner_scope_statement(model, auth_context: AuthContext):
    statement = select(model)
    if hasattr(model, "workspace_id"):
        statement = statement.where(model.workspace_id == auth_context.workspace_id)
    if _can_read_org_scope(auth_context):
        return statement.where(model.organization_id == auth_context.organization_id)
    organization_filter = (
        model.organization_id == auth_context.organization_id
        if auth_context.organization_id is not None
        else model.organization_id.is_(None)
    )
    return statement.where(model.user_id == auth_context.user_id, organization_filter)


def _email_scope_filter(auth_context: AuthContext) -> EmailScopeFilter:
    if _can_read_org_scope(auth_context):
        organization_filter = Email.organization_id == auth_context.organization_id
        return (organization_filter, organization_filter)
    organization_filter = (
        Email.organization_id == auth_context.organization_id
        if auth_context.organization_id is not None
        else Email.organization_id.is_(None)
    )
    return (Email.user_id == auth_context.user_id, organization_filter)


async def _scoped_rows(db: AsyncSession, statement):
    result = await db.execute(statement)
    return list(result.scalars().all())


async def _count_scalar(db: AsyncSession, statement) -> int:
    result = await db.execute(statement)
    return int(result.scalar_one() or 0)


async def _get_workspace_document(
    db: AsyncSession,
    auth_context: AuthContext,
    document_id: str,
) -> Document:
    result = await db.execute(
        select(Document).where(
            Document.document_id == document_id,
            Document.workspace_id == auth_context.workspace_id,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _status_from_ratio(total_count: int, ready_count: int) -> SurfaceStatus:
    if total_count <= 0:
        return "pending"
    if ready_count <= 0:
        return "needs_attention"
    if ready_count < total_count:
        return "running"
    return "ready"


def _progress_percent(total_count: int, ready_count: int) -> int:
    if total_count <= 0:
        return 0
    return max(0, min(100, round((ready_count / total_count) * 100)))


def _quality_status(total_count: int, issue_count: int) -> QualityStatus:
    if total_count <= 0:
        return "pending"
    return "pass" if issue_count == 0 else "needs_attention"


def _quality_detail(
    *,
    total_count: int,
    issue_count: int,
    ready_text: str,
    empty_text: str,
    issue_text: str,
) -> str:
    if total_count <= 0:
        return empty_text
    if issue_count == 0:
        return ready_text
    return issue_text


def _repository_summaries(
    webdav_accounts: list[WebdavAccount],
    project_folders: list[ProjectFolder],
    email_count: int,
    attachment_count: int,
    document_count: int,
) -> list[DataRepositorySummary]:
    repositories: list[DataRepositorySummary] = [
        DataRepositorySummary(
            source_id="email_repository",
            repository_type="email_repository",
            display_name="Scoped email archive",
            object_count=email_count,
            writeback_enabled=None,
            evidence_source="emails",
            provider_write_executed=False,
        ),
        DataRepositorySummary(
            source_id="attachment_repository",
            repository_type="attachment_repository",
            display_name="Scoped attachment archive",
            object_count=attachment_count,
            writeback_enabled=None,
            evidence_source="attachments",
            provider_write_executed=False,
        ),
        DataRepositorySummary(
            source_id="document_repository",
            repository_type="document_repository",
            display_name="Scoped document repository",
            object_count=document_count,
            writeback_enabled=None,
            evidence_source="documents",
            provider_write_executed=False,
        ),
    ]
    repositories.extend(
        DataRepositorySummary(
            source_id=account.source_uid,
            repository_type="webdav_account",
            display_name="Customer WebDAV account",
            object_count=0,
            writeback_enabled=bool(account.writeback_enabled),
            evidence_source="webdav_accounts",
            provider_write_executed=False,
        )
        for account in webdav_accounts
    )
    repositories.extend(
        DataRepositorySummary(
            source_id=folder.folder_uid,
            repository_type="project_folder",
            display_name=folder.project_name,
            object_count=0,
            writeback_enabled=None,
            evidence_source="project_folders",
            provider_write_executed=False,
        )
        for folder in project_folders
    )
    return repositories


def _attachment_repository_assets(
    rows: list[AttachmentAssetRow],
) -> list[DataRepositoryAsset]:
    assets: list[DataRepositoryAsset] = []
    for attachment, email in rows:
        content_chars = len((attachment.content or "").strip())
        has_thread = bool((email.thread_id or "").strip())
        state_code: RepositoryAssetState = (
            "ready" if content_chars > 0 and has_thread else "needs_attention"
        )
        detail_parts: list[str] = []
        if content_chars <= 0:
            detail_parts.append("content extraction pending")
        if not has_thread:
            detail_parts.append("canonical thread pending")
        if not detail_parts:
            detail_parts.append("content and thread evidence ready")
        assets.append(
            DataRepositoryAsset(
                asset_key=_opaque_asset_key(email, attachment),
                asset_type="email_attachment",
                display_name=_safe_display_text(
                    attachment.filename, "email attachment"
                ),
                source_label=_safe_display_text(email.subject, "untitled email"),
                state_code=state_code,
                detail_text=", ".join(detail_parts),
                content_chars=content_chars,
                captured_at=_datetime_to_utc_iso(email.date),
                evidence_source="attachments.content, emails.thread_id",
                thread_key=_opaque_thread_key(email),
                provider_write_executed=False,
            )
        )
    return assets


def _document_repository_assets(documents: list[Document]) -> list[DataRepositoryAsset]:
    assets: list[DataRepositoryAsset] = []
    for document in documents:
        content_chars = _document_content_chars(document)
        pending_statuses = {"embedding_pending", "hwp_conversion_pending"}
        state_code: RepositoryAssetState = (
            "needs_attention"
            if content_chars <= 0 or document.document_status in pending_statuses
            else "ready"
        )
        assets.append(
            DataRepositoryAsset(
                asset_key=document.document_id,
                asset_type="workspace_document",
                display_name=_safe_display_text(
                    document.document_name,
                    "workspace document",
                ),
                source_label="Workspace document",
                state_code=state_code,
                detail_text=f"document status: {document.document_status}",
                content_chars=content_chars,
                captured_at=_datetime_to_utc_iso(document.created_at),
                evidence_source="documents.document_status",
                thread_key="workspace_document",
                provider_write_executed=False,
            )
        )
    return assets


def _pipeline_stages(
    *,
    source_count: int,
    email_count: int,
    attachment_count: int,
    missing_thread_count: int,
    embedded_total: int,
    object_total: int,
    connector_event_count: int,
) -> list[DataPipelineStage]:
    thread_ready = max(0, email_count - missing_thread_count)
    return [
        DataPipelineStage(
            stage_key="source_registry",
            display_name="Source registry",
            status_code="ready" if source_count > 0 else "no_source",
            progress_percent=100 if source_count > 0 else 0,
            evidence_source="webdav_accounts, project_folders",
            detail_text=f"{source_count} customer-owned sources are in scope.",
            provider_write_executed=False,
        ),
        DataPipelineStage(
            stage_key="ingestion_inventory",
            display_name="Ingestion inventory",
            status_code="ready" if email_count + attachment_count > 0 else "no_source",
            progress_percent=100 if email_count + attachment_count > 0 else 0,
            evidence_source="emails, attachments",
            detail_text=(
                f"{email_count} emails and {attachment_count} attachments "
                "are visible in the signed workspace scope."
            ),
            provider_write_executed=False,
        ),
        DataPipelineStage(
            stage_key="canonical_threading",
            display_name="Canonical threading",
            status_code=_status_from_ratio(email_count, thread_ready),
            progress_percent=_progress_percent(email_count, thread_ready),
            evidence_source="emails.thread_id",
            detail_text=f"{missing_thread_count} emails need canonical thread ids.",
            provider_write_executed=False,
        ),
        DataPipelineStage(
            stage_key="embedding_inventory",
            display_name="Embedding inventory",
            status_code=_status_from_ratio(object_total, embedded_total),
            progress_percent=_progress_percent(object_total, embedded_total),
            evidence_source="emails.embedding, attachments.embedding",
            detail_text=f"{embedded_total} of {object_total} objects have vectors.",
            provider_write_executed=False,
        ),
        DataPipelineStage(
            stage_key="connector_observability",
            display_name="Connector observability",
            status_code="ready" if connector_event_count > 0 else "pending",
            progress_percent=100 if connector_event_count > 0 else 0,
            evidence_source="connector_signal_events",
            detail_text=f"{connector_event_count} connector events are in scope.",
            provider_write_executed=False,
        ),
    ]


def _embedding_collections(
    *,
    email_count: int,
    embedded_email_count: int,
    attachment_count: int,
    embedded_attachment_count: int,
) -> list[DataEmbeddingCollection]:
    model_name = settings.OPENAI_EMBEDDING_MODEL
    return [
        DataEmbeddingCollection(
            collection_key="emails_embedding",
            display_name="Email vectors",
            object_count=email_count,
            embedded_count=embedded_email_count,
            embedding_model=model_name,
            vector_dimensions=DATA_VECTOR_DIMENSIONS,
            status_code=_status_from_ratio(email_count, embedded_email_count),
            evidence_source="emails.embedding",
            provider_write_executed=False,
        ),
        DataEmbeddingCollection(
            collection_key="attachments_embedding",
            display_name="Attachment vectors",
            object_count=attachment_count,
            embedded_count=embedded_attachment_count,
            embedding_model=model_name,
            vector_dimensions=DATA_VECTOR_DIMENSIONS,
            status_code=_status_from_ratio(
                attachment_count,
                embedded_attachment_count,
            ),
            evidence_source="attachments.embedding",
            provider_write_executed=False,
        ),
    ]


def _check_thread_id_integrity(
    email_count: int, missing_thread_count: int
) -> DataQualityCheck:
    return DataQualityCheck(
        check_key="thread_id_integrity",
        display_name="Thread id integrity",
        status_code=_quality_status(email_count, missing_thread_count),
        issue_count=missing_thread_count,
        total_count=email_count,
        evidence_source="emails.thread_id",
        detail_text=_quality_detail(
            total_count=email_count,
            issue_count=missing_thread_count,
            ready_text="All scoped emails have canonical thread ids.",
            empty_text="No scoped emails are available yet.",
            issue_text="Some scoped emails need canonical thread ids.",
        ),
        provider_write_executed=False,
    )


def _check_dedupe_fingerprint(
    email_count: int, missing_fingerprint_count: int
) -> DataQualityCheck:
    return DataQualityCheck(
        check_key="dedupe_fingerprint",
        display_name="Dedupe fingerprint",
        status_code=_quality_status(email_count, missing_fingerprint_count),
        issue_count=missing_fingerprint_count,
        total_count=email_count,
        evidence_source="emails.fingerprint",
        detail_text=_quality_detail(
            total_count=email_count,
            issue_count=missing_fingerprint_count,
            ready_text="All scoped emails have duplicate-detection fingerprints.",
            empty_text="No scoped emails are available yet.",
            issue_text="Some scoped emails need duplicate-detection fingerprints.",
        ),
        provider_write_executed=False,
    )


def _check_attachment_content(
    attachment_count: int, blank_attachment_count: int
) -> DataQualityCheck:
    return DataQualityCheck(
        check_key="attachment_content",
        display_name="Attachment content",
        status_code=_quality_status(attachment_count, blank_attachment_count),
        issue_count=blank_attachment_count,
        total_count=attachment_count,
        evidence_source="attachments.content",
        detail_text=_quality_detail(
            total_count=attachment_count,
            issue_count=blank_attachment_count,
            ready_text="All scoped attachments have extracted content.",
            empty_text="No scoped attachments are available yet.",
            issue_text="Some scoped attachments need extracted content.",
        ),
        provider_write_executed=False,
    )


def _check_source_registry_coverage(source_count: int) -> DataQualityCheck:
    return DataQualityCheck(
        check_key="source_registry",
        display_name="Source registry coverage",
        status_code="pass" if source_count > 0 else "pending",
        issue_count=0 if source_count > 0 else 1,
        total_count=max(1, source_count),
        evidence_source="webdav_accounts, project_folders",
        detail_text=(
            "Customer-owned repositories are visible."
            if source_count > 0
            else "No customer-owned repositories are visible yet."
        ),
        provider_write_executed=False,
    )


def _check_connector_signal_coverage(connector_event_count: int) -> DataQualityCheck:
    return DataQualityCheck(
        check_key="connector_signal",
        display_name="Connector signal coverage",
        status_code="pass" if connector_event_count > 0 else "pending",
        issue_count=0 if connector_event_count > 0 else 1,
        total_count=max(1, connector_event_count),
        evidence_source="connector_signal_events",
        detail_text=(
            "Connector evidence is visible for this workspace."
            if connector_event_count > 0
            else "Connector jobs have not emitted workspace evidence yet."
        ),
        provider_write_executed=False,
    )


def _quality_checks(
    *,
    email_count: int,
    attachment_count: int,
    missing_thread_count: int,
    missing_fingerprint_count: int,
    blank_attachment_count: int,
    source_count: int,
    connector_event_count: int,
) -> list[DataQualityCheck]:
    return [
        _check_thread_id_integrity(
            email_count=email_count,
            missing_thread_count=missing_thread_count,
        ),
        _check_dedupe_fingerprint(
            email_count=email_count,
            missing_fingerprint_count=missing_fingerprint_count,
        ),
        _check_attachment_content(
            attachment_count=attachment_count,
            blank_attachment_count=blank_attachment_count,
        ),
        _check_source_registry_coverage(source_count),
        _check_connector_signal_coverage(connector_event_count),
    ]


@router.post("/documents", response_model=DataDocumentActionResponse)
async def upload_data_document(
    request: DataDocumentUploadRequest,
    auth_context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> DataDocumentActionResponse:
    document = Document(
        workspace_id=auth_context.workspace_id,
        document_name=_safe_display_text(request.document_name, "workspace document"),
        document_type=_safe_document_type(request.document_type),
        document_content=request.document_content,
        document_status="uploaded",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return _document_response(
        document,
        audit_event="data.document.uploaded",
        message="Document stored in the signed workspace scope.",
    )


@router.post(
    "/documents/{document_id}/reparse", response_model=DataDocumentActionResponse
)
async def reparse_data_document(
    document_id: str,
    auth_context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> DataDocumentActionResponse:
    document = await _get_workspace_document(db, auth_context, document_id)
    document.document_status = "parsed"
    await db.commit()
    await db.refresh(document)
    return _document_response(
        document,
        audit_event="data.document.reparsed",
        message="Document parse metadata refreshed in the signed workspace scope.",
    )


@router.post(
    "/documents/{document_id}/embedding-regeneration-intent",
    response_model=DataDocumentActionResponse,
)
async def create_document_embedding_regeneration_intent(
    document_id: str,
    auth_context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> DataDocumentActionResponse:
    document = await _get_workspace_document(db, auth_context, document_id)
    document.document_status = "embedding_pending"
    await db.commit()
    await db.refresh(document)
    return _document_response(
        document,
        audit_event="data.document.embedding_regeneration_intent",
        message="Embedding regeneration intent recorded; no provider write executed.",
    )


@router.post(
    "/documents/{document_id}/hwp-conversion-intent",
    response_model=DataDocumentActionResponse,
)
async def create_document_hwp_conversion_intent(
    document_id: str,
    auth_context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> DataDocumentActionResponse:
    document = await _get_workspace_document(db, auth_context, document_id)
    document.document_status = "hwp_conversion_pending"
    await db.commit()
    await db.refresh(document)
    return _document_response(
        document,
        audit_event="data.document.hwp_conversion_intent",
        message="HWP conversion intent recorded; no provider write executed.",
    )


@router.post(
    "/documents/{document_id}/webdav-materialization-intent",
    response_model=DataDocumentWebdavMaterializationResponse,
)
async def create_document_webdav_materialization_intent(
    document_id: str,
    request: DataDocumentWebdavMaterializationRequest,
    auth_context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> DataDocumentWebdavMaterializationResponse:
    document = await _get_workspace_document(db, auth_context, document_id)
    if not _materialized_document_content(document):
        raise HTTPException(
            status_code=422,
            detail="Workspace document has no materializable content.",
        )

    source_result = await webdav_service.determine_webdav_writeback_intent_from_db(
        db,
        auth_context.user_id,
        auth_context.organization_id,
        auth_context.workspace_id,
        target_source_id=request.target_source_id,
    )
    if source_result.get("status") == "error":
        status_code = WEB_DAV_ERROR_STATUS_CODES.get(
            str(source_result.get("error_code") or ""),
            422,
        )
        raise HTTPException(
            status_code=status_code, detail=source_result.get("message")
        )

    result = _document_webdav_materialization_response(document, source_result)
    if request.execute_provider:
        dispatch_result = await runner_manager.dispatch_command(
            auth_context.organization_id,
            auth_context.workspace_id,
            _document_webdav_runner_command(document, result),
        )
        result = _merge_document_webdav_dispatch_result(result, dispatch_result)
    return DataDocumentWebdavMaterializationResponse(**result)


async def _get_email_stats(
    db: AsyncSession,
    email_scope: EmailScopeFilter,
) -> EmailQualityStats:
    # ⚡ Bolt Optimization: Batching scalar counts using CASE
    # Impact: Reduces 7 sequential database queries down to 2, drastically cutting
    # latency from network roundtrips when fetching quality surface metrics.
    email_stats_result = await db.execute(
        select(
            func.count(Email.id),
            func.count(
                case((or_(Email.thread_id.is_(None), Email.thread_id == ""), 1))
            ),
            func.count(
                case((or_(Email.fingerprint.is_(None), Email.fingerprint == ""), 1))
            ),
            func.count(case((Email.embedding.is_not(None), 1))),
        ).where(*email_scope)
    )
    email_stats = email_stats_result.one_or_none()
    email_count = email_stats[0] if email_stats else 0
    missing_thread_count = email_stats[1] if email_stats else 0
    missing_fingerprint_count = email_stats[2] if email_stats else 0
    embedded_email_count = email_stats[3] if email_stats else 0
    return EmailQualityStats(
        count=email_count,
        missing_thread_count=missing_thread_count,
        missing_fingerprint_count=missing_fingerprint_count,
        embedded_count=embedded_email_count,
    )


async def _get_attachment_stats(
    db: AsyncSession,
    email_scope: EmailScopeFilter,
) -> AttachmentQualityStats:
    attachment_stats_result = await db.execute(
        select(
            func.count(Attachment.id),
            func.count(
                case(
                    (
                        or_(
                            Attachment.content.is_(None),
                            func.length(func.trim(Attachment.content)) == 0,
                        ),
                        1,
                    )
                )
            ),
            func.count(case((Attachment.embedding.is_not(None), 1))),
        )
        .join(Email)
        .where(*email_scope)
    )
    attachment_stats = attachment_stats_result.one_or_none()
    attachment_count = attachment_stats[0] if attachment_stats else 0
    blank_attachment_count = attachment_stats[1] if attachment_stats else 0
    embedded_attachment_count = attachment_stats[2] if attachment_stats else 0
    return AttachmentQualityStats(
        count=attachment_count,
        blank_content_count=blank_attachment_count,
        embedded_count=embedded_attachment_count,
    )


async def _get_attachment_assets(
    db: AsyncSession,
    email_scope: EmailScopeFilter,
) -> list[AttachmentAssetRow]:
    attachment_asset_result = await db.execute(
        select(Attachment, Email)
        .join(Email)
        .where(*email_scope)
        .order_by(Email.date.desc(), Attachment.filename.asc())
        .limit(8)
    )
    return list(attachment_asset_result.all())


async def _get_connector_events(
    db: AsyncSession,
    auth_context: AuthContext,
) -> list[ConnectorSignalEvent]:
    connector_statement = connector_scope_statement(auth_context)
    if connector_statement is None:
        return []
    return await _scoped_rows(db, connector_statement)


@router.get("/quality-surface", response_model=DataQualitySurfaceResponse)
async def get_data_quality_surface(
    auth_context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> DataQualitySurfaceResponse:
    webdav_accounts = await _scoped_rows(
        db,
        _owner_scope_statement(WebdavAccount, auth_context).order_by(
            WebdavAccount.created_at.asc(),
            WebdavAccount.source_uid.asc(),
        ),
    )
    project_folders = await _scoped_rows(
        db,
        _owner_scope_statement(ProjectFolder, auth_context).order_by(
            ProjectFolder.created_at.asc(),
            ProjectFolder.folder_uid.asc(),
        ),
    )
    documents = await _scoped_rows(
        db,
        select(Document)
        .where(Document.workspace_id == auth_context.workspace_id)
        .order_by(Document.created_at.desc(), Document.document_id.asc())
        .limit(8),
    )
    email_scope = _email_scope_filter(auth_context)

    email_stats = await _get_email_stats(db, email_scope)
    attachment_stats = await _get_attachment_stats(db, email_scope)
    email_count = email_stats.count
    missing_thread_count = email_stats.missing_thread_count
    missing_fingerprint_count = email_stats.missing_fingerprint_count
    embedded_email_count = email_stats.embedded_count
    attachment_count = attachment_stats.count
    blank_attachment_count = attachment_stats.blank_content_count
    embedded_attachment_count = attachment_stats.embedded_count

    connector_events = await _get_connector_events(db, auth_context)
    attachment_asset_rows = await _get_attachment_assets(db, email_scope)

    source_count = len(webdav_accounts) + len(project_folders)
    embedded_total = embedded_email_count + embedded_attachment_count
    object_total = email_count + attachment_count + len(documents)
    return DataQualitySurfaceResponse(
        workspace_id=auth_context.workspace_id,
        organization_id=auth_context.organization_id,
        audit_event="data.quality_surface.viewed",
        provider_write_executed=False,
        repositories=_repository_summaries(
            webdav_accounts,
            project_folders,
            email_count,
            attachment_count,
            len(documents),
        ),
        repository_assets=[
            *_document_repository_assets(documents),
            *_attachment_repository_assets(attachment_asset_rows),
        ],
        pipeline_stages=_pipeline_stages(
            source_count=source_count,
            email_count=email_count,
            attachment_count=attachment_count,
            missing_thread_count=missing_thread_count,
            embedded_total=embedded_total,
            object_total=object_total,
            connector_event_count=len(connector_events),
        ),
        embedding_collections=_embedding_collections(
            email_count=email_count,
            embedded_email_count=embedded_email_count,
            attachment_count=attachment_count,
            embedded_attachment_count=embedded_attachment_count,
        ),
        quality_checks=_quality_checks(
            email_count=email_count,
            attachment_count=attachment_count,
            missing_thread_count=missing_thread_count,
            missing_fingerprint_count=missing_fingerprint_count,
            blank_attachment_count=blank_attachment_count,
            source_count=source_count,
            connector_event_count=len(connector_events),
        ),
        connector_events=[
            DataConnectorEvent(
                event_uid=event.event_uid,
                signal_key=event.signal_key,
                state_code=event.state_code,
                detail_text=event.detail_text,
                observed_at=_datetime_to_utc_iso(event.observed_at),
            )
            for event in connector_events
        ],
    )
