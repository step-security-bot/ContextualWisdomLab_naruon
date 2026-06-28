import re
with open("backend/tests/test_auth_real.py", "r") as f:
    content = f.read()

# Only test_oidc_rejects_non_rs256_algorithm_before_decode defines decode_called
# and we only want to add it there.
content = content.replace(
"""    finally:
        settings.OIDC_ISSUER_URL = previous_issuer_url
        settings.OIDC_CLIENT_ID = previous_client_id
        settings.AUTH_SESSION_HMAC_SECRET = previous_secret

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_oidc_rejects_key_id_that_does_not_match_verified_key(monkeypatch):""",
"""    finally:
        settings.OIDC_ISSUER_URL = previous_issuer_url
        settings.OIDC_CLIENT_ID = previous_client_id
        settings.AUTH_SESSION_HMAC_SECRET = previous_secret

    assert exc.value.status_code == 401
    assert decode_called is False


@pytest.mark.asyncio
async def test_oidc_rejects_key_id_that_does_not_match_verified_key(monkeypatch):"""
)

with open("backend/tests/test_auth_real.py", "w") as f:
    f.write(content)
