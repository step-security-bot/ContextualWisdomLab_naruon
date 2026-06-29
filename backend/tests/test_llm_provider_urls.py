import pytest

from core.config import settings
from services.llm_provider_urls import (
    LLM_BASE_URL_NOT_ALLOWED,
    _is_ip_literal,
    _validate_global_address,
)


def test_validate_global_address_valid_ipv4():
    """Test that a valid global IPv4 address is accepted."""
    assert _validate_global_address("93.184.216.34") == "93.184.216.34"


def test_validate_global_address_valid_ipv6():
    """Test that a valid global IPv6 address is accepted."""
    assert (
        _validate_global_address("2606:2800:220:1:248:1893:25c8:1946")
        == "2606:2800:220:1:248:1893:25c8:1946"
    )


def test_validate_global_address_invalid_ip():
    """Test that an invalid IP address string raises a ValueError."""
    with pytest.raises(ValueError, match=LLM_BASE_URL_NOT_ALLOWED):
        _validate_global_address("not-an-ip-address")


def test_validate_global_address_private_ip():
    """Test that a private IP address is rejected."""
    with pytest.raises(ValueError, match=LLM_BASE_URL_NOT_ALLOWED):
        _validate_global_address("192.168.1.1")


def test_validate_global_address_loopback_ip_rejected():
    """Test that a loopback IP address is rejected by default."""
    with pytest.raises(ValueError, match=LLM_BASE_URL_NOT_ALLOWED):
        _validate_global_address("127.0.0.1")


def test_validate_global_address_link_local_ip_rejected():
    """Test that a link-local IP address is rejected."""
    with pytest.raises(ValueError, match=LLM_BASE_URL_NOT_ALLOWED):
        _validate_global_address("169.254.1.1")


def test_validate_global_address_multicast_ip_rejected():
    """Test that a multicast IP address is rejected."""
    with pytest.raises(ValueError, match=LLM_BASE_URL_NOT_ALLOWED):
        _validate_global_address("224.0.0.1")


def test_validate_global_address_loopback_allowed_when_settings_enabled(monkeypatch):
    """Test that a loopback IP is allowed when ALLOW_LOCAL_LLM_PROVIDERS is True."""
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", True)
    assert _validate_global_address("127.0.0.1") == "127.0.0.1"


def test_validate_global_address_private_allowed_when_host_allowed(monkeypatch):
    """Test that a private IP is allowed when the hostname is in ALLOWED_LLM_BASE_URL_HOSTS."""
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", True)
    monkeypatch.setattr(settings, "ALLOWED_LLM_BASE_URL_HOSTS", "ollama,other-host")

    assert _validate_global_address("192.168.1.5", hostname="ollama") == "192.168.1.5"


def test_validate_global_address_private_rejected_when_host_not_allowed(monkeypatch):
    """Test that a private IP is rejected even with ALLOW_LOCAL_LLM_PROVIDERS if the hostname is not allowed."""
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", True)
    monkeypatch.setattr(settings, "ALLOWED_LLM_BASE_URL_HOSTS", "ollama,other-host")

    with pytest.raises(ValueError, match=LLM_BASE_URL_NOT_ALLOWED):
        _validate_global_address("192.168.1.5", hostname="unallowed-host")


def test_validate_global_address_private_rejected_without_hostname(monkeypatch):
    """Test that a private IP is rejected if ALLOW_LOCAL_LLM_PROVIDERS is True but no hostname is provided."""
    monkeypatch.setattr(settings, "ALLOW_LOCAL_LLM_PROVIDERS", True)
    monkeypatch.setattr(settings, "ALLOWED_LLM_BASE_URL_HOSTS", "ollama,other-host")

    with pytest.raises(ValueError, match=LLM_BASE_URL_NOT_ALLOWED):
        _validate_global_address("192.168.1.5")


@pytest.mark.parametrize(
    "candidate, expected",
    [
        ("192.168.1.1", True),
        ("0.0.0.0", True),
        ("255.255.255.255", True),
        ("127.0.0.1", True),
        ("::1", True),
        ("2001:0db8:85a3:0000:0000:8a2e:0370:7334", True),
        ("2001:db8:85a3::8a2e:370:7334", True),
        ("fe80::1ff:fe23:4567:890a", True),
        ("256.256.256.256", False),
        ("192.168.1", False),
        ("1.2.3.4.5", False),
        ("2001:db8::85a3::8a2e:370:7334", False),
        ("localhost", False),
        ("example.com", False),
        ("api.openai.com", False),
        ("", False),
        (" ", False),
        ("invalid", False),
        ("12345", False),
        ("192.168.1.1.com", False),
    ],
)
def test_is_ip_literal(candidate, expected):
    assert _is_ip_literal(candidate) is expected
