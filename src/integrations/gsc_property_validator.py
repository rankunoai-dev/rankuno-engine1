"""GSC property URL validation.

Validates that a GSC property URL is compatible with a crawl base URL before
attempting to fetch analytics. This prevents querying metrics for the wrong domain.
"""

from __future__ import annotations

from urllib.parse import urlparse

from src.core.logger import get_logger
from src.integrations.gsc_schemas import GscPropertyValidationResult

__all__ = ["GscPropertyValidator"]

_logger = get_logger("integrations.gsc_property_validator")


class GscPropertyValidator:
    """Validates GSC property URLs against crawl base URLs.

    GSC properties can be domain-level (example.com) or path-scoped (example.com/path/).
    A property is valid for a crawl if:
    1. Exact match: both URLs refer to the same domain and path
    2. Subdomain match: property is the base domain, crawl is a subdomain
    3. Prefix match: property and crawl share the same base, crawl path extends property path
    """

    def validate(
        self,
        property_url: str,
        crawl_base_url: str,
    ) -> GscPropertyValidationResult:
        """Validate property URL against crawl base URL.

        Args:
            property_url: GSC property URL (e.g., https://example.com/)
            crawl_base_url: Crawl base URL (e.g., https://example.com/blog/)

        Returns:
            GscPropertyValidationResult with match type and reason

        Raises:
            ValueError: If either URL cannot be parsed
        """
        try:
            prop_parsed = urlparse(property_url.lower())
            crawl_parsed = urlparse(crawl_base_url.lower())
        except Exception as exc:
            raise ValueError(f"Invalid URL provided: {exc}") from exc

        # Extract components
        prop_netloc = self._normalize_netloc(prop_parsed.netloc)
        crawl_netloc = self._normalize_netloc(crawl_parsed.netloc)
        prop_path = self._normalize_path(prop_parsed.path)
        crawl_path = self._normalize_path(crawl_parsed.path)

        if not prop_netloc or not crawl_netloc:
            return GscPropertyValidationResult(
                is_valid=False,
                match_type="",
                reason="Property or crawl URL missing domain",
            )

        # Check scheme compatibility
        if prop_parsed.scheme and crawl_parsed.scheme and prop_parsed.scheme != crawl_parsed.scheme:  # noqa: SIM102
            return GscPropertyValidationResult(
                is_valid=False,
                match_type="",
                reason=f"Scheme mismatch: {prop_parsed.scheme} vs {crawl_parsed.scheme}",
            )

        # Exact match: same domain and path
        if prop_netloc == crawl_netloc and prop_path == crawl_path:
            return GscPropertyValidationResult(
                is_valid=True,
                match_type="exact",
                reason=f"Exact match: {property_url} ↔ {crawl_base_url}",
            )

        # Subdomain match: property is base domain, crawl is subdomain
        if self._is_subdomain(crawl_netloc, prop_netloc) and prop_path == "/":
            return GscPropertyValidationResult(
                is_valid=True,
                match_type="subdomain",
                reason=f"Subdomain match: {crawl_netloc} is a subdomain of {prop_netloc}",
            )

        # Prefix match: same domain, crawl path extends property path
        if prop_netloc == crawl_netloc and crawl_path.startswith(prop_path):
            return GscPropertyValidationResult(
                is_valid=True,
                match_type="prefix",
                reason=f"Prefix match: crawl path {crawl_path} extends property path {prop_path}",
            )

        # No match
        return GscPropertyValidationResult(
            is_valid=False,
            match_type="",
            reason=(
                f"No match: property {prop_netloc}{prop_path} "
                f"does not cover crawl {crawl_netloc}{crawl_path}"
            ),
        )

    def _normalize_netloc(self, netloc: str) -> str:
        """Normalize network location (domain).

        Removes port numbers and www prefix (canonicalize to base domain).
        """
        if not netloc:
            return ""

        # Remove port if present
        return netloc.split(":")[0]

    def _normalize_path(self, path: str) -> str:
        """Normalize path.

        Ensures path ends with / (unless empty).
        """
        if not path:
            return "/"

        if not path.endswith("/"):
            path = f"{path}/"

        return path

    def _is_subdomain(self, subdomain: str, domain: str) -> bool:
        """Check if subdomain is a subdomain of domain.

        Examples:
            _is_subdomain("blog.example.com", "example.com") → True
            _is_subdomain("example.com", "example.com") → False
            _is_subdomain("notexample.com", "example.com") → False
        """
        return subdomain != domain and subdomain.endswith(f".{domain}")
