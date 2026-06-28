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
    assert decode_called is False


@pytest.mark.asyncio
async def test_oidc_rejects_key_id_that_does_not_match_verified_key""",
"""    finally:
        settings.OIDC_ISSUER_URL = previous_issuer_url
        settings.OIDC_CLIENT_ID = previous_client_id
        settings.AUTH_SESSION_HMAC_SECRET = previous_secret

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_oidc_rejects_key_id_that_does_not_match_verified_key"""
)

# And test_oidc_rejects_unknown_critical_header_before_decode DOES define decode_called
# And it DOES assert decode_called is False correctly (line 1140).

# The ones failing are test_hmac_session_rejects_admin_role_claim (line 635)
content = content.replace(
"""    with pytest.raises(HTTPException) as exc:
        await get_auth_context(authorization=f"Bearer {token}")

    assert exc.value.status_code == 401
    assert decode_called is False""",
"""    with pytest.raises(HTTPException) as exc:
        await get_auth_context(authorization=f"Bearer {token}")

    assert exc.value.status_code == 401"""
)

with open("backend/tests/test_auth_real.py", "w") as f:
    f.write(content)
