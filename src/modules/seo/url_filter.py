"""URL filtering by regex or wildcard patterns during discovery.

This module applies include/exclude patterns to URLs during crawl discovery,
allowing users to whitelist certain paths (e.g., `/blog/*`) and/or blacklist
others (e.g., `/admin/*`).

Design rationale
----------------
Filtering is applied at the `SiteGraph.add()` entry point, after media and
malformed URL checks but before node creation. This ensures:

- Patterns are evaluated once per discovered URL, not per fetch
- The graph never holds filtered-out URLs, so counts stay accurate
- Filtering respects the normalized key, same as deduplication
- No performance penalty unless patterns are provided

Pattern formats
---------------
Two formats are supported:

**Wildcard patterns:**
- `/blog/*` matches `/blog/post-1` (single level, no slashes in match)
- `/articles/**` matches `/articles/2024/post` (recursive, any depth)
- `/admin` matches `/admin`, `/admin/`, `/admin/path` (prefix match)

**Regex patterns:**
- `/blog/[0-9]{4}/.*` matches `/blog/2024/my-post` (full Python regex)
- Must be valid Python regex; compiled with `re.IGNORECASE`
- Autodetection: patterns starting with `^` or `$`, or containing `[`, are
  assumed to be regex. Ambiguous patterns (pure text) default to wildcard.

Application order
-----------------
1. If `include_patterns` → URL must match **at least one**
2. Then if `exclude_patterns` → URL must **not** match **any**
3. If neither → URL passes (default behavior)
4. Matching is against the normalized URL path (no query string, no fragment)

This means include is a whitelist and exclude is a blacklist. Both can be
active in one crawl: include first narrows to matching URLs, then exclude
removes exceptions from that set.
"""

from __future__ import annotations

import re
from enum import Enum
from urllib.parse import urlparse

__all__ = ["PatternType", "URLFilter"]


class PatternType(Enum):
    """Kind of pattern for matching."""

    WILDCARD = "wildcard"
    """Simple glob: `*` (single segment), `**` (recursive), or prefix."""

    REGEX = "regex"
    """Full Python regex, case-insensitive."""


class URLFilter:
    """Applies include/exclude patterns to URLs.

    A filter is instantiated once per crawl and called for every discovered
    URL. Patterns are compiled on init; matching is fast.

    Attributes:
        include_patterns: User-supplied list of patterns (before compilation).
        exclude_patterns: User-supplied list of patterns (before compilation).
    """

    def __init__(
        self,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        """Create a filter from user patterns.

        Args:
            include_patterns: Whitelist. If provided, only URLs matching at
                least one pattern pass. `None` or empty disables.
            exclude_patterns: Blacklist. URLs matching any pattern are dropped.
                `None` or empty disables.
        """
        self.include_patterns = include_patterns or []
        self.exclude_patterns = exclude_patterns or []

        # Pre-compile patterns on init for fast matching.
        self._compiled_include: list[tuple[PatternType, re.Pattern[str] | str]] = [
            self._compile_pattern(p) for p in self.include_patterns
        ]
        self._compiled_exclude: list[tuple[PatternType, re.Pattern[str] | str]] = [
            self._compile_pattern(p) for p in self.exclude_patterns
        ]

    def matches(self, url: str) -> bool:
        """Check if a URL passes the filter.

        Args:
            url: Absolute or relative URL. Matching is against the path only.

        Returns:
            `True` if the URL should be included in the crawl, `False` if it
            should be skipped.
        """
        # Extract path from URL. For relative URLs (e.g., "/blog/post"),
        # urlparse treats them as path directly.
        parsed = urlparse(url)
        path = parsed.path or "/"

        # Apply whitelist: if include patterns exist, URL must match at least one
        if self.include_patterns and not any(
            self._match_single(path, p, ptype) for ptype, p in self._compiled_include
        ):
            return False

        # Apply blacklist: if exclude patterns exist, URL must not match any
        if self.exclude_patterns:
            return not any(
                self._match_single(path, p, ptype) for ptype, p in self._compiled_exclude
            )

        # Nothing excluded it, so the default is to crawl.
        return True

    @staticmethod
    def _compile_pattern(pattern: str) -> tuple[PatternType, re.Pattern[str] | str]:
        """Detect pattern type and compile if needed.

        Heuristic: if pattern contains regex metacharacters (`^`, `$`, `[`),
        or is a bare URL path, assume regex. Otherwise, assume wildcard.

        Args:
            pattern: User-supplied pattern string.

        Returns:
            Tuple of (pattern type, compiled regex or wildcard string).

        Raises:
            re.error: If regex pattern is syntactically invalid.
        """
        # Regex indicators: starts with ^, ends with $, or contains [
        if pattern.startswith("^") or pattern.endswith("$") or "[" in pattern:
            # Compile as regex (will raise re.error if invalid)
            compiled_re = re.compile(pattern, re.IGNORECASE)
            return (PatternType.REGEX, compiled_re)
        # Treat as wildcard; no compilation needed
        return (PatternType.WILDCARD, pattern)

    @staticmethod
    def _match_single(path: str, pattern: re.Pattern[str] | str, pattern_type: PatternType) -> bool:
        """Match a single pattern against a path.

        Args:
            path: Normalized URL path (e.g., `/blog/post`).
            pattern: Compiled regex or wildcard string.
            pattern_type: Kind of pattern.

        Returns:
            `True` if the path matches the pattern.
        """
        if pattern_type == PatternType.REGEX and isinstance(pattern, re.Pattern):
            # Regex: use search (not match, which anchors to start)
            return bool(pattern.search(path))
        # Wildcard: custom matching logic
        if isinstance(pattern, str):
            return URLFilter._wildcard_match(path, pattern)
        return False

    @staticmethod
    def _wildcard_match(path: str, pattern: str) -> bool:
        """Match wildcard pattern against path.

        Patterns:
        - `/blog/*` matches `/blog/post` but not `/blog/2024/post`
        - `/articles/**` matches `/articles/post` and `/articles/2024/post`
        - `/admin` matches `/admin`, `/admin/`, `/admin/anything`

        Args:
            path: Normalized URL path.
            pattern: Wildcard pattern string.

        Returns:
            `True` if path matches the pattern.
        """
        # Recursive wildcard: ** matches zero or more path segments
        if "**" in pattern:
            # Convert ** to .* for regex matching, but we must do this carefully
            # to avoid converting ** to .[^/]* when we replace * later.
            # Use a placeholder for ** first.
            placeholder = "\x00DOUBLE_STAR\x00"
            regex_pattern = pattern.replace("**", placeholder)
            # Now replace single * with [^/]* (won't affect the placeholder)
            regex_pattern = regex_pattern.replace("*", "[^/]*")
            # Finally, replace the placeholder with .*
            regex_pattern = regex_pattern.replace(placeholder, ".*")
            # Ensure anchoring: pattern should match from start
            regex_pattern = f"^{regex_pattern}"
            try:
                compiled = re.compile(regex_pattern, re.IGNORECASE)
                return bool(compiled.match(path))
            except re.error:
                # Invalid wildcard pattern; treat as no match
                return False

        # Single wildcard: * matches one segment only (no slashes)
        if "*" in pattern:
            # Replace * with [^/]* (match anything except /)
            regex_pattern = pattern.replace("*", "[^/]*")
            regex_pattern = f"^{regex_pattern}$"
            try:
                compiled = re.compile(regex_pattern, re.IGNORECASE)
                return bool(compiled.match(path))
            except re.error:
                return False

        # No wildcard: prefix match
        # `/admin` matches `/admin`, `/admin/`, `/admin/path`
        path_lower = path.lower()
        pattern_lower = pattern.lower()

        if path_lower == pattern_lower:
            return True

        # Special case: root pattern `/` matches everything
        if pattern_lower == "/":
            return True

        # Prefix match: check if path starts with pattern + /
        return path_lower.startswith(pattern_lower + "/")
