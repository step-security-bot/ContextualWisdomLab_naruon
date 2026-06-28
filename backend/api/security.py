from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import (
    AuthContext,
    get_auth_context,
    is_admin_role,
)
from api.common.scopes import connector_scope_statement
from db.models import (
    CalendarWritebackSource,
    ConnectorSignalEvent,
    SecurityAuditEvent,
    WebdavAccount,
)
from db.session import get_db
from core.config import settings
from services.access_policy import AccessRequest, ResourcePolicy, evaluate_access

router = APIRouter(prefix="/api/security", tags=["security"])

SourceType = Literal["caldav_source", "carddav_source", "webdav_repository"]
ScopeKind = Literal["organization", "personal"]
DecisionReason = Literal[
    "allowed",
    "organization_denied",
    "workspace_denied",
    "data_region_denied",
    "consent_denied",
    "ownership_denied",
    "rbac_denied",
]


class ViewerContext(BaseModel):
    role: str
    scope_kind: ScopeKind


class PolicyDecisionSummary(BaseModel):
    resource_label: str
    resource_type: str
    allowed: bool
    reason: DecisionReason
    evidence_label: str


class GovernanceSource(BaseModel):
    source_type: SourceType
    source_label: str
    scope_kind: ScopeKind
    capabilities: list[str]
    writeback_enabled: bool
    policy_decision: PolicyDecisionSummary
    last_observed_at: str | None


class ConnectorEvidence(BaseModel):
    state_code: str
    evidence_label: str
    observed_at: str


class DurableAuditEvidence(BaseModel):
    actor_role: str
    scope_kind: ScopeKind
    event_action: str
    resource_type: str
    evidence_label: str
    observed_at: str


class ExternalShareReview(BaseModel):
    source_type: SourceType
    review_label: str
    exposure_level: Literal["internal", "external_writeback"]
    decision_reason: DecisionReason


class PolicyOrderStep(BaseModel):
    display_name: str
    evidence_label: str


class SecurityAccessSurfaceResponse(BaseModel):
    scope_kind: ScopeKind
    viewer: ViewerContext
    sources: list[GovernanceSource]
    connector_events: list[ConnectorEvidence]
    durable_audit_events: list[DurableAuditEvidence]
    policy_decisions: list[PolicyDecisionSummary]
    external_share_reviews: list[ExternalShareReview]
    policy_order: list[PolicyOrderStep]


def _datetime_to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _scope_kind(organization_id: str | None) -> ScopeKind:
    return "organization" if organization_id is not None else "personal"


def _evidence_label(evidence_source: str) -> str:
    if "webdav" in evidence_source.lower():
        return "webdav_source_evidence"
    if "calendar" in evidence_source.lower():
        return "calendar_source_evidence"
    if "access_policy" in evidence_source.lower():
        return "policy_engine_evidence"
    if "auth" in evidence_source.lower() or "session" in evidence_source.lower():
        return "signed_session_evidence"
    if "connector" in evidence_source.lower() or "runner" in evidence_source.lower():
        return "connector_observation_evidence"
    return "server_audit_evidence"


def _can_read_org_scope(auth_context: AuthContext) -> bool:
    return (
        is_admin_role(auth_context.role)
        and auth_context.organization_id is not None
    )


def _webdav_scope_statement(auth_context: AuthContext):
    statement = select(WebdavAccount).order_by(
        WebdavAccount.created_at.asc(),
        WebdavAccount.source_uid.asc(),
    )
    statement = statement.where(WebdavAccount.workspace_id == auth_context.workspace_id)
    if _can_read_org_scope(auth_context):
        return statement.where(
            WebdavAccount.organization_id == auth_context.organization_id
        )
    organization_filter = (
        WebdavAccount.organization_id == auth_context.organization_id
        if auth_context.organization_id is not None
        else WebdavAccount.organization_id.is_(None)
    )
    return statement.where(
        WebdavAccount.user_id == auth_context.user_id,
        organization_filter,
    )


def _calendar_scope_statement(auth_context: AuthContext):
    statement = (
        select(CalendarWritebackSource)
        .where(
            CalendarWritebackSource.source_protocol.in_(("caldav", "carddav")),
            CalendarWritebackSource.workspace_id == auth_context.workspace_id,
        )
        .order_by(
            CalendarWritebackSource.created_at.asc(),
            CalendarWritebackSource.source_uid.asc(),
        )
    )
    if _can_read_org_scope(auth_context):
        return statement.where(
            CalendarWritebackSource.organization_id == auth_context.organization_id
        )
    organization_filter = (
        CalendarWritebackSource.organization_id == auth_context.organization_id
        if auth_context.organization_id is not None
        else CalendarWritebackSource.organization_id.is_(None)
    )
    return statement.where(
        CalendarWritebackSource.user_id == auth_context.user_id,
        organization_filter,
    )


def _durable_audit_scope_statement(auth_context: AuthContext):
    statement = (
        select(SecurityAuditEvent)
        .where(SecurityAuditEvent.workspace_id == auth_context.workspace_id)
        .order_by(SecurityAuditEvent.observed_at.desc())
        .limit(12)
    )
    if _can_read_org_scope(auth_context):
        return statement.where(
            SecurityAuditEvent.organization_id == auth_context.organization_id
        )
    organization_filter = (
        SecurityAuditEvent.organization_id == auth_context.organization_id
        if auth_context.organization_id is not None
        else SecurityAuditEvent.organization_id.is_(None)
    )
    return statement.where(
        SecurityAuditEvent.actor_user_id == auth_context.user_id,
        organization_filter,
    )


def _access_request(auth_context: AuthContext) -> AccessRequest:
    return AccessRequest(
        user_id=auth_context.user_id,
        role=auth_context.role,
        organization_id=auth_context.organization_id,
        group_ids=auth_context.group_ids,
        data_region=settings.DATA_REGION,
        consent_scopes=("mail.read", "calendar.read", "webdav.write"),
        workspace_id=auth_context.workspace_id,
    )


def _decision_summary(
    *,
    resource_label: str,
    resource_type: str,
    auth_context: AuthContext,
    resource: ResourcePolicy,
    evidence_source: str,
) -> PolicyDecisionSummary:
    decision = evaluate_access(_access_request(auth_context), resource)
    return PolicyDecisionSummary(
        resource_label=resource_label,
        resource_type=resource_type,
        allowed=decision.allowed,
        reason=decision.reason,
        evidence_label=_evidence_label(evidence_source),
    )


def _source_policy(
    auth_context: AuthContext,
    owner_id: str,
    organization_id: str | None,
    workspace_id: str,
    writeback_enabled: bool,
) -> ResourcePolicy:
    delegated_user_ids: tuple[str, ...] = (
        (auth_context.user_id,)
        if (
            is_admin_role(auth_context.role)
            and organization_id == auth_context.organization_id
        )
        else ()
    )
    required_consent = ("webdav.write",) if writeback_enabled else ()
    return ResourcePolicy(
        owner_id=owner_id,
        organization_id=organization_id,
        permitted_roles=("tenant_admin", "organization_admin", "group_admin", "member"),
        permitted_group_ids=auth_context.group_ids,
        data_region=settings.DATA_REGION,
        required_consent_scopes=required_consent,
        workspace_id=workspace_id,
        delegated_user_ids=delegated_user_ids,
    )


def _webdav_source(
    account: WebdavAccount, auth_context: AuthContext
) -> GovernanceSource:
    decision = _decision_summary(
        resource_label="WebDAV repository",
        resource_type="webdav_repository",
        auth_context=auth_context,
        resource=_source_policy(
            auth_context,
            account.user_id,
            account.organization_id,
            account.workspace_id,
            bool(account.writeback_enabled),
        ),
        evidence_source="webdav_accounts",
    )
    return GovernanceSource(
        source_type="webdav_repository",
        source_label="WebDAV repository",
        scope_kind=_scope_kind(account.organization_id),
        capabilities=["read", "write", "etag"] if account.writeback_enabled else ["read"],
        writeback_enabled=bool(account.writeback_enabled),
        policy_decision=decision,
        last_observed_at=_datetime_to_utc_iso(account.created_at),
    )


def _calendar_source(
    source: CalendarWritebackSource, auth_context: AuthContext
) -> GovernanceSource:
    source_type: SourceType = (
        "carddav_source" if source.source_protocol == "carddav" else "caldav_source"
    )
    decision = _decision_summary(
        resource_label=f"{source.provider_name} {source.source_protocol.upper()} source",
        resource_type=source_type,
        auth_context=auth_context,
        resource=_source_policy(
            auth_context,
            source.user_id,
            source.organization_id,
            source.workspace_id,
            bool(source.writeback_enabled),
        ),
        evidence_source="calendar_writeback_sources",
    )
    capabilities = ["read"]
    if source.writeback_enabled:
        capabilities.extend(["write", "etag"])
    return GovernanceSource(
        source_type=source_type,
        source_label=source.provider_name,
        scope_kind=_scope_kind(source.organization_id),
        capabilities=capabilities,
        writeback_enabled=bool(source.writeback_enabled),
        policy_decision=decision,
        last_observed_at=_datetime_to_utc_iso(source.created_at),
    )


def _connector_evidence(event: ConnectorSignalEvent) -> ConnectorEvidence:
    return ConnectorEvidence(
        state_code=event.state_code,
        evidence_label=_evidence_label("connector_signal_events"),
        observed_at=_datetime_to_utc_iso(event.observed_at),
    )


def _durable_audit_evidence(event: SecurityAuditEvent) -> DurableAuditEvidence:
    return DurableAuditEvidence(
        actor_role=event.actor_role,
        scope_kind=_scope_kind(event.organization_id),
        event_action=event.event_action,
        resource_type=event.resource_type,
        evidence_label=_evidence_label(event.evidence_source),
        observed_at=_datetime_to_utc_iso(event.observed_at),
    )


def _canonical_policy_decisions(
    auth_context: AuthContext,
    source_decisions: list[PolicyDecisionSummary],
) -> list[PolicyDecisionSummary]:
    decisions = list(source_decisions)
    decisions.append(
        _decision_summary(
            resource_label="Cross-organization provider secret",
            resource_type="provider_secret",
            auth_context=auth_context,
            resource=ResourcePolicy(
                owner_id=auth_context.user_id,
                organization_id="org-outside-scope",
                permitted_roles=("tenant_admin", "organization_admin"),
                permitted_group_ids=(),
                data_region=settings.DATA_REGION,
                required_consent_scopes=(),
                workspace_id=auth_context.workspace_id,
            ),
            evidence_source="access_policy.evaluate_access",
        )
    )
    decisions.append(
        _decision_summary(
            resource_label="Regional export outside policy",
            resource_type="data_export",
            auth_context=auth_context,
            resource=ResourcePolicy(
                owner_id=auth_context.user_id,
                organization_id=auth_context.organization_id,
                permitted_roles=("tenant_admin", "organization_admin", "member"),
                permitted_group_ids=auth_context.group_ids,
                data_region=settings.SECONDARY_DATA_REGION,
                required_consent_scopes=(),
                workspace_id=auth_context.workspace_id,
            ),
            evidence_source="access_policy.evaluate_access",
        )
    )
    return decisions


def _share_reviews(sources: list[GovernanceSource]) -> list[ExternalShareReview]:
    return [
        ExternalShareReview(
            source_type=source.source_type,
            review_label=f"{source.source_label} writeback boundary",
            exposure_level="external_writeback"
            if source.writeback_enabled
            else "internal",
            decision_reason=source.policy_decision.reason,
        )
        for source in sources
    ]


def _policy_order() -> list[PolicyOrderStep]:
    return [
        PolicyOrderStep(
            display_name="Signed session identity",
            evidence_label="signed_session_evidence",
        ),
        PolicyOrderStep(
            display_name="Organization and workspace scope",
            evidence_label="signed_session_evidence",
        ),
        PolicyOrderStep(
            display_name="Data-region deny",
            evidence_label="policy_engine_evidence",
        ),
        PolicyOrderStep(
            display_name="Consent and source capability deny",
            evidence_label="policy_engine_evidence",
        ),
        PolicyOrderStep(
            display_name="Owner or delegated admin boundary",
            evidence_label="policy_engine_evidence",
        ),
        PolicyOrderStep(
            display_name="RBAC allow after ABAC denies",
            evidence_label="policy_engine_evidence",
        ),
    ]


def _require_authoritative_workspace_scope(auth_context: AuthContext) -> None:
    if auth_context.session_verifier == "hmac":
        raise HTTPException(
            status_code=403,
            detail="Authoritative workspace membership is required for security access surface",
        )


@router.get("/access-surface", response_model=SecurityAccessSurfaceResponse)
async def get_access_surface(
    auth_context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> SecurityAccessSurfaceResponse:
    _require_authoritative_workspace_scope(auth_context)
    webdav_result = await db.execute(_webdav_scope_statement(auth_context))
    calendar_result = await db.execute(_calendar_scope_statement(auth_context))
    audit_result = await db.execute(_durable_audit_scope_statement(auth_context))
    connector_statement = connector_scope_statement(auth_context)
    connector_events: list[ConnectorSignalEvent] = []
    if connector_statement is not None:
        connector_result = await db.execute(connector_statement)
        connector_events = connector_result.scalars().all()

    durable_audit_events = audit_result.scalars().all()

    sources = [
        _webdav_source(account, auth_context)
        for account in webdav_result.scalars().all()
    ]
    sources.extend(
        _calendar_source(source, auth_context)
        for source in calendar_result.scalars().all()
    )
    source_decisions = [source.policy_decision for source in sources]
    policy_decisions = _canonical_policy_decisions(auth_context, source_decisions)

    return SecurityAccessSurfaceResponse(
        scope_kind=_scope_kind(auth_context.organization_id),
        viewer=ViewerContext(
            role=auth_context.role,
            scope_kind=_scope_kind(auth_context.organization_id),
        ),
        sources=sources,
        connector_events=[_connector_evidence(event) for event in connector_events],
        durable_audit_events=[
            _durable_audit_evidence(event) for event in durable_audit_events
        ],
        policy_decisions=policy_decisions,
        external_share_reviews=_share_reviews(sources),
        policy_order=_policy_order(),
    )
