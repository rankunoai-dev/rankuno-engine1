"""Tests for GSC property URL validation."""

import pytest
from src.integrations.gsc_property_validator import GscPropertyValidator


@pytest.fixture
def validator() -> GscPropertyValidator:
    """Provide a validator instance."""
    return GscPropertyValidator()


class TestExactMatch:
    """Test exact domain and path matching."""

    def test_exact_match_simple_domain(self, validator):
        """Exact match: same domain with trailing slash."""
        result = validator.validate(
            "https://example.com/",
            "https://example.com/",
        )
        assert result.is_valid is True
        assert result.match_type == "exact"

    def test_exact_match_with_path(self, validator):
        """Exact match: same domain and path."""
        result = validator.validate(
            "https://example.com/blog/",
            "https://example.com/blog/",
        )
        assert result.is_valid is True
        assert result.match_type == "exact"


class TestSubdomainMatch:
    """Test subdomain matching (property is base domain)."""

    def test_subdomain_match(self, validator):
        """Subdomain match: property is base, crawl is subdomain."""
        result = validator.validate(
            "https://example.com/",  # property: base domain
            "https://blog.example.com/",  # crawl: subdomain
        )
        assert result.is_valid is True
        assert result.match_type == "subdomain"

    def test_subdomain_match_multi_level(self, validator):
        """Subdomain match: multi-level subdomain."""
        result = validator.validate(
            "https://example.com/",
            "https://api.v2.example.com/",
        )
        assert result.is_valid is True
        assert result.match_type == "subdomain"

    def test_subdomain_not_match_wrong_domain(self, validator):
        """Subdomain: not a match if different base domain."""
        result = validator.validate(
            "https://example.com/",
            "https://notexample.com/",
        )
        assert result.is_valid is False


class TestPrefixMatch:
    """Test path prefix matching."""

    def test_prefix_match_simple(self, validator):
        """Prefix match: crawl path extends property path."""
        result = validator.validate(
            "https://example.com/blog/",  # property: /blog/
            "https://example.com/blog/products/",  # crawl: /blog/products/
        )
        assert result.is_valid is True
        assert result.match_type == "prefix"

    def test_prefix_match_root_to_path(self, validator):
        """Prefix match: property is root, crawl is sub-path."""
        result = validator.validate(
            "https://example.com/",
            "https://example.com/blog/",
        )
        assert result.is_valid is True
        assert result.match_type == "prefix"

    def test_prefix_match_deep_paths(self, validator):
        """Prefix match: deep paths."""
        result = validator.validate(
            "https://example.com/blog/",
            "https://example.com/blog/2024/august/post/",
        )
        assert result.is_valid is True
        assert result.match_type == "prefix"


class TestTrailingSlashNormalization:
    """Test that trailing slashes are normalized."""

    def test_normalize_property_missing_slash(self, validator):
        """Property without trailing slash matches crawl with slash."""
        result = validator.validate(
            "https://example.com",  # no trailing slash
            "https://example.com/",
        )
        assert result.is_valid is True
        assert result.match_type == "exact"

    def test_normalize_crawl_missing_slash(self, validator):
        """Crawl without trailing slash matches property with slash."""
        result = validator.validate(
            "https://example.com/",
            "https://example.com",  # no trailing slash
        )
        assert result.is_valid is True
        assert result.match_type == "exact"

    def test_normalize_both_missing_slash(self, validator):
        """Both URLs without trailing slashes match."""
        result = validator.validate(
            "https://example.com",
            "https://example.com",
        )
        assert result.is_valid is True
        assert result.match_type == "exact"


class TestCaseInsensitivity:
    """Test that domain matching is case-insensitive."""

    def test_case_insensitive_domain(self, validator):
        """Domain comparison is case-insensitive."""
        result = validator.validate(
            "https://Example.com/",
            "https://example.com/",
        )
        assert result.is_valid is True
        assert result.match_type == "exact"

    def test_case_insensitive_subdomain(self, validator):
        """Subdomain matching is case-insensitive."""
        result = validator.validate(
            "https://EXAMPLE.COM/",
            "https://blog.Example.com/",
        )
        assert result.is_valid is True
        assert result.match_type == "subdomain"


class TestPortHandling:
    """Test that port numbers are handled correctly."""

    def test_port_ignored_exact_match(self, validator):
        """Ports are ignored in matching."""
        result = validator.validate(
            "https://example.com:443/",
            "https://example.com/",
        )
        assert result.is_valid is True
        assert result.match_type == "exact"

    def test_different_ports_still_match(self, validator):
        """Different ports on same domain still match."""
        result = validator.validate(
            "https://example.com:8080/",
            "https://example.com:3000/",
        )
        assert result.is_valid is True
        assert result.match_type == "exact"


class TestInvalidCases:
    """Test invalid URL combinations."""

    def test_different_domains(self, validator):
        """Different domains do not match."""
        result = validator.validate(
            "https://example.com/",
            "https://other.com/",
        )
        assert result.is_valid is False
        assert result.match_type == ""

    def test_property_path_not_prefix_of_crawl(self, validator):
        """Property path that doesn't prefix crawl path is invalid."""
        result = validator.validate(
            "https://example.com/blog/",
            "https://example.com/shop/",
        )
        assert result.is_valid is False
        assert result.match_type == ""


class TestMalformedURLs:
    """Test error handling for malformed URLs."""

    def test_empty_property_url(self, validator):
        """Empty property URL returns invalid result."""
        result = validator.validate("", "https://example.com/")
        assert result.is_valid is False

    def test_empty_crawl_url(self, validator):
        """Empty crawl URL returns invalid result."""
        result = validator.validate("https://example.com/", "")
        assert result.is_valid is False

    def test_missing_domain_property(self, validator):
        """Property URL with no domain returns invalid."""
        result = validator.validate(
            "/path/only",
            "https://example.com/",
        )
        assert result.is_valid is False

    def test_missing_domain_crawl(self, validator):
        """Crawl URL with no domain returns invalid."""
        result = validator.validate(
            "https://example.com/",
            "/path/only",
        )
        assert result.is_valid is False
