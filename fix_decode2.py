import re
with open("backend/tests/test_auth_real.py", "r") as f:
    content = f.read()

content = re.sub(
    r'(    assert exc.value.status_code == 401\n\n\n@pytest.mark.asyncio\nasync def test_oidc_rejects_key_id_that_does_not_match_verified_key)',
    r'    assert exc.value.status_code == 401\n    assert decode_called is False\n\n\n@pytest.mark.asyncio\nasync def test_oidc_rejects_key_id_that_does_not_match_verified_key',
    content
)

content = re.sub(
    r'(    assert exc.value.status_code == 401\n\n\n@pytest.mark.asyncio\n@pytest.mark.parametrize\(\n    "admin_role",\n    \("system_admin", "platform_admin", "tenant_admin", "organization_admin"\),\n\)\nasync def test_oidc_session_rejects_admin_role_claim)',
    r'    assert exc.value.status_code == 401\n    assert decode_called is False\n\n\n@pytest.mark.asyncio\n@pytest.mark.parametrize(\n    "admin_role",\n    ("system_admin", "platform_admin", "tenant_admin", "organization_admin"),\n)\nasync def test_oidc_session_rejects_admin_role_claim',
    content
)

with open("backend/tests/test_auth_real.py", "w") as f:
    f.write(content)
