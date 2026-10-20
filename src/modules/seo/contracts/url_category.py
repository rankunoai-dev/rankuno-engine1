"""Path categories for the URL exports: the first path segment of an address.

Why a URL path and not the navigation menu: the menu is a property of the
rendered site, and a page the menu does not reach has no category at all. The
first path segment is computed from the address alone, so every crawled URL gets
one, the same answer comes out on every run, and an analyst can predict it from
the URL in the row.

Why it lives in `contracts`: the URL exports are written by `page_classifier`, and
ADR 0011 allows that package to share code with `deliverables` only through this
one. The category is a fact about an address, not about either side's workbook,
so it belongs in the shared package.

Why it is duplicated in TypeScript: `rankuno-ui/src/lib/urlCategory.ts` must
group URLs the same way this module does. Both read the shared fixture
`tests/fixtures/url_category/parity.json`, so a change to one side that the
other does not follow fails a test rather than producing two different
categorisations of the same site.

The address is split with the same regular expression in both languages, not with
`urllib` on this side and `URL` on the other. The two standard libraries disagree
about percent-encoding and malformed authorities, and a parity test that relied
on them agreeing would be testing their accident.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["HOMEPAGE_CATEGORY", "UNCATEGORISED", "category_key", "category_sort_key"]

HOMEPAGE_CATEGORY: Final[str] = "/"
"""The category of the site root. It sorts ahead of every other category."""

UNCATEGORISED: Final[str] = "(uncategorised)"
"""Shown for an address that does not parse to a host. Sorted last."""

_ABSOLUTE_HTTP: Final[re.Pattern[str]] = re.compile(r"^https?://([^/?#]*)([^?#]*)", re.IGNORECASE)
"""Group 1 is the authority, group 2 the path. Query and fragment are discarded."""


def _split(url: str) -> tuple[str, str] | None:
    """The authority and path of an absolute http(s) address, or `None` if it has no host."""
    match = _ABSOLUTE_HTTP.match(url)
    if match is None or not match.group(1):
        return None
    return match.group(1), match.group(2)


def category_key(url: str) -> str:
    """The category an address belongs to.

    The first non-empty path segment, lowercased. A site root, with or without a
    query or fragment, is `/`. An address that does not parse to a host is
    `(uncategorised)`. Lowercasing folds `/Blog` and `/blog` into one category,
    which is what a reader of the export expects; the segment is not decoded, so
    `%E2%82%AC` stays as written.

    Args:
        url: A crawled page address.

    Returns:
        The category key.
    """
    parts = _split(url)
    if parts is None:
        return UNCATEGORISED
    segments = [segment for segment in parts[1].split("/") if segment]
    return segments[0].lower() if segments else HOMEPAGE_CATEGORY


def category_sort_key(url: str) -> tuple[int, str, str]:
    """Sort order for URL rows: homepage first, categories A to Z, uncategorised last.

    The tier is decided by whether the address parsed, not by comparing category
    strings. A real path segment named `(uncategorised)` must not be ordered with
    the addresses that failed to parse. The URL breaks ties, so the order is the
    same on every run.

    Args:
        url: A crawled page address.

    Returns:
        A tuple to pass as a sort key.
    """
    if _split(url) is None:
        return (2, UNCATEGORISED, url)
    key = category_key(url)
    tier = 0 if key == HOMEPAGE_CATEGORY else 1
    return (tier, key, url)
