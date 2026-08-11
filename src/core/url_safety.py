"""SSRF guard — validates a URL *before* a socket is ever opened.

The crawler accepts operator- and client-supplied URLs, which makes it a
server-side request forgery vector by construction. A target of
`http://169.254.169.254/latest/meta-data/iam/security-credentials/` is not a
malformed URL; it is a well-formed request for cloud instance credentials.

`docs/adr/0004-*.md` and the Phase 1 Master Blueprint §6 both require a private
range blocker. This module is that blocker, and it is the only sanctioned way to
turn an untrusted string into something the crawler may fetch.

Design stance: **deny by default**. Anything not positively recognised as a
public, plain-HTTP(S) endpoint is refused. Refusing a legitimate target is an
inconvenience; fetching an internal one is an incident.

Known limitation — DNS rebinding
--------------------------------
Validation resolves the hostname and checks every returned address, but a
resolver can return a different answer when the HTTP client resolves it again a
moment later (a TOCTOU rebinding attack). `SafeUrl.resolved_ips` is exposed
precisely so a caller can *pin* the connection to an address that was actually
validated. Callers that reconnect by hostname remain exposed.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

from src.core.errors import UnsafeUrlError
from src.core.logger import get_logger

__all__ = [
    "ALLOWED_SCHEMES",
    "BLOCKED_HOST_SUFFIXES",
    "DEFAULT_ALLOWED_PORTS",
    "Resolver",
    "SafeUrl",
    "UrlSafetyPolicy",
    "describe_ip_block",
    "system_resolver",
]

_logger = get_logger("core.url_safety")

ALLOWED_SCHEMES = frozenset({"http", "https"})
"""Only plain web schemes. Blocks `file:`, `gopher:`, `ftp:`, `data:` and the
redirect-to-`file:` trick that turns a fetcher into an arbitrary file reader."""

DEFAULT_ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})
"""Ports a public web server plausibly listens on. An unrestricted port set
turns the crawler into an internal port scanner."""

BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".intranet",
    ".corp",
    ".home",
    ".lan",
    "metadata.google.internal",
    "metadata.goog",
)
"""Hostnames that name internal infrastructure regardless of what they resolve
to. Checked before resolution so a hostile resolver cannot help."""

_BLOCKED_EXACT_HOSTS = frozenset({"localhost", "metadata", "instance-data"})

_DEFAULT_PORT_FOR_SCHEME = {"http": 80, "https": 443}

Resolver = Callable[[str], list[str]]
"""Maps a hostname to its IP addresses. Injectable so tests never touch DNS."""


def system_resolver(host: str) -> list[str]:
    """Resolve `host` to every address the system resolver knows.

    Every returned address is validated, not just the first. A hostname with one
    public and one loopback address must be refused outright.

    Args:
        host: Hostname to resolve.

    Returns:
        Sorted, de-duplicated IP address strings.

    Raises:
        UnsafeUrlError: If the hostname does not resolve.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(host, f"hostname does not resolve ({exc.strerror or exc})") from exc
    return sorted({str(info[4][0]) for info in infos})


def describe_ip_block(address: str) -> str | None:
    """Explain why an IP address must not be fetched, or return `None` if it may.

    Args:
        address: An IPv4 or IPv6 address in string form.

    Returns:
        A human-readable reason, or `None` when the address is a public unicast
        address that is safe to contact.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return f"'{address}' is not a valid IP address"

    # An IPv4-mapped IPv6 address (::ffff:127.0.0.1) carries the IPv4 address's
    # reachability, not the IPv6 wrapper's. Unwrap before classifying, or
    # loopback slips through disguised as a v6 address.
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return describe_ip_block(str(ip.ipv4_mapped))
        if ip.sixtofour is not None:
            return describe_ip_block(str(ip.sixtofour))
        if ip.teredo is not None:
            return describe_ip_block(str(ip.teredo[1]))

    checks: tuple[tuple[bool, str], ...] = (
        (ip.is_unspecified, "unspecified address"),
        (ip.is_loopback, "loopback address"),
        (ip.is_link_local, "link-local address (cloud instance metadata range)"),
        (ip.is_multicast, "multicast address"),
        (ip.is_reserved, "reserved address"),
        (ip.is_private, "private address (RFC1918 / unique-local)"),
    )
    for is_blocked, reason in checks:
        if is_blocked:
            return reason
    return None


@dataclass(frozen=True)
class SafeUrl:
    """A URL that passed every safety check.

    Producing one of these is the only way to obtain permission to fetch. The
    type exists so a reviewer can tell validated URLs from raw strings at a
    glance, and so an unvalidated string cannot reach the HTTP client by accident.

    Attributes:
        original: The URL exactly as supplied.
        url: Normalised form — lowercased scheme and host, default port removed.
        scheme: Either `http` or `https`.
        host: Lowercased, IDNA-encoded hostname or IP literal.
        port: Effective port, defaulted from the scheme when absent.
        resolved_ips: Every address that was validated. Pin the connection to one
            of these to close the DNS rebinding window.
    """

    original: str
    url: str
    scheme: str
    host: str
    port: int
    resolved_ips: tuple[str, ...]


class UrlSafetyPolicy:
    """Turns untrusted URL strings into `SafeUrl` values, or refuses them."""

    def __init__(
        self,
        *,
        allowed_schemes: Iterable[str] = ALLOWED_SCHEMES,
        allowed_ports: Iterable[int] = DEFAULT_ALLOWED_PORTS,
        allow_private_ips: bool = False,
        resolver: Resolver | None = None,
    ) -> None:
        """Build a policy.

        Args:
            allowed_schemes: URL schemes permitted. Widening this is a security
                decision requiring an ADR.
            allowed_ports: Ports permitted.
            allow_private_ips: Permit private, loopback and link-local targets.
                **Test and local-fixture use only.** Enabling it in a deployed
                environment reinstates the SSRF vulnerability this class exists
                to close, so it is logged loudly.
            resolver: Hostname resolution strategy. Defaults to the system
                resolver; tests inject a stub.
        """
        self._schemes = frozenset(allowed_schemes)
        self._ports = frozenset(allowed_ports)
        self._allow_private = allow_private_ips
        self._resolve: Resolver = resolver or system_resolver

        if allow_private_ips:
            _logger.warning("ssrf_guard_private_ips_permitted")

    def validate(self, url: str) -> SafeUrl:
        """Validate a URL, or refuse it.

        Args:
            url: An untrusted URL string.

        Returns:
            The validated, normalised URL.

        Raises:
            UnsafeUrlError: If any check fails. The message names the failing
                rule so an operator can tell a typo from an attack.
        """
        candidate = url.strip()
        if not candidate:
            raise UnsafeUrlError(url, "empty URL")

        # A raw CR/LF or NUL enables request splitting against a naive client.
        if any(char in candidate for char in ("\r", "\n", "\t", "\x00")):
            raise UnsafeUrlError(url, "URL contains a control character")

        try:
            parts = urlsplit(candidate)
        except ValueError as exc:
            # `urlsplit` itself raises on a bracketed host that is not a valid
            # IP — `http://[invalid-ipv6]/` — as of the 3.11 hardening in
            # `_check_bracketed_host`. Left bare, that `ValueError` escapes every
            # caller, none of which expect anything but `UnsafeUrlError` from
            # this method: one such link in a page's markup aborted the crawl.
            #
            # A URL the standard library cannot parse is unsafe by definition,
            # so it becomes the error callers already handle.
            raise UnsafeUrlError(url, f"URL is unparseable ({exc})") from exc

        scheme = parts.scheme.lower()
        if scheme not in self._schemes:
            allowed = ", ".join(sorted(self._schemes))
            raise UnsafeUrlError(
                url, f"scheme '{parts.scheme}' is not permitted (allowed: {allowed})"
            )

        if parts.username is not None or parts.password is not None:
            raise UnsafeUrlError(url, "embedded credentials are not permitted")

        host = self._extract_host(url, parts.hostname)
        port = self._extract_port(url, parts, scheme)
        self._reject_internal_names(url, host)
        resolved = self._validate_addresses(url, host)

        return SafeUrl(
            original=url,
            url=self._normalize(parts, scheme, host, port),
            scheme=scheme,
            host=host,
            port=port,
            resolved_ips=resolved,
        )

    # -- internals ---------------------------------------------------------

    def _extract_host(self, url: str, hostname: str | None) -> str:
        """Lowercase and IDNA-encode the hostname, refusing malformed ones."""
        if not hostname:
            raise UnsafeUrlError(url, "URL has no host")

        host = hostname.lower().rstrip(".")
        if not host:
            raise UnsafeUrlError(url, "URL has no host")

        # Normalise Unicode homographs to their punycode form so that a
        # look-alike domain cannot bypass a suffix check.
        if not host.isascii():
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise UnsafeUrlError(url, f"hostname is not encodable as IDNA ({exc})") from exc
        return host

    def _extract_port(self, url: str, parts: SplitResult, scheme: str) -> int:
        """Resolve the effective port and check it against the allowlist."""
        try:
            explicit = parts.port
        except ValueError as exc:  # SplitResult.port validates lazily
            raise UnsafeUrlError(url, f"invalid port ({exc})") from exc

        port = explicit if explicit is not None else _DEFAULT_PORT_FOR_SCHEME[scheme]
        if port not in self._ports:
            allowed = ", ".join(str(p) for p in sorted(self._ports))
            raise UnsafeUrlError(url, f"port {port} is not permitted (allowed: {allowed})")
        return port

    def _reject_internal_names(self, url: str, host: str) -> None:
        """Refuse hostnames that name internal infrastructure by convention."""
        if self._allow_private:
            return
        if host in _BLOCKED_EXACT_HOSTS:
            raise UnsafeUrlError(url, f"'{host}' names an internal host")
        for suffix in BLOCKED_HOST_SUFFIXES:
            if host == suffix or host.endswith(suffix):
                raise UnsafeUrlError(url, f"'{host}' matches blocked suffix '{suffix}'")

    def _validate_addresses(self, url: str, host: str) -> tuple[str, ...]:
        """Check every address the host maps to, resolving only if needed."""
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            addresses = self._resolve(host)
        else:
            addresses = [str(literal)]

        if not addresses:
            raise UnsafeUrlError(url, "hostname resolved to no addresses")

        if self._allow_private:
            return tuple(addresses)

        for address in addresses:
            reason = describe_ip_block(address)
            if reason is not None:
                # Log the full picture: the operator needs to know *which* of a
                # multi-homed host's addresses was the problem.
                _logger.warning(
                    "ssrf_blocked",
                    extra={"host": host, "address": address, "reason": reason},
                )
                raise UnsafeUrlError(url, f"host resolves to {address} — {reason}")
        return tuple(addresses)

    @staticmethod
    def _normalize(parts: SplitResult, scheme: str, host: str, port: int) -> str:
        """Rebuild the URL in canonical form, dropping a redundant port."""
        netloc = host if port == _DEFAULT_PORT_FOR_SCHEME[scheme] else f"{host}:{port}"
        return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
