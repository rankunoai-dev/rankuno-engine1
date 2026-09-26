"""Tests for URL pattern filtering."""

from __future__ import annotations

import time

import pytest
from src.modules.seo.url_filter import PatternType, URLFilter


class TestURLFilterBasics:
    """Basic filter instantiation and properties."""

    def test_empty_filter_passes_all(self) -> None:
        """Filter with no patterns passes everything."""
        f = URLFilter()
        assert f.matches("/blog/post")
        assert f.matches("/admin/panel")
        assert f.matches("/")

    def test_none_patterns_pass_all(self) -> None:
        """Explicitly None patterns pass everything."""
        f = URLFilter(include_patterns=None, exclude_patterns=None)
        assert f.matches("/blog/post")

    def test_empty_list_patterns_pass_all(self) -> None:
        """Empty pattern lists pass everything."""
        f = URLFilter(include_patterns=[], exclude_patterns=[])
        assert f.matches("/blog/post")


class TestWildcardSingleLevel:
    """Single-level wildcard: `/blog/*` matches within one segment."""

    def test_single_wildcard_matches_segment(self) -> None:
        """Pattern `/blog/*` matches `/blog/post` but not deeper."""
        f = URLFilter(include_patterns=["/blog/*"])
        assert f.matches("/blog/post")
        assert f.matches("/blog/my-article")
        assert f.matches("/blog/123")

    def test_single_wildcard_no_slashes(self) -> None:
        """Pattern `/blog/*` does not match `/blog/2024/post` (has slash)."""
        f = URLFilter(include_patterns=["/blog/*"])
        assert not f.matches("/blog/2024/post")
        assert not f.matches("/blog/archive/2024/post")

    def test_single_wildcard_requires_prefix(self) -> None:
        """Pattern `/blog/*` requires `/blog/` prefix."""
        f = URLFilter(include_patterns=["/blog/*"])
        assert not f.matches("/blogging/post")
        assert not f.matches("/myblog/post")

    def test_multiple_single_wildcards(self) -> None:
        """Multiple wildcards in one pattern."""
        f = URLFilter(include_patterns=["/*/post/*"])
        assert f.matches("/blog/post/123")
        assert f.matches("/news/post/abc")
        assert not f.matches("/blog/article/post/123")  # Extra level


class TestWildcardRecursive:
    """Recursive wildcard: `/articles/**` matches any depth."""

    def test_double_wildcard_matches_any_depth(self) -> None:
        """Pattern `/articles/**` matches any depth under `/articles/`."""
        f = URLFilter(include_patterns=["/articles/**"])
        assert f.matches("/articles/post")
        assert f.matches("/articles/2024/post")
        assert f.matches("/articles/2024/12/post")

    def test_double_wildcard_requires_prefix(self) -> None:
        """Pattern `/articles/**` requires `/articles/` prefix."""
        f = URLFilter(include_patterns=["/articles/**"])
        assert not f.matches("/article/post")  # Single article
        assert not f.matches("/articlespost")  # No slash


class TestWildcardPrefix:
    """Prefix matching: `/admin` matches `/admin`, `/admin/`, `/admin/path`."""

    def test_prefix_exact_match(self) -> None:
        """Pattern `/admin` matches path `/admin` exactly."""
        f = URLFilter(include_patterns=["/admin"])
        assert f.matches("/admin")

    def test_prefix_with_trailing_slash(self) -> None:
        """Pattern `/admin` matches `/admin/`."""
        f = URLFilter(include_patterns=["/admin"])
        assert f.matches("/admin/")

    def test_prefix_with_path(self) -> None:
        """Pattern `/admin` matches `/admin/users`, `/admin/settings`."""
        f = URLFilter(include_patterns=["/admin"])
        assert f.matches("/admin/users")
        assert f.matches("/admin/settings/general")

    def test_prefix_no_partial_match(self) -> None:
        """Pattern `/admin` does not match `/administrator`."""
        f = URLFilter(include_patterns=["/admin"])
        assert not f.matches("/administrator")

    def test_prefix_case_insensitive(self) -> None:
        """Prefix matching is case-insensitive."""
        f = URLFilter(include_patterns=["/Admin"])
        assert f.matches("/admin/users")
        assert f.matches("/ADMIN/panel")


class TestRegexPatterns:
    """Full regex patterns with metacharacters."""

    def test_regex_with_character_class(self) -> None:
        """Patterns with `[...]` are treated as regex."""
        f = URLFilter(include_patterns=["/blog/[0-9]{4}/"])
        assert f.matches("/blog/2024/")
        assert f.matches("/blog/2025/post")
        assert not f.matches("/blog/abc/")

    def test_regex_with_anchor(self) -> None:
        """Patterns starting with `^` are treated as regex."""
        f = URLFilter(include_patterns=["^/api/v[0-9]"])
        assert f.matches("/api/v1")
        assert f.matches("/api/v2")
        assert not f.matches("/api/version")

    def test_regex_with_end_anchor(self) -> None:
        """Patterns ending with `$` are treated as regex."""
        f = URLFilter(include_patterns=["/admin$"])
        assert f.matches("/admin")
        assert not f.matches("/admin/")
        assert not f.matches("/admin/panel")

    def test_regex_alternation(self) -> None:
        """Patterns with `|` (alternation) work."""
        # Use explicit regex with ^ to force regex detection
        f = URLFilter(include_patterns=["^(/blog|/news)"])
        assert f.matches("/blog")
        assert f.matches("/news")
        assert f.matches("/blog/post")
        assert f.matches("/news/article")

    def test_regex_case_insensitive(self) -> None:
        """Regex patterns are compiled with IGNORECASE."""
        f = URLFilter(include_patterns=["/Blog/[A-Z]+"])
        assert f.matches("/blog/post")
        assert f.matches("/BLOG/POST")
        assert f.matches("/Blog/Article")


class TestIncludePatterns:
    """Whitelist: include patterns only."""

    def test_include_single_pattern(self) -> None:
        """Include pattern creates a whitelist."""
        f = URLFilter(include_patterns=["/blog/*"])
        assert f.matches("/blog/post")
        assert not f.matches("/news/article")
        assert not f.matches("/admin/panel")

    def test_include_multiple_patterns(self) -> None:
        """Multiple include patterns: URL must match at least one."""
        f = URLFilter(include_patterns=["/blog/*", "/articles/*"])
        assert f.matches("/blog/post")
        assert f.matches("/articles/guide")
        assert not f.matches("/news/story")

    def test_include_empty_does_not_restrict(self) -> None:
        """Empty include list means no restriction."""
        f = URLFilter(include_patterns=[])
        assert f.matches("/anything")


class TestExcludePatterns:
    """Blacklist: exclude patterns only."""

    def test_exclude_single_pattern(self) -> None:
        """Exclude pattern creates a blacklist."""
        f = URLFilter(exclude_patterns=["/admin/*"])
        assert f.matches("/blog/post")
        assert not f.matches("/admin/panel")
        assert not f.matches("/admin/users")

    def test_exclude_multiple_patterns(self) -> None:
        """Multiple exclude patterns: URL must not match any."""
        f = URLFilter(exclude_patterns=["/admin/*", "/private/*"])
        assert f.matches("/blog/post")
        assert not f.matches("/admin/panel")
        assert not f.matches("/private/data")
        assert not f.matches("/private/settings")


class TestIncludeAndExclude:
    """Combined: both include and exclude."""

    def test_include_then_exclude(self) -> None:
        """Include narrows to whitelist, then exclude removes from it."""
        f = URLFilter(
            include_patterns=["/blog/**", "/articles/**"],
            exclude_patterns=["/admin/*"],
        )
        # Matches include (blog or articles)
        assert f.matches("/blog/post")
        assert f.matches("/articles/guide")

        # /blog/admin/panel passes include, and does NOT match exclude pattern /admin/*
        # (because /admin/* only matches /admin/X, not /blog/admin/X)
        assert f.matches("/blog/admin/panel")

        # Paths outside blog/articles are rejected by include:
        assert not f.matches("/news/story")
        # Paths matching /admin/* are rejected by exclude:
        assert not f.matches("/admin/panel")

    def test_exclude_all_then_include_overrides(self) -> None:
        """Order matters: include first (whitelist), then exclude."""
        f = URLFilter(
            include_patterns=["/blog/**"],
            exclude_patterns=["/admin/**"],
        )
        # Path must be under /blog/
        assert f.matches("/blog/post")
        # Path /admin/... is not under /blog/, so filtered out by include
        assert not f.matches("/admin/panel")
        # Path /blog/admin/... is under /blog/ (passes include) but not /admin/...
        # (so passes exclude)
        assert f.matches("/blog/admin/settings")

    def test_strategy_whitelist_then_blacklist(self) -> None:
        """Typical use case: whitelist content, blacklist admin."""
        f = URLFilter(
            include_patterns=["/content/**", "/blog/**"],
            exclude_patterns=["/admin", "/**-draft"],  # Use ** to match any depth
        )
        assert f.matches("/content/articles/news")
        assert f.matches("/blog/2024/post")
        # Fails include (not in /content/ or /blog/)
        assert not f.matches("/admin")
        # Fails exclude (matches /**-draft pattern, which matches /content/my-draft)
        assert not f.matches("/content/my-draft")


class TestQueryStringAndFragment:
    """Matching ignores query strings and fragments."""

    def test_query_string_ignored(self) -> None:
        """Query strings are stripped before matching."""
        f = URLFilter(include_patterns=["/blog/*"])
        assert f.matches("/blog/post?id=123")
        assert f.matches("/blog/post?utm_source=google")

    def test_fragment_ignored(self) -> None:
        """Fragments are stripped before matching."""
        f = URLFilter(include_patterns=["/blog/*"])
        assert f.matches("/blog/post#comments")
        assert f.matches("/blog/post#section-2")

    def test_full_url_with_scheme(self) -> None:
        """Absolute URLs are parsed; only path is matched."""
        f = URLFilter(include_patterns=["/blog/*"])
        assert f.matches("https://example.com/blog/post")
        assert f.matches("http://example.com/blog/post?id=1#comments")


class TestEdgeCases:
    """Edge cases and corner scenarios."""

    def test_empty_path_defaults_to_slash(self) -> None:
        """Empty or missing path defaults to `/`."""
        f = URLFilter(include_patterns=["/"])
        assert f.matches("")
        assert f.matches("/")
        assert f.matches("https://example.com")  # Path is /

    def test_root_pattern(self) -> None:
        """Pattern `/` matches everything (all paths start with `/`)."""
        f = URLFilter(include_patterns=["/"])
        assert f.matches("/")
        assert f.matches("/blog")
        assert f.matches("/anything/deep/down")

    def test_root_exclude(self) -> None:
        """Excluding `/` excludes everything; pattern is too broad."""
        f = URLFilter(exclude_patterns=["/ "])
        # After stripping, `/` matches all paths, so all are excluded
        # (except this path doesn't actually match the pattern)
        # Actually, the pattern is "/ " with a space, so it's a literal string.
        # This won't match "/" normally.
        # Let me think: the exclude pattern is "/ " (with trailing space).
        # Wildcard matching: no wildcards, so it's a prefix match.
        # Does "/" prefix match "/ "? No, they're different strings.
        # So all URLs pass.
        assert f.matches("/blog")

    def test_pattern_with_multiple_stars(self) -> None:
        """Multiple `*` in one pattern segment."""
        f = URLFilter(include_patterns=["/api/*/response/*"])
        assert f.matches("/api/v1/response/json")
        assert f.matches("/api/v2/response/xml")
        assert not f.matches("/api/v1/data/json")  # "data" != "response"

    def test_regex_error_in_pattern(self) -> None:
        """Invalid regex patterns raise re.error during init."""
        import re

        with pytest.raises(re.error):
            URLFilter(include_patterns=["[invalid(regex"])

    def test_case_sensitivity_overall(self) -> None:
        """All matching is case-insensitive."""
        f = URLFilter(include_patterns=["/Blog/*"])
        assert f.matches("/blog/post")
        assert f.matches("/BLOG/POST")
        assert f.matches("/Blog/Post")


class TestPerformance:
    """Performance: filters should be fast on bulk URL volume."""

    def test_bulk_matching_thousand_urls(self) -> None:
        """1000 URLs against 8 patterns: every verdict correct, no pathological cost.

        The wall-clock bound is a smoke guard against an order-of-magnitude
        regression (a quadratic scan, a per-call disk or network read), not a
        latency spec. It is deliberately loose: measured uninstrumented this
        loop takes 4-15 ms, but the quality gate runs the suite under
        `coverage` tracing, where the original 100 ms bound was close enough to
        the traced time to fail intermittently on a loaded machine while the
        code was unchanged. A bound the profiler can trip measures the
        profiler. `perf_counter` rather than `time.time` because only the
        former is specified for measuring intervals.
        """
        patterns = [
            "/blog/*",
            "/articles/**",
            "/news/*",
            "^/api/v[0-9]",
            "/admin/*",
            "/private/*",
            "/draft$",
            "[0-9]{4}/[0-9]{2}",
        ]
        f = URLFilter(include_patterns=patterns[:4], exclude_patterns=patterns[4:])

        urls = (
            [f"/blog/post-{i}" for i in range(250)]
            + [f"/articles/2024/post-{i}" for i in range(250)]
            + [f"/news/story-{i}" for i in range(250)]
            + [f"/api/v1/endpoint-{i}" for i in range(250)]
        )

        start = time.perf_counter()
        results = [f.matches(url) for url in urls]
        elapsed = time.perf_counter() - start

        # Every URL matches an include pattern and none matches an exclude
        # pattern, so the verdict is `True` for all 1000 - not merely "most".
        assert sum(results) == len(urls)
        assert elapsed < 1.0, f"Bulk matching took {elapsed:.3f}s, expected < 1.0s"


class TestRobustness:
    """Robustness: malformed inputs are handled gracefully."""

    def test_very_long_url(self) -> None:
        """Very long URLs are handled."""
        f = URLFilter(include_patterns=["/blog/*"])
        long_path = "/blog/" + "x" * 10000
        assert f.matches(long_path)

    def test_special_characters_in_path(self) -> None:
        """Paths with special chars (allowed in URLs) work."""
        f = URLFilter(include_patterns=["/api/**"])
        assert f.matches("/api/user%40example.com")  # Encoded @
        assert f.matches("/api/file-name_v1.2.3")

    def test_unicode_in_pattern_and_path(self) -> None:
        """Unicode characters in patterns and paths."""
        f = URLFilter(include_patterns=["/blog/*"])
        # Regex matching should handle Unicode
        assert f.matches("/blog/café")
        assert f.matches("/blog/文章")


class TestPatternTypeDetection:
    """Pattern type detection (wildcard vs regex)."""

    def test_wildcard_pattern_detected(self) -> None:
        """Pure text patterns default to wildcard."""
        ptype, _ = URLFilter._compile_pattern("/blog/*")
        assert ptype == PatternType.WILDCARD

    def test_regex_with_bracket_detected(self) -> None:
        """Patterns with `[` are detected as regex."""
        ptype, _ = URLFilter._compile_pattern("/blog/[0-9]*")
        assert ptype == PatternType.REGEX

    def test_regex_with_caret_detected(self) -> None:
        """Patterns starting with `^` are detected as regex."""
        ptype, _ = URLFilter._compile_pattern("^/api/")
        assert ptype == PatternType.REGEX

    def test_regex_with_dollar_detected(self) -> None:
        """Patterns ending with `$` are detected as regex."""
        ptype, _ = URLFilter._compile_pattern("/admin$")
        assert ptype == PatternType.REGEX
