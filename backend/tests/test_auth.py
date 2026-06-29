import pytest
from api.auth import is_admin_role


@pytest.mark.parametrize(
    "role, expected",
    [
        ("system_admin", True),
        ("platform_admin", True),
        ("tenant_admin", True),
        ("organization_admin", True),
        ("group_admin", False),
        ("member", False),
        ("invalid_role", False),
        ("", False),
    ],
)
def test_is_admin_role(role: str, expected: bool):
    assert is_admin_role(role) is expected
