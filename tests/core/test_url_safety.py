"""Tests for the SSRF guard.

These tests never touch DNS. Every hostname resolution goes through an injected
stub resolver, so the suite is deterministic and runs offline.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, NoReturn

import pytest
from src.core.errors import UnsafeUrlError
from src.core.url_safety import (
    DEFAULT_ALLOWED_PORTS,
    SafeUrl,
    UrlSafetyPolicy,
    describe_ip_block,
    system_resolver,
)

PUBLIC_IP = "93.184.216.34"


def policy_for(
    mapping: dict[str, list[str]] | None = None,
    *,
    allow_private_ips: bool = False,
    allowed_ports: Iterable[int] = DEFAULT_ALLOWED_PORTS,
) -> UrlSafetyPolicy:
    """Build a policy whose resolver answers from a fixed table."""
    table = mapping or {}

    def resolver(host: str) -> list[str]:
        return table.get(host, [PUBLIC_IP])  # default: a public address

    return UrlSafetyPolicy(
        resolver=resolver,
        allow_private_ips=allow_private_ips,
        allowed_ports=allowed_ports,
    )


class TestDescribeIpBlock:
    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",  # AWS/GCP instance metadata
            "0.0.0.0",  # noqa: S104 - asserting this is blocked, not binding to it
            "224.0.0.1",
            "::1",
            "fe80::1",
            "fc00::1",
        ],
    )
    def test_blocks_non_public_addresses(self, address):
        assert describe_ip_block(address) is not None

    @pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1::1"])
    def test_allows_public_addresses(self, address):
        assert describe_ip_block(address) is None

    def test_unwraps_ipv4_mapped_ipv6(self):
        """::ffff:127.0.0.1 is loopback wearing a v6 costume."""
        assert describe_ip_block("::ffff:127.0.0.1") is not None

    def test_unwraps_6to4(self):
        """2002:: encodes an embedded IPv4 address that must be classified."""
        assert describe_ip_block("2002:a00:1::") is not None

    def test_rejects_garbage(self):
        assert describe_ip_block("not-an-ip") is not None


class TestSchemeAndShape:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://example.com/",
            "ftp://example.com/",
            "data:text/plain,hello",
        ],
    )
    def test_rejects_non_web_schemes(self, url):
        with pytest.raises(UnsafeUrlError, match="scheme"):
            policy_for().validate(url)

    def test_rejects_embedded_credentials(self):
        with pytest.raises(UnsafeUrlError, match="credentials"):
            policy_for().validate("http://user:pass@example.com/")

    @pytest.mark.parametrize("url", ["", "   "])
    def test_rejects_empty(self, url):
        with pytest.raises(UnsafeUrlError, match="empty"):
            policy_for().validate(url)

    def test_rejects_control_characters(self):
        """CR/LF in a URL enables request splitting against a naive client."""
        with pytest.raises(UnsafeUrlError, match="control character"):
            policy_for().validate("http://example.com/\r\nX-Injected: 1")

    def test_rejects_missing_host(self):
        with pytest.raises(UnsafeUrlError, match="no host"):
            policy_for().validate("http:///just-a-path")

    def test_rejects_disallowed_port(self):
        with pytest.raises(UnsafeUrlError, match="port 22"):
            policy_for().validate("http://example.com:22/")

    def test_rejects_invalid_port(self):
        with pytest.raises(UnsafeUrlError, match="port"):
            policy_for().validate("http://example.com:not-a-port/")


class TestInternalNames:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/",
            "http://foo.localhost/",
            "http://db.internal/",
            "http://printer.local/",
            "http://metadata.google.internal/",
        ],
    )
    def test_rejects_internal_hostnames_before_resolution(self, url):
        """These are refused on the name alone, so a hostile resolver cannot help."""
        with pytest.raises(UnsafeUrlError):
            policy_for().validate(url)


class TestAddressValidation:
    def test_rejects_private_literal(self):
        with pytest.raises(UnsafeUrlError, match="private"):
            policy_for().validate("http://192.168.0.5/")

    def test_rejects_metadata_literal(self):
        with pytest.raises(UnsafeUrlError, match="link-local"):
            policy_for().validate("http://169.254.169.254/latest/meta-data/")

    def test_rejects_host_resolving_to_private_address(self):
        """The classic DNS-based SSRF: a public name pointing inward."""
        p = policy_for({"evil.example.com": ["10.0.0.7"]})
        with pytest.raises(UnsafeUrlError, match="10.0.0.7"):
            p.validate("http://evil.example.com/")

    def test_rejects_multihomed_host_with_any_private_address(self):
        """One bad address in the set poisons the whole hostname."""
        p = policy_for({"mixed.example.com": ["93.184.216.34", "127.0.0.1"]})
        with pytest.raises(UnsafeUrlError):
            p.validate("http://mixed.example.com/")

    def test_rejects_host_that_resolves_to_nothing(self):
        p = policy_for({"void.example.com": []})
        with pytest.raises(UnsafeUrlError, match="no addresses"):
            p.validate("http://void.example.com/")

    def test_decimal_encoded_loopback_is_still_loopback(self):
        """2130706433 == 127.0.0.1; ipaddress normalises it, so it must be caught."""
        p = policy_for({"sneaky.example.com": ["2130706433"]})
        with pytest.raises(UnsafeUrlError):
            p.validate("http://sneaky.example.com/")


class TestSuccessfulValidation:
    def test_returns_safe_url_with_resolved_addresses(self):
        p = policy_for({"example.com": ["93.184.216.34"]})
        result = p.validate("https://example.com/path?a=1")
        assert isinstance(result, SafeUrl)
        assert result.scheme == "https"
        assert result.host == "example.com"
        assert result.port == 443
        assert result.resolved_ips == ("93.184.216.34",)

    def test_normalizes_scheme_host_and_default_port(self):
        p = policy_for({"example.com": ["93.184.216.34"]})
        assert p.validate("HTTPS://Example.COM:443/x").url == "https://example.com/x"

    def test_keeps_non_default_port(self):
        p = policy_for({"example.com": ["93.184.216.34"]})
        assert p.validate("http://example.com:8080/x").url == "http://example.com:8080/x"

    def test_empty_path_becomes_root(self):
        p = policy_for({"example.com": ["93.184.216.34"]})
        assert p.validate("https://example.com").url == "https://example.com/"

    def test_preserves_query_string(self):
        p = policy_for({"example.com": ["93.184.216.34"]})
        assert p.validate("https://example.com/s?q=a&b=2").url == "https://example.com/s?q=a&b=2"

    def test_strips_trailing_dot_from_host(self):
        """'example.com.' and 'example.com' are the same host; treat them alike."""
        p = policy_for({"example.com": ["93.184.216.34"]})
        assert p.validate("https://example.com./").host == "example.com"

    def test_public_ip_literal_is_allowed_without_resolution(self):
        result = policy_for().validate("http://93.184.216.34/")
        assert result.resolved_ips == ("93.184.216.34",)

    def test_idna_encodes_unicode_hostnames(self):
        """Punycode normalisation stops a homograph bypassing the suffix checks."""
        p = policy_for({"xn--bcher-kva.example": ["93.184.216.34"]})
        assert p.validate("https://bücher.example/").host == "xn--bcher-kva.example"


class TestPolicyConfiguration:
    def test_allow_private_ips_permits_loopback(self):
        """Escape hatch for fixture servers. Must be explicit, never the default."""
        result = policy_for(allow_private_ips=True).validate("http://127.0.0.1:8080/")
        assert result.host == "127.0.0.1"

    def test_allow_private_ips_permits_internal_names(self):
        p = policy_for({"localhost": ["127.0.0.1"]}, allow_private_ips=True)
        assert p.validate("http://localhost:8080/").host == "localhost"

    def test_custom_port_allowlist(self):
        p = policy_for(allowed_ports={9000})
        assert p.validate("http://example.com:9000/").port == 9000
        with pytest.raises(UnsafeUrlError):
            p.validate("http://example.com/")

    def test_default_policy_rejects_loopback(self):
        """Sanity check that the safe default is actually the default."""
        with pytest.raises(UnsafeUrlError):
            policy_for().validate("http://127.0.0.1:8080/")


class TestSystemResolver:
    def test_unresolvable_host_raises_unsafe_url_error(self, monkeypatch):
        import socket

        def boom(*_args: Any, **_kwargs: Any) -> NoReturn:
            raise socket.gaierror(-2, "Name or service not known")

        monkeypatch.setattr(socket, "getaddrinfo", boom)
        with pytest.raises(UnsafeUrlError, match="does not resolve"):
            system_resolver("nope.example")

    def test_returns_sorted_unique_addresses(self, monkeypatch):
        import socket

        def fake(*_args: Any, **_kwargs: Any) -> list[tuple[int, int, int, str, tuple[str, int]]]:
            return [
                (0, 0, 0, "", (PUBLIC_IP, 0)),
                (0, 0, 0, "", (PUBLIC_IP, 0)),
                (0, 0, 0, "", ("8.8.8.8", 0)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake)
        assert system_resolver("example.com") == ["8.8.8.8", PUBLIC_IP]
