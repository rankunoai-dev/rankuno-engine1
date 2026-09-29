"""Turn a finished Rankuno crawl into an approved Screaming Frog URL list.

Screaming Frog's `--crawl` mode follows links, so it can only ever audit what
the site itself points at. The URLs it therefore *cannot* reach are exactly
the ones worth auditing: orphans, and pages published only in a sitemap. This
engine already holds both. `--crawl-list` is how they get handed over.

**List mode is not a site crawl.** `--crawl-list` makes Screaming Frog fetch
the supplied URLs and nothing else — it does not spider outward from them, so
the resulting export describes a set of pages, never a site. Nothing built
from it may be presented as a crawl of the site (see `FIELD_MAPPING`'s
`url_list_source` row, and ADR 0022).

What this module is, precisely
------------------------------
The list is generated and frozen at **preview** time, before a human approves
anything, and the bytes are what the SHA-256 in every downstream gate names.
Generating at download time instead would mean the operator approves a
fingerprint of one list and the worker fetches whatever the source crawl
happens to say later — or nothing at all, if the crawl was deleted in between.
Approval has to bind bytes that already exist.

The pipeline, in this order, every stage counted:

1. **Dedupe**, after dropping the fragment. `#pricing` and `#contact` on one
   page are one page to a crawler, and sending both spends two of a licensed
   seat's URLs on one fetch. A query string is *not* dropped: `?page=2` is a
   different resource and collapsing it would silently drop real pages.
2. **Scheme** — `http`/`https` only. A crawl graph can hold `mailto:` and
   `tel:` links; Screaming Frog would report each as an error row.
3. **Registrable domain** — anything outside the source crawl's own domain is
   removed and *counted*, never a reason to refuse the whole list. A crawl of
   one site routinely holds a handful of outbound links, and refusing a
   10,000-URL list over 18 of them would be useless.
4. **Host safety** — `UrlSafetyPolicy`, once per unique host. A same-site list
   has one to five hosts; validating per URL would mean 50,000 `getaddrinfo`
   calls for a list that resolves two names (`UrlSafetyPolicy.validate` has no
   cache — `src/core/url_safety.py`).
5. **Ceiling** — over it, this **refuses**. See `UrlListTooLargeError`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from enum import StrEnum

from pydantic import Field

from src.core.errors import RankunoError, UnsafeUrlError
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.page_classifier.url_rules import registrable_domain, safe_split, site_host

__all__ = [
    "LIST_ENCODING",
    "LIST_LINE_ENDING",
    "SAMPLE_SIZE",
    "EmptyUrlListError",
    "UrlListCounts",
    "UrlListManifest",
    "UrlListSource",
    "UrlListTooLargeError",
    "build_url_list",
    "fingerprint",
    "read_url_list_file",
    "render_url_list",
]

_logger = get_logger(__name__)

LIST_ENCODING = "utf-8"
"""UTF-8 **without** a BOM, and the reader strips one if it finds one.

Screaming Frog is a Java application and reads a list file as UTF-8; a BOM
would be decoded as a zero-width no-break space glued to the front of the
first URL, which then fails to resolve — one silently missing row at the top
of every list. Nothing this module writes carries one, and
`read_url_list_file` removes one from anything that does, so a file an
operator re-saved from Notepad still works."""

LIST_LINE_ENDING = "\r\n"
"""CRLF. The consumer is a Windows desktop application reading a file this
engine may have written on a Linux cloud host, and CRLF is what every Windows
text reader — including Notepad, where an operator will open it to check —
handles without turning the file into one long line. A Java `BufferedReader`
treats a bare LF, a bare CR and CRLF identically, so CRLF costs one byte per
URL and removes the only ambiguity that matters."""

SAMPLE_SIZE = 3
"""How many URLs the approval summary shows. A bare hash is unapprovable; the
first three addresses plus the count are what let a human tell "the crawl I
meant" from "a different crawl entirely" (ADR 0013 condition 8)."""


class UrlListSource(StrEnum):
    """Which set of a finished crawl's URLs to hand to Screaming Frog.

    Two members, both operator-chosen. There is no default: "which URLs"
    is the whole decision being approved, and a default would make the
    larger, slower, licence-spending option reachable without a choice.
    """

    ORPHANS = "orphans"
    """Only the pages no internal link reaches — `EngineGapReason.
    SITEMAP_ORPHAN` from a saved reconciliation. The recommended source, and
    the one that answers the question list mode exists for.

    Available **only** for a crawl that has already been cross-checked
    against a Screaming Frog export, because that comparison is what defines
    an orphan. `GET /jobs/{id}/url-list/sources` reports availability rather
    than leaving a UI to guess."""

    ALL = "all"
    """Every URL the crawl discovered. Large, and mostly pages Screaming Frog
    would have reached by itself — offered because a re-audit of a whole
    discovered set is a legitimate, occasional request, not because it is the
    normal one."""


class UrlListCounts(StrictModel):
    """What each filtering stage removed, so a UI can say so truthfully.

    Every field is a count of URLs *dropped by that stage*, in pipeline
    order, except `source_rows` and `kept`. They reconcile exactly:
    `source_rows - duplicates_dropped - non_http_dropped - off_domain_dropped
    - unsafe_host_dropped == kept`. A test pins that identity, because a
    count a UI renders as "Excluded 18 external URLs" is a claim about data
    the operator cannot check.
    """

    source_rows: int = Field(ge=0)
    duplicates_dropped: int = Field(default=0, ge=0)
    non_http_dropped: int = Field(default=0, ge=0)
    off_domain_dropped: int = Field(default=0, ge=0)
    unsafe_host_dropped: int = Field(default=0, ge=0)
    kept: int = Field(default=0, ge=0)


class UrlListManifest(StrictModel):
    """Everything about a generated list except the bytes themselves.

    The bytes live in the dispatch store, keyed by `sha256`; this is what
    travels through an API response, a confirmation modal, and
    `describe_invocation`. `sha256` is the only field any gate compares.

    Attributes:
        source: Which set was asked for.
        source_job_id: The Rankuno crawl the URLs came from.
        source_label: That crawl's human-facing label, so the approval
            summary can name it rather than showing a bare job id.
        registrable_domain: The domain every kept URL is inside. Recorded
            because it is the rule that produced `counts.off_domain_dropped`,
            and an operator querying that number needs to see the rule.
        url_count: How many URLs the list holds. Also the denominator the
            finished job's truncation check uses.
        sha256: Hex digest of the exact rendered bytes.
        sample: The first `SAMPLE_SIZE` URLs, verbatim.
        counts: The full filtering account.
    """

    source: UrlListSource
    source_job_id: str = Field(min_length=1, max_length=64)
    source_label: str = Field(default="", max_length=400)
    registrable_domain: str = Field(default="", max_length=253)
    url_count: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample: tuple[str, ...] = ()
    counts: UrlListCounts


class UrlListTooLargeError(RankunoError):
    """The list is over the configured ceiling, so nothing was generated.

    A refusal, not a silent trim, and not an offered truncation. Three
    reasons, in order of weight:

    1. A truncated list changes *what was audited* without changing what the
       operator was shown. "12,000 URLs, first three: ..." describes a list
       that would have been cut to 10,000 — the sample and the count would
       both still be true and the result would still be wrong.
    2. It would break the one check this feature makes newly possible: a run
       that crawls fewer pages than the list holds is evidence of the
       Screaming Frog free-tier cap (`license_check.FREE_TIER_URL_CEILING`).
       A deliberately shortened list and a licence-capped run would produce
       the same shortfall, and the check would have to be abandoned.
    3. The operator has a real alternative that is not "accept less data":
       `UrlListSource.ORPHANS`, which is the recommended source anyway and is
       typically two orders of magnitude smaller.
    """

    def __init__(self, *, url_count: int, ceiling: int, source: UrlListSource) -> None:
        """Record both numbers so the message can name them and a caller can too."""
        self.url_count = url_count
        self.ceiling = ceiling
        self.source = source
        alternative = (
            ""
            if source is UrlListSource.ORPHANS
            else " Choose 'Orphans Only', which is smaller and is the recommended source."
        )
        super().__init__(
            f"this crawl's '{source.value}' URL list holds {url_count:,} URLs, over the "
            f"{ceiling:,} ceiling (SCREAMING_FROG_URL_LIST_MAX_URLS), so nothing was "
            f"generated. A shorter list is not silently substituted because the run would "
            f"then audit fewer pages than the approval says.{alternative}"
        )


class EmptyUrlListError(RankunoError):
    """Filtering left no URLs at all, so there is nothing to dispatch.

    Refused rather than queued: a `--crawl-list` run against an empty file is
    a Screaming Frog process that starts, finds nothing, exports nothing, and
    reports a successful crawl of zero pages. The operator would see a
    finished job and no data, with no record of why.
    """

    def __init__(self, counts: UrlListCounts, *, source: UrlListSource) -> None:
        """Record the counts, which are the whole explanation."""
        self.counts = counts
        self.source = source
        super().__init__(
            f"the '{source.value}' URL list is empty after filtering: "
            f"{counts.source_rows:,} URL(s) in, {counts.duplicates_dropped:,} duplicate, "
            f"{counts.non_http_dropped:,} not http/https, "
            f"{counts.off_domain_dropped:,} outside the crawl's own domain, "
            f"{counts.unsafe_host_dropped:,} on a host that failed the SSRF check. "
            f"Nothing was dispatched."
        )


def fingerprint(body: bytes) -> str:
    """SHA-256 of the exact rendered bytes, lowercase hex.

    The only identity any gate compares. Computed over the rendered file, not
    over the URL list in memory, so line endings and encoding are inside the
    thing that is signed — a worker that re-rendered the same URLs with LF
    would get a different digest and be refused, which is correct: it is not
    the file that was approved.
    """
    return hashlib.sha256(body).hexdigest()


def render_url_list(urls: Iterable[str]) -> bytes:
    """Render URLs as the file Screaming Frog reads. See `LIST_ENCODING`."""
    text = "".join(f"{url}{LIST_LINE_ENDING}" for url in urls)
    return text.encode(LIST_ENCODING)


def read_url_list_file(body: bytes) -> tuple[str, ...]:
    """Parse rendered list bytes back into URLs, tolerating a BOM and any newline.

    Used by the worker to count what it received and by tests to assert a
    round trip. Blank lines are dropped: a trailing line ending is normal, and
    an operator who opened the file and pressed enter should not add an empty
    crawl target.
    """
    text = body.decode(LIST_ENCODING, errors="replace").lstrip("﻿")
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def _strip_fragment(url: str) -> str:
    """Drop `#...`. See this module's docstring for why fragments and not queries."""
    return url.split("#", 1)[0].strip()


def _host_of(url: str) -> str | None:
    """The comparable host, or `None` when the URL cannot be split at all."""
    parts = safe_split(url)
    if parts is None or not parts.netloc:
        return None
    return site_host(parts.netloc)


def _dedupe(urls: Iterable[str], counts: dict[str, int]) -> Iterator[str]:
    """Yield fragment-stripped URLs, first occurrence wins."""
    seen: set[str] = set()
    for raw in urls:
        counts["source_rows"] += 1
        url = _strip_fragment(raw)
        if not url or url in seen:
            counts["duplicates_dropped"] += 1
            continue
        seen.add(url)
        yield url


def _same_scheme_and_domain(
    urls: Iterable[str], *, domain: str, counts: dict[str, int]
) -> Iterator[str]:
    """Drop non-web schemes, then anything outside the crawl's own domain."""
    for url in urls:
        parts = safe_split(url)
        if parts is None or parts.scheme.lower() not in {"http", "https"}:
            counts["non_http_dropped"] += 1
            continue
        host = _host_of(url)
        if host is None or (domain and registrable_domain(host) != domain):
            counts["off_domain_dropped"] += 1
            continue
        yield url


def _safe_hosts(urls: Iterable[str], *, policy: UrlSafetyPolicy) -> frozenset[str]:
    """Validate each *unique* host once, and return the ones that passed.

    One `UrlSafetyPolicy.validate()` per distinct host, not per URL: that
    method performs an uncached `getaddrinfo` on every call, so a 50,000-URL
    list would otherwise be 50,000 DNS lookups for the one or two names it
    actually resolves. The URL handed to `validate` is `scheme://host/` — the
    path plays no part in any check the policy makes, and building it this way
    means one hostile path cannot poison a host every other URL shares.
    """
    allowed: set[str] = set()
    checked: set[str] = set()
    for url in urls:
        parts = safe_split(url)
        if parts is None or parts.netloc in checked:
            continue
        checked.add(parts.netloc)
        try:
            policy.validate(f"{parts.scheme.lower()}://{parts.netloc}/")
        except UnsafeUrlError as exc:
            _logger.warning(
                "sf_url_list_host_refused", extra={"host": parts.netloc, "reason": str(exc)}
            )
            continue
        allowed.add(parts.netloc)
    return frozenset(allowed)


def build_url_list(
    urls: Iterable[str],
    *,
    source: UrlListSource,
    source_job_id: str,
    source_label: str,
    base_url: str,
    max_urls: int,
    policy: UrlSafetyPolicy,
) -> tuple[UrlListManifest, bytes]:
    """Filter, cap, render and fingerprint one crawl's URLs.

    Args:
        urls: The raw source URLs, in any order, with duplicates. Consumed
            lazily — a caller streaming a 93 MB result file never materialises
            more than the kept set (`src.core.json_stream`).
        source: Which set was asked for. Carried through to the manifest and
            into the refusal messages.
        source_job_id: The crawl these came from.
        source_label: That crawl's human-facing label, for the approval text.
        base_url: The crawl's own root. Its registrable domain is the
            in-scope rule; an unparseable `base_url` disables the domain
            filter rather than silently emptying the list.
        max_urls: The ceiling. Exceeding it refuses.
        policy: SSRF policy, applied per unique host.

    Returns:
        The manifest and the exact rendered bytes it fingerprints.

    Raises:
        UrlListTooLargeError: More kept URLs than `max_urls`.
        EmptyUrlListError: Filtering left nothing to crawl.
    """
    tally = {
        "source_rows": 0,
        "duplicates_dropped": 0,
        "non_http_dropped": 0,
        "off_domain_dropped": 0,
        "unsafe_host_dropped": 0,
    }
    base_host = _host_of(base_url)
    domain = registrable_domain(base_host) if base_host else ""
    in_scope = list(_same_scheme_and_domain(_dedupe(urls, tally), domain=domain, counts=tally))

    allowed_netlocs = _safe_hosts(in_scope, policy=policy)
    kept: list[str] = []
    for url in in_scope:
        parts = safe_split(url)
        if parts is None or parts.netloc not in allowed_netlocs:
            tally["unsafe_host_dropped"] += 1
            continue
        kept.append(url)

    counts = UrlListCounts(**tally, kept=len(kept))
    if not kept:
        raise EmptyUrlListError(counts, source=source)
    if len(kept) > max_urls:
        raise UrlListTooLargeError(url_count=len(kept), ceiling=max_urls, source=source)

    body = render_url_list(kept)
    manifest = UrlListManifest(
        source=source,
        source_job_id=source_job_id,
        source_label=source_label,
        registrable_domain=domain,
        url_count=len(kept),
        sha256=fingerprint(body),
        sample=tuple(kept[:SAMPLE_SIZE]),
        counts=counts,
    )
    _logger.info(
        "sf_url_list_built",
        extra={
            "source": source.value,
            "source_job_id": source_job_id,
            "kept": len(kept),
            "off_domain_dropped": counts.off_domain_dropped,
            "sha256": manifest.sha256,
        },
    )
    return manifest, body
