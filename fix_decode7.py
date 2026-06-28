import re
with open("backend/tests/test_auth_real.py", "r") as f:
    content = f.read()

content = content.replace(
"""    finally:
        settings.OIDC_ISSUER_URL = previous_issuer_url
        settings.OIDC_CLIENT_ID = previous_client_id
        settings.AUTH_SESSION_HMAC_SECRET = previous_secret

    assert exc.value.status_code == 401
    assert decode_called is False


@pytest.mark.asyncio
async def test_oidc_rejects_unknown_critical_header_before_decode""",
"""    finally:
        settings.OIDC_ISSUER_URL = previous_issuer_url
        settings.OIDC_CLIENT_ID = previous_client_id
        settings.AUTH_SESSION_HMAC_SECRET = previous_secret

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_oidc_rejects_unknown_critical_header_before_decode"""
)

with open("backend/tests/test_auth_real.py", "w") as f:
    f.write(content)
