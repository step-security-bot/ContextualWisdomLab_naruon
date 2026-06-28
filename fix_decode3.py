import re
with open("backend/tests/test_auth_real.py", "r") as f:
    content = f.read()

content = re.sub(
    r'(    assert exc.value.status_code == 401\n\n\n@pytest.mark.asyncio\nasync def test_oidc_rejects_key_id_that_does_not_match_verified_key)',
    r'    assert exc.value.status_code == 401\n    assert decode_called is False\n\n\n@pytest.mark.asyncio\nasync def test_oidc_rejects_key_id_that_does_not_match_verified_key',
    content
)

with open("backend/tests/test_auth_real.py", "w") as f:
    f.write(content)
