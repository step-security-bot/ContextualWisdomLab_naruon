from core.rbac import (
    AbacPolicy,
    ResourceAction,
    check_tenant_access,
    evaluate_abac_policy,
)


def test_check_tenant_access_hierarchy():
    """Test that higher privileges can access resources requiring lower privileges."""
    assert check_tenant_access("system_admin", "member") is True
    assert check_tenant_access("system_admin", "tenant_admin") is True
    assert check_tenant_access("platform_admin", "group_admin") is True
    assert check_tenant_access("tenant_admin", "member") is True
    assert check_tenant_access("organization_admin", "group_admin") is True
    assert check_tenant_access("group_admin", "member") is True

def test_check_tenant_access_equality():
    """Test that users can access resources requiring their exact role."""
    assert check_tenant_access("member", "member") is True
    assert check_tenant_access("group_admin", "group_admin") is True
    assert check_tenant_access("tenant_admin", "tenant_admin") is True
    assert check_tenant_access("organization_admin", "organization_admin") is True
    assert check_tenant_access("system_admin", "system_admin") is True
    assert check_tenant_access("platform_admin", "platform_admin") is True

def test_check_tenant_access_insufficient_privilege():
    """Test that lower privileges cannot access resources requiring higher privileges."""
    assert check_tenant_access("member", "system_admin") is False
    assert check_tenant_access("member", "tenant_admin") is False
    assert check_tenant_access("group_admin", "tenant_admin") is False
    assert check_tenant_access("tenant_admin", "system_admin") is False
    assert check_tenant_access("organization_admin", "platform_admin") is False

def test_check_tenant_access_equivalent_roles():
    """Test roles that share the same level in the hierarchy."""
    # level 2
    assert check_tenant_access("tenant_admin", "organization_admin") is True
    assert check_tenant_access("organization_admin", "tenant_admin") is True

    # level 3
    assert check_tenant_access("system_admin", "platform_admin") is True
    assert check_tenant_access("platform_admin", "system_admin") is True

def test_check_tenant_access_invalid_roles():
    """Test behavior when invalid roles are provided."""
    # invalid user role
    assert check_tenant_access("invalid_role", "member") is False

    # invalid required role
    assert check_tenant_access("system_admin", "invalid_role") is False

    # both invalid
    assert check_tenant_access("invalid_role", "another_invalid") is False

    # None values
    assert check_tenant_access(None, "member") is False
    assert check_tenant_access("system_admin", None) is False
    assert check_tenant_access(None, None) is False


def test_evaluate_abac_policy_empty_conditions():
    """Test that a policy with no conditions allows access."""
    policy = AbacPolicy(
        policy_id="p1",
        resource_type="document",
        action=ResourceAction.READ,
        conditions={},
    )
    user_attrs = {"department": "sales"}
    assert evaluate_abac_policy(user_attrs, policy) is True


def test_evaluate_abac_policy_exact_match():
    """Test that exact matches of attributes allow access."""
    policy = AbacPolicy(
        policy_id="p2",
        resource_type="document",
        action=ResourceAction.WRITE,
        conditions={"department": "sales", "clearance": "high"},
    )
    user_attrs = {"department": "sales", "clearance": "high"}
    assert evaluate_abac_policy(user_attrs, policy) is True


def test_evaluate_abac_policy_missing_attribute():
    """Test that missing required attributes deny access."""
    policy = AbacPolicy(
        policy_id="p3",
        resource_type="document",
        action=ResourceAction.DELETE,
        conditions={"department": "sales", "clearance": "high"},
    )
    user_attrs = {"department": "sales"}
    assert evaluate_abac_policy(user_attrs, policy) is False


def test_evaluate_abac_policy_mismatched_attribute():
    """Test that mismatched attribute values deny access."""
    policy = AbacPolicy(
        policy_id="p4",
        resource_type="document",
        action=ResourceAction.READ,
        conditions={"department": "sales"},
    )
    user_attrs = {"department": "marketing"}
    assert evaluate_abac_policy(user_attrs, policy) is False


def test_evaluate_abac_policy_extra_attributes():
    """Test that extra attributes not in the policy do not deny access."""
    policy = AbacPolicy(
        policy_id="p5",
        resource_type="document",
        action=ResourceAction.READ,
        conditions={"department": "sales"},
    )
    user_attrs = {"department": "sales", "clearance": "high", "role": "manager"}
    assert evaluate_abac_policy(user_attrs, policy) is True
