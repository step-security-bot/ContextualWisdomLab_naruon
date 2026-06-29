from core.rbac import check_tenant_access

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
