"""Three domain-agnostic URL helpers the desktop worker needs without the engine.

`safe_split`, `site_host` and `registrable_domain` were born in
`src/modules/seo/page_classifier/url_rules.py`, but they are pure-stdlib facts
about web URLs — "split without raising", "which host names the site",
"which domain two hosts share" — with no knowledge of page classification. The
Screaming Frog worker's URL-list builder needs all three, and importing them
from `url_rules` ran `page_classifier/__init__.py`, which eagerly imports the
whole classification cascade. That one incidental import was most of what put
engine code inside the standalone worker (ADR 0030).

They live in `core` because they import nothing but the standard library and
the logger, which is what `core` is for. `url_rules` re-exports all three, so
every existing caller resolves to the same function objects as before.
"""

from __future__ import annotations

from urllib.parse import SplitResult, urlsplit

from src.core.logger import get_logger

__all__ = ["registrable_domain", "safe_split", "site_host"]

_logger = get_logger("core.url_hosts")


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
