import math

import pytest
from core.runtime_secrets import (
    _KNOWN_PUBLIC_AUTH_SESSION_HMAC_SECRETS,
    _LOW_ENTROPY_PLACEHOLDER_TERMS,
    _character_class_count,
    _shannon_entropy_bits,
    validate_auth_session_hmac_secret_value,
)


def test_validate_auth_session_hmac_secret_value_valid():
    validate_auth_session_hmac_secret_value("thisisaverylongandsecurestring123!")


def test_validate_auth_session_hmac_secret_value_empty():
    with pytest.raises(
        ValueError,
        match="AUTH_SESSION_HMAC_SECRET must be at least 32 bytes",
    ):
        validate_auth_session_hmac_secret_value("")
    with pytest.raises(
        ValueError,
        match="AUTH_SESSION_HMAC_SECRET must be at least 32 bytes",
    ):
        validate_auth_session_hmac_secret_value(None)


def test_validate_auth_session_hmac_secret_value_short():
    with pytest.raises(
        ValueError,
        match="AUTH_SESSION_HMAC_SECRET must be at least 32 bytes",
    ):
        validate_auth_session_hmac_secret_value("short")
    with pytest.raises(
        ValueError,
        match="AUTH_SESSION_HMAC_SECRET must be at least 32 bytes",
    ):
        validate_auth_session_hmac_secret_value("a" * 31)


def test_validate_auth_session_hmac_secret_value_repeated():
    with pytest.raises(ValueError, match="must not be a repeated character"):
        validate_auth_session_hmac_secret_value("a" * 32)
    with pytest.raises(ValueError, match="must not be a repeated character"):
        validate_auth_session_hmac_secret_value("1" * 64)


def test_validate_auth_session_hmac_secret_value_rejects_low_diversity():
    with pytest.raises(ValueError, match="at least 12 distinct characters"):
        validate_auth_session_hmac_secret_value("abcabcabcabcabcabcabcabcabcabcab")
    with pytest.raises(ValueError, match="at least three character classes"):
        validate_auth_session_hmac_secret_value("abcdefghijklmnopqrstuvwxyzabcdef")
    with pytest.raises(ValueError, match="at least 128 bits of estimated entropy"):
        validate_auth_session_hmac_secret_value("aaaaaaaaaaaaaaaaaaaaABC123!@#xyz")


def test_validate_auth_session_hmac_secret_value_public_fixture():
    for public_fixture in _KNOWN_PUBLIC_AUTH_SESSION_HMAC_SECRETS:
        with pytest.raises(ValueError, match="must not use a public fixture value"):
            validate_auth_session_hmac_secret_value(public_fixture)


def test_validate_auth_session_hmac_secret_value_placeholder():
    for term in _LOW_ENTROPY_PLACEHOLDER_TERMS:
        with pytest.raises(ValueError, match="must not contain placeholder terms"):
            validate_auth_session_hmac_secret_value(
                f"this_is_a_sufficiently_long_prefix_for_testing_purposes_{term}"
            )


def test_validate_auth_session_hmac_secret_value_rejects_strix_fixture():
    with pytest.raises(ValueError, match="placeholder terms"):
        validate_auth_session_hmac_secret_value("NaRuOnSeCrEtToKeN1234567890abcdef")


def test_validate_auth_session_hmac_secret_value_accepts_multibyte_byte_length():
    secret = "가ABCDEFGHIJKLMNOabcdefghij1234!"

    assert len(secret) < 32
    assert len(secret.encode("utf-8")) >= 32

    validate_auth_session_hmac_secret_value(secret)


def test_validate_auth_session_hmac_secret_value_multibyte_length():
    with pytest.raises(ValueError, match="must be at least 32 bytes"):
        validate_auth_session_hmac_secret_value("가나다라마바사아자차")

    with pytest.raises(ValueError, match="at least three character classes"):
        validate_auth_session_hmac_secret_value("가나다라마바사아자차카타파하")


def test_character_class_count():
    assert _character_class_count("alllower") == 1
    assert _character_class_count("ALLUPPER") == 1
    assert _character_class_count("12345678") == 1
    assert _character_class_count("!@#$%^&*") == 1

    assert _character_class_count("LowerAndUpper") == 2
    assert _character_class_count("lower123") == 2
    assert _character_class_count("UPPER123") == 2
    assert _character_class_count("lower!@#") == 2

    assert _character_class_count("LowerAndUpper123") == 3
    assert _character_class_count("LowerAndUpper!@#") == 3

    assert _character_class_count("All4Classes123!@#") == 4
    assert _character_class_count("aaAA11!!") == 4

    assert _character_class_count("") == 0


def test_shannon_entropy_bits():
    assert _shannon_entropy_bits("") == 0.0

    assert _shannon_entropy_bits("a") == 0.0
    assert _shannon_entropy_bits("aaaaa") == 0.0

    assert _shannon_entropy_bits("ab") == 2.0
    assert _shannon_entropy_bits("abab") == 4.0

    assert math.isclose(_shannon_entropy_bits("aab"), 3 * math.log2(3) - 2)
    assert math.isclose(_shannon_entropy_bits("abcd"), 8.0)
    assert math.isclose(_shannon_entropy_bits("abc"), 4.754887502163468)
    assert math.isclose(_shannon_entropy_bits("abcabc"), 9.509775004326936)
