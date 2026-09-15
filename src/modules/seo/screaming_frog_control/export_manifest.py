"""The `--export-tabs` / `--bulk-export` CLI argument manifest (ADR 0013).

Every filename `load_screaming_frog_bundle`
(`src/modules/seo/deliverables/screaming_frog_adapter.py`) and
`ISSUE_CATALOGUE` (`src/modules/seo/contracts/catalogue.py`) can consume is
produced by exactly one argument below. Derived mechanically from
`catalogue.py`'s own `sf_sources` filenames, not guessed: verified against a
real `ScreamingFrogSEOSpiderCli.exe 19.4 --help export-tabs` / `--help
bulk-export` dump and five real headless crawls of `https://example.com`
(2026-09-15), which confirmed the naming transform Screaming Frog applies to
turn an argument string into its output filename — lowercase; strip `-`,
`<`, `>`, `&`; `.` -> `_`; ` ` and `:` -> `_` — and, for `--bulk-export`'s
nested "Category:Submenu:Export Name" arguments, that only the last
`:`-separated segment contributes to the filename.

Needs-verification note (ADR 0013 investigation): five target filenames embed
a numeric threshold instead of the literal placeholder word Screaming Frog's
`--help` shows (e.g. `H1:Over X Characters` wrote `h1_over_70_characters.csv`
in the live test run — confirmed). The other four
(`Meta Description:Below/Over X Pixels`, `Page Titles:Below/Over X Pixels`)
were not independently run; they are included here on the same mechanism,
matching the numbers `catalogue.py` already hardcodes (400/985/200/561), but
that specific number is only produced under this exact filename if Screaming
Frog's *active* configuration carries the same threshold — this engine's
`.seospiderconfig` templates (`template_registry.py`) must not override these
five settings, and a template that does will silently change these five
output filenames, not error. Flagged rather than asserted as fact.
"""

from __future__ import annotations

from typing import Final

__all__ = ["BULK_EXPORT", "EXPORT_TABS", "SPINE_TAB"]

SPINE_TAB: Final[str] = "Internal:All"
"""Produces `internal_all.csv`, the page spine `load_screaming_frog_bundle`
requires non-optionally (`SPINE_FILE`). Confirmed live."""

EXPORT_TABS: Final[tuple[str, ...]] = (
    "Canonicals:Canonical Is Relative",
    "Canonicals:Canonicalised",
    "Canonicals:Missing",
    "Canonicals:Multiple",
    "Canonicals:Multiple Conflicting",
    "Canonicals:Non-Indexable Canonical",
    "Canonicals:Outside <head>",
    "Canonicals:Unlinked",
    "Content:Exact Duplicates",
    "Content:Grammar Errors",
    "Content:Lorem Ipsum Placeholder",
    "Content:Low Content Pages",
    "Content:Near Duplicates",
    "Content:Soft 404 Pages",
    "Content:Spelling Errors",
    "Directives:Nofollow",
    "Directives:Noindex",
    "H1:Duplicate",
    "H1:Missing",
    "H1:Multiple",
    "H1:Over X Characters",
    "Hreflang:Inconsistent Language & Region Return Links",
    "Hreflang:Incorrect Language & Region Codes",
    "Hreflang:Missing",
    "Hreflang:Missing Return Links",
    "Hreflang:Missing Self Reference",
    "Hreflang:Missing X-Default",
    "Hreflang:Multiple Entries",
    "Hreflang:Noindex Return Links",
    "Hreflang:Non-200 hreflang URLs",
    "Hreflang:Non-Canonical Return Links",
    "Hreflang:Not Using Canonical",
    "Hreflang:Outside <head>",
    "Hreflang:Unlinked hreflang URLs",
    "Meta Description:Below X Pixels",
    "Meta Description:Duplicate",
    "Meta Description:Missing",
    "Meta Description:Multiple",
    "Meta Description:Outside <head>",
    "Meta Description:Over X Pixels",
    "Page Titles:Below X Pixels",
    "Page Titles:Duplicate",
    "Page Titles:Missing",
    "Page Titles:Multiple",
    "Page Titles:Outside <head>",
    "Page Titles:Over X Pixels",
    "Page Titles:Same as H1",
    "Pagination:Multiple Pagination URLs",
    "Pagination:Non-Indexable",
    "Pagination:Pagination Loop",
    "Pagination:Pagination URL Not in Anchor Tag",
    "Pagination:Sequence Error",
    "Pagination:Unlinked Pagination URLs",
    "Response Codes:Internal Blocked by Robots.txt",
    "Response Codes:Internal Client Error (4xx)",
    "Response Codes:Internal No Response",
    "Response Codes:Internal Redirect Chain",
    "Response Codes:Internal Redirect Loop",
    "Response Codes:Internal Redirection (3xx)",
    "Response Codes:Internal Server Error (5xx)",
    "Security:Bad Content Type",
    "Security:Form on HTTP URL",
    "Security:HTTP URLs",
    "Security:Missing Content-Security-Policy Header",
    "Security:Missing HSTS Header",
    "Security:Missing Secure Referrer-Policy Header",
    "Security:Missing X-Content-Type-Options Header",
    "Security:Missing X-Frame-Options Header",
    "Security:Mixed Content",
    "Sitemaps:Non-Indexable URLs in Sitemap",
    "Sitemaps:Orphan URLs",
    "Sitemaps:URLs not in Sitemap",
    "Sitemaps:XML Sitemap with over 50k URLs",
    "Structured Data:Missing",
    "Structured Data:Parse Errors",
    "Structured Data:Validation Errors",
    "Structured Data:Validation Warnings",
    "URL:Contains Space",
    "URL:Multiple Slashes",
    "URL:Parameters",
    "URL:Repetitive Path",
    "URL:Underscores",
    "URL:Uppercase",
)
"""One argument per `--export-tabs Tab:Filter` this engine needs. `SPINE_TAB`
is kept separate since it is mandatory, not part of the issue catalogue."""

BULK_EXPORT: Final[tuple[str, ...]] = (
    "Canonicals:Canonicalised Inlinks",
    "Canonicals:Non-Indexable Canonical Inlinks",
    "Response Codes:Internal:Internal Blocked Resource Inlinks",
    "Response Codes:Internal:Internal Blocked by Robots.txt Inlinks",
    "Response Codes:Internal:Internal Client Error (4xx) Inlinks",
    "Response Codes:Internal:Internal No Response Inlinks",
    "Response Codes:Internal:Internal Redirection (3xx) Inlinks",
    "Response Codes:Internal:Internal Server Error (5xx) Inlinks",
    "Security:Form URL Insecure",
    "Security:HTTP URLs Inlinks",
    "Security:Protocol-Relative Outlinks",
    "Security:Unsafe Cross-Origin Links",
)
"""One argument per `--bulk-export` edge-list file the catalogue needs."""
