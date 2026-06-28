"""Pure RBAC/ABAC access policy decisions for workspace resources."""

from dataclasses import dataclass, field
from typing import Literal

from core.rbac import check_tenant_access

PolicyRoleName = Literal[
    "system_admin",
    "tenant_admin",
    "platform_admin",
    "organization_admin",
    "group_admin",
    "member",
]
DecisionReason = Literal[
    "allowed",
    "organization_denied",
    "workspace_denied",
    "data_region_denied",
    "consent_denied",
    "ownership_denied",
    "rbac_denied",
]


@dataclass(frozen=True)
class AccessRequest:
    user_id: str
    role: PolicyRoleName
    organization_id: str | None
    group_ids: tuple[str, ...]
    data_region: str | None
    consent_scopes: tuple[str, ...]
    workspace_id: str | None = None


@dataclass(frozen=True)
class ResourcePolicy:
    owner_id: str
    organization_id: str | None
    permitted_roles: tuple[PolicyRoleName, ...]
    permitted_group_ids: tuple[str, ...]
    data_region: str | None
    required_consent_scopes: tuple[str, ...]
    workspace_id: str | None = None
    delegated_user_ids: tuple[str, ...] = field(default_factory=tuple)
    require_owner_match: bool = False


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: DecisionReason


ROLE_EQUIVALENTS: dict[str, frozenset[str]] = {
    "system_admin": frozenset({"system_admin", "platform_admin"}),
    "platform_admin": frozenset({"system_admin", "platform_admin"}),
    "tenant_admin": frozenset({"tenant_admin", "organization_admin"}),
    "organization_admin": frozenset({"tenant_admin", "organization_admin"}),
    "group_admin": frozenset({"group_admin"}),
    "member": frozenset({"member"}),
}

CANONICAL_ROLE: dict[str, str] = {
    "system_admin": "system_admin",
    "platform_admin": "system_admin",
    "tenant_admin": "tenant_admin",
    "organization_admin": "tenant_admin",
    "group_admin": "group_admin",
    "member": "member",
}


def _equivalent_roles(role: str) -> frozenset[str]:
    return ROLE_EQUIVALENTS.get(role, frozenset({role}))


def _canonical_role(role: str) -> str:
    return CANONICAL_ROLE.get(role, role)


def _role_allowed(role: str, permitted_roles: tuple[PolicyRoleName, ...]) -> bool:
    if _is_system_admin_role(role):
        return any(_is_system_admin_role(item) for item in permitted_roles)
    request_role = _canonical_role(role)
    return any(
        check_tenant_access(request_role, _canonical_role(item))
        for item in permitted_roles
    )


def _is_system_admin_role(role: str) -> bool:
    return role in {"system_admin", "platform_admin"}


def evaluate_access(request: AccessRequest, resource: ResourcePolicy) -> AccessDecision:
    """Evaluate resource access with ABAC denials before RBAC allows."""
    role_allowed = _role_allowed(request.role, resource.permitted_roles)
    group_allowed = bool(set(request.group_ids) & set(resource.permitted_group_ids))

    if _is_system_admin_role(request.role) and not role_allowed:
        return AccessDecision(allowed=False, reason="rbac_denied")

    if request.organization_id != resource.organization_id:
        return AccessDecision(allowed=False, reason="organization_denied")

    if (
        resource.workspace_id is not None
        and request.workspace_id != resource.workspace_id
    ):
        return AccessDecision(allowed=False, reason="workspace_denied")

    if resource.data_region is not None and request.data_region != resource.data_region:
        return AccessDecision(allowed=False, reason="data_region_denied")

    missing_consent = set(resource.required_consent_scopes) - set(
        request.consent_scopes
    )
    if missing_consent:
        return AccessDecision(allowed=False, reason="consent_denied")

    owns_resource = request.user_id == resource.owner_id
    has_delegation = request.user_id in resource.delegated_user_ids
    if not owns_resource and not has_delegation:
        return AccessDecision(allowed=False, reason="ownership_denied")

    if not role_allowed and not group_allowed:
        return AccessDecision(allowed=False, reason="rbac_denied")

    return AccessDecision(allowed=True, reason="allowed")
