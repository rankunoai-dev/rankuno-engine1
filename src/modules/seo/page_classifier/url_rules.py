"""Layer 0 URL rules — normalisation and instant classification, pre-fetch.

Everything here runs **before a network packet is sent**, which is the whole
point. `AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md` Rule 1: one SKU with 20
filter options generates 2^20 permutations, and a crawler that discovers this
by fetching them has already lost. Dropping them costs nothing here.

Two jobs:

1. **Normalise** a URL to a canonical dedup key — strip tracking parameters,
   sort remaining query parameters, unify trailing slashes, and fold `www.` and
   the scheme. Two URLs that render the same page must produce the same key.

   Locale prefixes are **not** folded by default: `/de/pricing/` is a different
   URL that Google indexes and ranks separately, and an audit that merges it
   away cannot report on it. See `normalize_url`.
2. **Classify instantly** where the URL alone is conclusive: the root path, a
   parameter matrix, a legal page.

Layer 0 is expected to settle roughly 65% of a typical site at ~0 cost. Every
page it resolves is a page that never reaches the paid Layer 3, which per
`docs/adr/0005` is the dominant term in the cost model.
"""

from __future__ import annotations

import re
from urllib.parse import SplitResult, parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from src.core.logger import get_logger
from src.modules.seo.page_classifier.schemas import (
    MAX_CRAWL_DEPTH,
    HierarchyLevel,
    PrimaryPageType,
)

__all__ = [
    "safe_split",
    "MAX_QUERY_PARAMS",
    "NON_PAGE_SUFFIXES",
    "TRACKING_PARAM_PREFIXES",
    "TRACKING_PARAMS",
    "depth_of",
    "TRAP_SEGMENT_MIN_LENGTH",
    "is_crawlable_url",
    "is_faceted_filter",
    "is_malformed_url",
    "is_spider_trap",
    "is_locale_segment",
    "MARKUP_MARKERS",
    "STRUCTURAL_ESCAPES",
    "decode_percent_escapes",
    "is_tracking_param",
    "normalize_path",
    "normalize_url",
    "registrable_domain",
    "same_site",
    "site_host",
    "strip_locale_prefix",
    "url_fast_path",
]

NON_PAGE_SUFFIXES = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".bmp",
    # Design sources. Never a landing page and never indexable, but WordPress
    # media libraries publish them into `attachment-sitemap.xml` alongside the
    # images. `.ai` is safe as a *suffix* test because it only matches a final
    # path segment containing a dot — `/solutions/ai/` and `/ai/` are untouched,
    # and the host is never examined, so an `.ai` domain is unaffected.
    ".eps",
    ".ai",
    ".psd",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".rss",
    ".atom",
    ".zip",
    ".gz",
    ".tar",
    ".rar",
    ".7z",
    ".mp4",
    ".mp3",
    ".avi",
    ".mov",
    ".wmv",
    ".wav",
    ".webm",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".exe",
    ".dmg",
    ".pkg",
    # Markdown. Observed live: allbirds.com/agents.md entered the graph as a
    # page and was classified UNKNOWN at 0.0 confidence — crawl budget spent on
    # something that can never be classified (build-log 0010 §7).
    ".md",
    ".markdown",
)
"""Path endings that are never an HTML page.

`.txt` is deliberately **absent**. `llms.txt` and `llms-full.txt` are the AI
crawler manifests Phase 7's answer-readiness audit reads, so excluding `.txt`
would blind a later phase to files it specifically needs.

Document formats — `.pdf`, `.doc(x)`, `.xls(x)`, `.ppt(x)`, `.csv` — are
deliberately **absent**, ruled on directly by the operator. A whitepaper, ebook
or datasheet is an indexable B2B asset that ranks, and an audit that cannot see
them is missing real surface. They do classify poorly, because the pipeline
parses HTML; the answer to that is a document page type, not hiding them from
discovery. Design *sources* are a different matter and are excluded above: an
`.eps` is not something anyone lands on.

Lives here rather than in `discovery_parsers` because it is a property of a URL
string, and because three discovery paths need it. A second copy alongside the
sitemap parser was the original proposal and would have drifted from this one
the first time either was edited."""

MAX_QUERY_PARAMS = 5
"""Above this, a URL is a filter permutation rather than a page (Rule 4).

Chosen to sit above legitimate use — pagination plus a sort plus a category is
three — and below the combinatorial range where faceted navigation lives."""

TRACKING_PARAMS = frozenset(
    {
        "gclid",
        "fbclid",
        "msclkid",
        "dclid",
        "gclsrc",
        "mc_cid",
        "mc_eid",
        "igshid",
        "ref",
        "referrer",
        "source",
        "qid",
        "sr",
        "th",
        "psc",
        "_ga",
        "_gl",
        "yclid",
        "twclid",
        "ttclid",
        "si",
        "trk",
        "sessionid",
        "session_id",
        "phpsessid",
        "jsessionid",
    }
)
"""Parameters that never change rendered content.

`ref` and `qid` are the Amazon case specifically: they turn one product page
into fifty distinct URLs in a crawl frontier."""

TRACKING_PARAM_PREFIXES = ("utm_", "pf_rd_", "pd_rd_", "_encoding", "spm_", "hsa_", "vero_")
"""Prefix families. `pf_rd_*` alone accounts for a dozen Amazon parameters."""

# A region-qualified locale (en-gb, pt_BR, zh-Hans) is unambiguous: no ordinary
# path segment looks like one.
_REGIONAL_LOCALE_RE = re.compile(r"^[a-z]{2}[-_][a-z]{2,4}$", re.IGNORECASE)

# Bare two-letter codes are NOT safe to detect by shape. `/dp/` is an Amazon
# product path, `/ai/` and `/hr/` are ordinary content sections, and treating
# any two-letter segment as a language silently deletes them from the dedup key.
# Only genuine ISO 639-1 codes are eligible, and callers who know a site's real
# locales should pass them explicitly via `known_locales`.
_ISO_639_1 = frozenset(
    {
        "ar",
        "bg",
        "bn",
        "cs",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "fa",
        "fi",
        "fr",
        "he",
        "hi",
        "hu",
        "id",
        "is",
        "ja",
        "ko",
        "lt",
        "lv",
        "ms",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sl",
        "sr",
        "sv",
        "th",
        "tr",
        "uk",
        "ur",
        "vi",
        "zh",
    }
)
"""Deliberately excludes `it` (Italian) and `hr` (Croatian).

Both collide with extremely common English content sections — `/it/` for IT
services, `/hr/` for human resources — and mis-stripping a real content section
is a worse failure than missing a locale fold. Sites genuinely serving those
languages should pass `known_locales` explicitly."""

# Slugs that identify a legal or infrastructure page on essentially any site.
_LEGAL_SLUGS = frozenset(
    {
        "privacy-policy",
        "privacy",
        "terms",
        "terms-of-service",
        "terms-and-conditions",
        "terms-of-use",
        "cookie-policy",
        "cookies",
        "legal",
        "disclaimer",
        "accessibility",
        "gdpr",
        "imprint",
        "impressum",
        "sitemap",
        "404",
        "search",
    }
)

# Parameter names that indicate faceted navigation rather than a distinct page.
_FILTER_PARAMS = frozenset(
    {"color", "colour", "size", "price", "brand", "sort", "sort_by", "orderby", "filter", "facet"}
)


def is_tracking_param(name: str) -> bool:
    """Report whether a query parameter is pure tracking noise.

    Args:
        name: Query parameter name.

    Returns:
        True when the parameter can be dropped without changing the page.
    """
    lowered = name.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PARAM_PREFIXES)


def is_locale_segment(segment: str, known_locales: frozenset[str] | None = None) -> bool:
    """Report whether a path segment is a locale prefix rather than content.

    Args:
        segment: A single path segment.
        known_locales: Locales actually observed on this site. When supplied,
            **only** these match — which is the reliable mode, since the crawler
            has seen the site's real locale set.

    Returns:
        True when the segment should be treated as a locale.
    """
    candidate = segment.lower()
    if known_locales is not None:
        return candidate in {locale.lower() for locale in known_locales}
    if _REGIONAL_LOCALE_RE.match(candidate):
        return True
    return candidate in _ISO_639_1


def strip_locale_prefix(
    path: str, known_locales: frozenset[str] | None = None
) -> tuple[str, str | None]:
    """Remove a leading locale segment from a path.

    `/de/software/` and `/software/` are the same page in different languages
    and must share a dedup key, or a bilingual site's graph doubles.

    Args:
        path: URL path.
        known_locales: Locales observed on this site. Supplying them removes all
            guesswork; without them a conservative ISO 639-1 list is used.

    Returns:
        The path without its locale prefix, and the locale that was removed
        (`None` if there was none). Trailing-slash form is preserved so this
        composes predictably with `normalize_path`.
    """
    segments = [s for s in path.split("/") if s]
    if not segments or not is_locale_segment(segments[0], known_locales):
        return path or "/", None

    remainder = segments[1:]
    if not remainder:
        return "/", segments[0].lower()

    trailing = "/" if path.endswith("/") else ""
    return "/" + "/".join(remainder) + trailing, segments[0].lower()


STRUCTURAL_ESCAPES: frozenset[str] = frozenset({"%2F", "%3F", "%23", "%25", "%5C"})
"""Percent-escapes that must survive decoding, because decoding them changes
what the URL *means* rather than how it is spelled.

`/a%2Fb` is one path segment containing a slash; `/a/b` is two segments. RFC 3986
§2.2 calls these reserved for exactly this reason — the escaped and unescaped
forms are not equivalent, and folding them together would merge two different
addresses into one node. `%25` is here because it is the escape character itself:
decoding it first would make `%2520` decode twice.
"""

_ESCAPE_RUN = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")


def decode_percent_escapes(path: str) -> str:
    """Decode the escapes in a path that carry no structural meaning.

    RFC 3986 §6.2.2.2: percent-encoding an octet that did not need encoding does
    not create a different URL. `%6D%79` and `my` address the same resource, and
    so do `%E2%80%91` and a raw `‑` (U+2011) — the browser encodes the raw form
    before sending it, so the server receives the same bytes either way.

    The engine did not know that. Measured across 65 stored crawls and 476,067
    URLs, three pages were held twice under two spellings of one address, and the
    audit reported each pair to the client as a duplicate-content defect *on
    their site*. One of them reached a client report:

        gep.com/blog/technology/procurement%E2%80%91ai%E2%80%91agents-…
        gep.com/blog/technology/procurement‑ai‑agents-…

    **Runs are decoded whole, never escape by escape.** A UTF-8 character is
    several octets — `%E2%80%91` is three — and `unquote("%E2")` alone yields a
    replacement character, silently corrupting the key it was meant to repair.
    An earlier draft of this function did exactly that and merged nothing while
    appearing to work.

    Invalid UTF-8 is left encoded rather than replaced. A path that does not
    decode is not a path whose meaning we know, and `errors="replace"` would map
    several distinct broken URLs onto one key.

    Args:
        path: URL path, encoded or not.

    Returns:
        The path with non-structural escapes decoded. Structural ones
        (`STRUCTURAL_ESCAPES`) are preserved exactly.
    """

    def decode_run(match: re.Match[str]) -> str:
        out: list[str] = []
        pending: list[str] = []
        for escape in _ESCAPE.findall(match.group(0)):
            if escape.upper() in STRUCTURAL_ESCAPES:
                out.append(_decode(pending))
                pending = []
                out.append(escape)
            else:
                pending.append(escape)
        out.append(_decode(pending))
        return "".join(out)

    return _ESCAPE_RUN.sub(decode_run, path)


def _decode(escapes: list[str]) -> str:
    """Decode consecutive escapes as one UTF-8 sequence, or leave them alone."""
    if not escapes:
        return ""
    joined = "".join(escapes)
    try:
        return unquote(joined, encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return joined


def normalize_path(path: str) -> str:
    """Canonicalise a path to its dedup form.

    Decoded, lowercased, one trailing slash, no empty segments.

    Decoding runs first and is the reason the split on `/` is safe to do
    afterwards: `decode_percent_escapes` preserves `%2F`, so nothing it returns
    can grow a segment boundary that was not already there.

    Segments are stripped of surrounding whitespace, which decoding can expose —
    `/youtube-ranking-factors%20` becomes a segment with a trailing space, and no
    server serves a different page at that address. Interior spaces are kept:
    `Infosys ESG - climate change.pdf` is a real published filename.
    """
    segments = [s.strip() for s in decode_percent_escapes(path).split("/")]
    kept = [s for s in segments if s]
    if not kept:
        return "/"
    return "/" + "/".join(s.lower() for s in kept) + "/"


_logger = get_logger("modules.seo.url_rules")


def safe_split(url: str) -> SplitResult | None:
    """Split a URL, or return `None` when the standard library refuses.

    `urlsplit` raises `ValueError` on some inputs — an unbalanced bracket gives
    "Invalid IPv6 URL", and a bracketed host that is not a valid IP fails
    `_check_bracketed_host`, both added as 3.11 hardening. Neither is rare in
    the wild: a page only has to contain one such `<a href>`.

    Left unguarded, that exception propagates out of `normalize_url`, which is
    called for every URL entering the graph — so a single malformed link on any
    page failed the entire crawl. Observed live on highradius.com.

    `None` means "not a usable URL", which every caller can act on. Raising is
    not useful here: the crawl cannot fix the markup, and there is nothing to
    retry.
    """
    try:
        return urlsplit(url.strip())
    except ValueError as exc:
        _logger.debug("url_unsplittable", extra={"url": url[:120], "error": str(exc)})
        return None


def is_crawlable_url(url: str) -> bool:
    """Report whether a URL plausibly addresses an HTML page.

    Tested on the *path* only, so a query string cannot mask an extension and
    `?download=report.jpg` is not mistaken for an image.

    Matching is a suffix test rather than a parsed extension. `PurePath.suffix`
    would be equivalent on POSIX and wrong on Windows, where `Path` treats a
    backslash as a separator and parses drive letters — neither of which is
    true of a URL.
    A path with an interior dot such as `/v1.0/details` has no matching suffix
    and is kept, which is the case that matters.

    Args:
        url: Absolute or relative URL.

    Returns:
        True when the URL should be allowed into the graph. Unparseable URLs
        return True: they are not media, and rejecting them here would hide them
        from the reporting that exists to surface them.
    """
    parts = safe_split(url)
    if parts is None:
        return True
    return not parts.path.lower().endswith(NON_PAGE_SUFFIXES)


TRAP_SEGMENT_MIN_LENGTH = 3
"""Shortest segment whose repetition is evidence of a trap.

Locale and shorthand segments — `en`, `de`, `fr`, `iki`, `lp` — legitimately
recur in a path, so only longer segments count. Measured against 55,645 real
URLs from six sites, this threshold produced no false positive."""


MARKUP_MARKERS: tuple[str, ...] = ("<", ">", "href=", "“", "”")
"""Substrings that mean a URL was built out of broken markup, not a link.

Every one of these is illegal in a URL path unencoded, and meaningless in it
encoded. They appear because an unclosed tag or a smart-quoted attribute made
the HTML parser treat prose as an `href`:

* `highradius.com/about/news/highradius-launches-livecube/<a href=` — an anchor
  that was never closed.
* `kinsta.com/blog/how-to-use-mailchimp/%E2%80%9C>MailChimp</a>%20per%20...` — a
  curly quote instead of `"` around the attribute, which swallowed an entire
  paragraph of Italian body copy into the address.
* `gep.com/<nolink>` and `linear.app/team/%3Cteam%20ID%3E/new` — documentation
  placeholders published as real links.

Measured across 65 stored crawls and 392,835 URLs: 100 distinct matches, and
every one inspected was fabricated. No legitimate page URL was caught.
"""

_LEADING_SPACE_PATH = re.compile(r"^/(?:%20|%09|%0[ad]|\s)", re.I)
"""A path that begins with whitespace, raw or percent-encoded.

The signature of `href=" blog/post/"`. `urljoin` strips a leading space before
resolving, so the DOM path is safe; a sitemap `<loc>` carrying the same defect
is not, and neither is an href whose space survived as `%20`.

Why *leading* only, and this is the whole subtlety
--------------------------------------------------
Whitespace elsewhere in a path is usually **legitimate**. Rejecting it outright
would have deleted real, indexable assets — measured on the stored crawls:

* `infosys.com/.../pdf/Infosys ESG - climate change.pdf` — a published report
  whose filename genuinely contains spaces.
* `infosys.com/confluence/images/.../digital%20bank%20in%20a%20bank_icici%20bank.pdf`
  — the same thing, percent-encoded.

387 URLs across the corpus carry whitespace that is part of a real filename. A
path *beginning* with a space is different in kind: no page is served at a path
whose first character is a space, so the 20 distinct URLs this matches are
artefacts rather than pages.
"""


def is_malformed_url(url: str) -> bool:
    """Report whether a URL was fabricated by broken markup rather than linked.

    Two independent signatures, both measured against the stored corpus before
    being adopted (see the constants above). Kept apart from `is_spider_trap`
    for the same reason that rule is kept apart from `is_crawlable_url`: a loop
    is a real URL generated too many times, whereas this is not a URL at all,
    and a report that merges the two can name neither cause.

    Checked on the **path** only. Restricting it there loses nothing — verified
    at 100 matches either way across the corpus — and avoids refusing a query
    string that legitimately carries a comparison operator.

    Percent-decoded before matching, because `%3C` and `<` are the same
    character and a fabricated URL is as likely to arrive encoded as raw.

    Args:
        url: Absolute or relative URL.

    Returns:
        True when the URL should never enter the graph. Unparseable URLs return
        False: they are refused earlier, by `safe_split`, and claiming them here
        would attribute them to the wrong cause in the report.
    """
    parts = safe_split(url)
    if parts is None:
        return False
    if _LEADING_SPACE_PATH.match(parts.path):
        return True
    decoded = unquote(parts.path)
    return any(marker in decoded for marker in MARKUP_MARKERS)


def is_spider_trap(url: str) -> bool:
    """Report whether a URL is a self-referential crawl loop rather than a page.

    A template that emits a *relative* href — `href="software/b2b-payments/"`
    with no leading slash — resolves against whatever page it appears on. Land
    on the result and the same href resolves again, one level deeper, forever.
    `urljoin` is behaving correctly; the site's markup is wrong, and a crawler
    that follows it generates URLs without limit.

    This is not hypothetical. On a HighRadius crawl 21,242 of 33,447 URLs were
    this one bug, all descending from `/software/b2b-payments/credit-card-
    surcharge/`. They fill the page budget, and each one is fetched and
    classified as though it were a distinct page.

    Two independent triggers:

    * A path segment longer than `TRAP_SEGMENT_MIN_LENGTH` appearing more than
      once. A real path does not repeat a meaningful segment; `/en-gb/en-gb/…`
      and `/resources/templates/templates/` are both malformed.
    * More than `MAX_CRAWL_DEPTH` segments, which is already the ceiling beyond
      which `url_fast_path` treats a URL as a trap rather than content. Reusing
      that constant rather than introducing a second one keeps the two from
      drifting apart.

    Deliberately separate from `is_crawlable_url`: one is about what a URL
    *addresses*, this is about how it was *constructed*, and counting them
    together would make the report unable to say which problem a site has.

    Args:
        url: Absolute or relative URL.

    Returns:
        True when the URL should be refused. An unparseable URL is not a trap —
        `safe_split` already reports it, and claiming otherwise would attribute
        it to the wrong cause.
    """
    parts = safe_split(url)
    if parts is None:
        return False

    segments = [s for s in (parts.path or "").split("/") if s]
    if len(segments) > MAX_CRAWL_DEPTH:
        return True

    counts: dict[str, int] = {}
    for segment in segments:
        if len(segment) > TRAP_SEGMENT_MIN_LENGTH:
            lowered = segment.lower()
            counts[lowered] = counts.get(lowered, 0) + 1
            if counts[lowered] > 1:
                return True
    return False


def site_host(netloc: str) -> str:
    """Reduce a netloc to the host that identifies the site.

    Drops the port and a leading `www.`, which is a serving convention rather
    than a different site. Every other subdomain is kept: `blog.example.com` and
    `shop.example.com` really are separate properties, and folding them would
    turn a bounded crawl into an unbounded one.

    Args:
        netloc: Host, optionally with port and credentials.

    Returns:
        The comparable host, lower-cased.
    """
    host = netloc.lower().rsplit("@", 1)[-1]
    if host.startswith("["):
        # A bracketed IPv6 literal is full of colons that are not the port
        # separator. Only one after the closing bracket is.
        closing = host.find("]")
        host = host[: closing + 1] if closing != -1 else host
    else:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "ac", "gov", "edu", "gob", "or", "ne"})
"""Second-level labels that behave like a suffix: `co.uk`, `com.au`, `ac.jp`.

A heuristic, and named as one. The correct answer needs the Public Suffix List,
which is a network-fetched dataset with its own update problem; this covers the
shapes that actually appear in client work and errs toward treating two hosts as
*different* domains, which is the safer mistake — it under-reports a
relationship rather than inventing one.
"""


def registrable_domain(host: str) -> str:
    """The domain two hosts must share to be the same organisation.

    `smartstaging-auth.gep.com` and `www.gep.com` are both `gep.com`;
    `gep.com` and `example.com` are not. This exists because "not the site we
    crawled" and "a subdomain of the site we crawled" are very different
    findings, and the first real Search Console export made the difference
    urgent: 558 rows on two gep.com subdomains read as ordinary off-site noise.

    Args:
        host: A bare host, already stripped of port and credentials.

    Returns:
        The registrable domain, or the host unchanged when it has too few
        labels or is an IP literal.
    """
    lowered = host.lower().strip(".")
    if not lowered or lowered.startswith("["):
        return lowered
    labels = lowered.split(".")
    if len(labels) < 3:
        return lowered
    if all(label.isdigit() for label in labels):
        # An IPv4 literal has no registrable domain, and slicing its last two
        # labels invents one: `1.2.3.4` became `3.4`, which would make every
        # host on 10.x look like it shared an organisation.
        return lowered
    if labels[-2] in _SECOND_LEVEL and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_site(a: str, b: str) -> bool:
    """Whether two URLs belong to the same site.

    `www.example.com` and `example.com` are one site served two ways, and an
    exact host comparison treats them as two. That is not cosmetic: a crawl
    seeded at the bare host reads a homepage whose links are all absolute and
    `www`-qualified, discards every one of them as external, and reports a
    one-page site. The reverse happens just as easily — most hosts redirect one
    form to the other, and which form the operator types is arbitrary.

    Args:
        a: First URL.
        b: Second URL.

    Returns:
        True when both resolve to the same site host. An unparseable URL is
        never the same site as anything, including itself.
    """
    first, second = safe_split(a), safe_split(b)
    if first is None or second is None:
        return False
    return site_host(first.netloc) == site_host(second.netloc)


def normalize_url(
    url: str, *, strip_locale: bool = False, known_locales: frozenset[str] | None = None
) -> str:
    """Reduce a URL to its canonical dedup key.

    Applies Rules 1 and 2 of the Amazon-scale specification: drop tracking
    parameters, then sort what remains so parameter order cannot fork one page
    into several frontier entries.

    Locale folding is **off by default**, reversing the original choice. That
    choice was made to stop "a bilingual site's graph doubling", which is right
    for a crawler that only wants unique content and wrong for an audit tool:
    Google indexes `/de/pricing/` and `/pricing/` as separate URLs, ranks them
    separately, and hreflang correctness is an entire audit category we cannot
    report on for pages we have merged away.

    Measured on highradius.com, folding put `/de/software/order-to-cash/` and
    the English page on one key, so the surviving node's language depended on
    which variant was crawled first — a German `Startseite` root in an English
    tree. The damage was limited there only because their slugs are translated.
    A site using identical slugs per locale — very common — would lose every
    variant silently.

    The cost is real and worth stating: a multilingual site now reports more
    pages than it used to, and those pages consume the page budget.

    Args:
        url: Absolute or relative URL.
        strip_locale: Fold locale variants onto one key. Enable only when
            duplicate *content* is the question and distinct URLs are not.
        known_locales: Locales observed on this site, passed through to
            `strip_locale_prefix`.

    Returns:
        The normalised URL.
    """
    parts = safe_split(url)
    if parts is None:
        # Unparseable. Returned as-is so it still has a stable identity in the
        # graph and can be reported, rather than aborting the crawl that found
        # it.
        return url.strip()

    path = parts.path or "/"
    if strip_locale:
        path, _ = strip_locale_prefix(path, known_locales)
    path = normalize_path(path)

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not is_tracking_param(k)
    ]
    query = urlencode(sorted(kept))

    # `http://x`, `https://x`, `https://www.x` and `http://www.x` are one page
    # served four ways, and each was becoming its own graph node with its own
    # trail. On highradius.com that split `/resources/?ps=templates` into three
    # nodes and left 11 header-menu links unmatchable against the page set.
    #
    # Only the `www.` label is folded, never another subdomain: `blog.x.com` is
    # a different property and merging it would collapse a real distinction. The
    # port is kept — `localhost:8000` and `localhost:9000` are different servers
    # — which is why `site_host` cannot be reused here; it drops the port for
    # same-site comparison, which is a different question.
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    scheme = parts.scheme.lower()
    if scheme in {"http", "https"}:
        scheme = "https"
    return urlunsplit((scheme, netloc, path, query, ""))


def depth_of(
    path: str, *, strip_locale: bool = True, known_locales: frozenset[str] | None = None
) -> int:
    """Count path segments, capped at the crawl-trap ceiling.

    This is *path* depth, not click depth. The two are deliberately different:
    a blog post linked from the homepage has click depth 1 but lives several
    segments down, and conflating them is the click-depth fallacy the engine
    exists to avoid.

    Args:
        path: URL path.
        strip_locale: Whether a locale prefix should be excluded from the count.
        known_locales: Locales observed on this site.

    Returns:
        Segment count, clamped to `MAX_CRAWL_DEPTH`.
    """
    if strip_locale:
        path, _ = strip_locale_prefix(path, known_locales)
    return min(len([s for s in path.split("/") if s]), MAX_CRAWL_DEPTH)


def is_faceted_filter(url: str) -> bool:
    """Report whether a URL is a filter permutation rather than a page.

    Two independent triggers, either sufficient: more surviving parameters than
    a real page plausibly needs, or the presence of a known facet parameter.

    Args:
        url: The URL to test.

    Returns:
        True when the URL should be classified as a faceted filter unfetched.
    """
    parts = safe_split(url)
    if parts is None or not parts.query:
        return False

    meaningful = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not is_tracking_param(k)
    ]
    if len(meaningful) > MAX_QUERY_PARAMS:
        return True
    return any(k.lower() in _FILTER_PARAMS for k, _ in meaningful)


def url_fast_path(url: str) -> tuple[HierarchyLevel, PrimaryPageType] | None:
    """Classify a URL where the URL alone is conclusive.

    Deliberately conservative. A wrong answer here is never revisited by a later
    layer, so this only fires on patterns that are unambiguous on any site.
    Anything that merely *looks* like a product or a service is left for the
    structural signals, which have evidence this function does not.

    Args:
        url: The URL to classify.

    Returns:
        A `(level, page_type)` pair, or `None` if the URL is not conclusive.
    """
    parts = safe_split(url)
    if parts is None:
        return None
    path, _ = strip_locale_prefix(parts.path or "/")
    segments = [s.lower() for s in path.split("/") if s]

    # Root is the homepage, but only when no query survives normalisation:
    # `/?utm_source=x` is the homepage, `/?s=query` is a search results page.
    if not segments:
        meaningful = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not is_tracking_param(k)
        ]
        if not meaningful:
            return (HierarchyLevel.L0_HOMEPAGE, PrimaryPageType.HOMEPAGE)
        return (HierarchyLevel.UTILITY_PAGE, PrimaryPageType.FACETED_FILTER)

    if is_faceted_filter(url):
        return (HierarchyLevel.UTILITY_PAGE, PrimaryPageType.FACETED_FILTER)

    if any(segment in _LEGAL_SLUGS for segment in segments):
        return (HierarchyLevel.UTILITY_PAGE, PrimaryPageType.UTILITY_LEGAL)

    # Beyond the depth ceiling a URL is a crawl trap, not content.
    if len(segments) > MAX_CRAWL_DEPTH:
        return (HierarchyLevel.UTILITY_PAGE, PrimaryPageType.FACETED_FILTER)

    return None
