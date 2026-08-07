"""Site profiling — one probe pass per crawl job.

Produces the `SiteProfile` that `weights.get_weight_profile()` consumes. Until
this module existed that contract had no producer, so every call site passed
`None` and the seam had nothing to select on.

Rankuno is an agency: every engagement is a site nobody has seen before, and
nobody will state in advance whether it is Shopify or a headless SPA. So the
platform is **detected at runtime**, never configured per client.

Cost is deliberately trivial — six requests against a crawl of tens of thousands
of pages. It runs once per job, never per page.

Detection is evidence-based, not guesswork:

| Signal | Establishes |
| :--- | :--- |
| `/wp-json/wp/v2/types` returns JSON | WordPress |
| `/products.json` or `/collections.json` returns JSON | Shopify |
| Homepage HTML has a hydration root but no content | Client-rendered |
| `robots.txt` sitemap entries | Grouped sitemap taxonomy |
| Locale-prefixed sitemap entries | Multi-region routing |

A negative result is as useful as a positive one. A site with no content API and
an empty hydration root is `HEADLESS`, which changes the weight vector as much
as detecting WordPress would.
"""

from __future__ import annotations

import json
import re

from src.core.logger import get_logger
from src.core.robots import parse_robots_txt
from src.integrations.http_fetcher import FetchResult, HttpFetcher
from src.modules.seo.page_classifier.url_rules import is_locale_segment
from src.modules.seo.page_classifier.weights import CmsFamily, SiteProfile

__all__ = [
    "CATALOGUE_PROBES",
    "PROBE_PATHS",
    "WORDPRESS_PROBE",
    "detect_client_side_rendering",
    "locales_from_sitemaps",
    "probe_site",
]

_logger = get_logger("modules.seo.site_profile")

WORDPRESS_PROBE = "/wp-json/wp/v2/types"
"""Cheapest authoritative WordPress signal — a small JSON document that only a
WordPress REST API serves. `/wp-json/` alone is often reverse-proxied."""

CATALOGUE_PROBES = ("/products.json", "/collections.json")
"""Shopify's public catalogue endpoints. Presence also implies a catalogue,
which independently sets `has_catalogue`."""

PROBE_PATHS = (WORDPRESS_PROBE, *CATALOGUE_PROBES, "/robots.txt", "/")

# Hydration roots left behind by the common client-rendered frameworks.
_HYDRATION_ROOT_RE = re.compile(
    r'<div[^>]+id\s*=\s*["\'](root|__next|app|__nuxt|svelte)["\'][^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)

# Text remaining after stripping markup, below which a page has no server-side
# content worth parsing. A shell page is typically well under 200 characters.
_MIN_SERVER_RENDERED_CHARS = 200

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)


def _is_json_response(result: FetchResult) -> bool:
    """Whether a probe returned a genuine JSON document.

    Checked by parsing, not by trusting `Content-Type`: a great many sites
    answer unknown paths with a 200 HTML error page, and a soft 404 that claims
    to be JSON would otherwise be read as a positive detection.
    """
    if not result.ok or not result.body.strip():
        return False
    try:
        json.loads(result.body)
    except (json.JSONDecodeError, ValueError):
        return False
    return True


def detect_client_side_rendering(html: str) -> bool:
    """Report whether a page's content is rendered by the browser, not the server.

    Two conditions must both hold: a recognised hydration root is present, and
    the document carries almost no text once markup is stripped. Either alone
    produces false positives — plenty of server-rendered React sites keep a
    `<div id="root">`, and a genuinely thin page is not a SPA.

    Args:
        html: Raw homepage HTML.

    Returns:
        True when a headless browser would be required to see the real DOM.
    """
    if not html:
        return False

    if not _HYDRATION_ROOT_RE.search(html):
        return False

    without_code = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", without_code)
    return len(" ".join(text.split())) < _MIN_SERVER_RENDERED_CHARS


def locales_from_sitemaps(sitemap_urls: tuple[str, ...]) -> tuple[str, ...]:
    """Extract locale prefixes declared by a site's own sitemap entries.

    This is the reliable way to learn a site's locales: it is the site telling
    us, rather than us guessing from two-letter path segments — the guess that
    corrupted `/dp/` in cycle 0002.

    Args:
        sitemap_urls: Sitemap URLs, typically from robots.txt.

    Returns:
        Sorted, de-duplicated locale prefixes.
    """
    found: set[str] = set()
    for url in sitemap_urls:
        path = re.sub(r"^[a-z]+://[^/]+", "", url, flags=re.IGNORECASE)
        for segment in (s for s in path.split("/") if s):
            if is_locale_segment(segment):
                found.add(segment.lower())
            break  # Only the first segment can be a locale prefix.
    return tuple(sorted(found))


def probe_site(fetcher: HttpFetcher, base_url: str) -> SiteProfile:
    """Discover a site's platform characteristics with a handful of requests.

    Probe failures are never fatal. A site that blocks `/wp-json/` is not
    WordPress *as far as we can tell*, which is the correct conclusion to draw
    and is exactly what an `UNKNOWN` family means.

    Args:
        fetcher: Safety-wired fetcher. Every probe inherits SSRF validation,
            robots compliance and per-host throttling from it.
        base_url: Site root, e.g. `https://www.example.com/`.

    Returns:
        The discovered profile. Never raises for an unprofilable site.
    """
    root = base_url.rstrip("/") or base_url

    wordpress = _is_json_response(_safe_probe(fetcher, f"{root}{WORDPRESS_PROBE}"))
    catalogue = any(
        _is_json_response(_safe_probe(fetcher, f"{root}{path}")) for path in CATALOGUE_PROBES
    )

    robots_result = _safe_probe(fetcher, f"{root}/robots.txt")
    sitemaps = parse_robots_txt(robots_result.body).sitemaps if robots_result.ok else ()

    homepage = _safe_probe(fetcher, f"{root}/")
    client_side = detect_client_side_rendering(homepage.body) if homepage.is_html else False

    family = _resolve_family(wordpress=wordpress, catalogue=catalogue, client_side=client_side)

    profile = SiteProfile(
        cms_family=family,
        renders_client_side=client_side,
        has_catalogue=catalogue,
        locale_prefixes=locales_from_sitemaps(sitemaps),
    )

    _logger.info(
        "site_profiled",
        extra={
            "base_url": root,
            "cms_family": family,
            "client_side": client_side,
            "has_catalogue": catalogue,
            "locales": profile.locale_prefixes,
            "weight_profile": profile.weight_profile_name,
        },
    )
    return profile


def _resolve_family(*, wordpress: bool, catalogue: bool, client_side: bool) -> CmsFamily:
    """Pick the CMS family from the probe results.

    WordPress is checked first: a WooCommerce store answers both the WordPress
    probe and a catalogue probe, and its `/wp-json/` parent IDs are the stronger
    signal of the two.
    """
    if wordpress:
        return CmsFamily.WORDPRESS
    if catalogue:
        return CmsFamily.SHOPIFY
    if client_side:
        return CmsFamily.HEADLESS
    return CmsFamily.UNKNOWN


def _safe_probe(fetcher: HttpFetcher, url: str) -> FetchResult:
    """Fetch a probe URL, converting any failure into a benign 404 result.

    A probe is a question, and "no" is a valid answer. Letting a refused or
    unreachable probe propagate would mean one blocked endpoint aborts the whole
    crawl before it starts.
    """
    try:
        return fetcher.fetch(url)
    except Exception as exc:  # noqa: BLE001 - a probe must never abort a crawl
        _logger.debug("probe_failed", extra={"url": url, "error": str(exc)})
        return FetchResult(requested_url=url, final_url=url, status_code=404)
