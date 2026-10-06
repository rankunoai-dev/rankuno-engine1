"""The job bundle: one finished local crawl, as the cloud accepts it (ADR 0034).

A bundle is the unit `scripts/push_job_to_cloud.py` uploads and
`POST /api/v1/jobs/import` validates. It is versioned (`format` + `version`)
because it is a persisted contract between two builds that are upgraded at
different times — a workstation can be weeks behind the cloud.

What it deliberately does not carry
-----------------------------------
No `org_id`, no job id, no `has_*` flags and no telemetry: `extra="forbid"`
rejects them outright. Each of those is something the *server* decides — the
org comes from the verified session, the id from the store, the flags from
what was actually written, the telemetry from the result. A client able to
state any of them could file a job under another org or make the UI advertise
a result that is not there.

No checkpoint, reconciliation or performance report in v1. A checkpoint holds
URLs only and exists to resume a crawl, which an imported job never does.

URL schemes
-----------
Everything here is rendered by the UI, and several fields become `href`s. A
crawled site controls what it links to and what it declares as canonical, so a
`javascript:` value is a stored-XSS payload the moment it reaches a link.
`audit_url_schemes` refuses the whole bundle rather than repairing it: a
silently rewritten crawl would no longer be the crawl that ran.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, model_validator

from src.core.job_provenance import (
    INSTANCE_ID_PATTERN,
    SOURCE_JOB_ID_PATTERN,
    SOURCE_LABEL_PATTERN,
)
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.nav_tree_parser import NavNode
from src.modules.seo.page_classifier.tool import PageClassificationInput, PageClassificationOutput

__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "CANONICAL_URL_FIELDS",
    "MAX_BUNDLE_HOMEPAGE_BYTES",
    "NOT_A_LINK_URL_FIELDS",
    "STRICT_URL_FIELDS",
    "BundleSource",
    "JobImportBundle",
    "audit_url_schemes",
    "url_scheme",
]

BUNDLE_FORMAT = "rankuno.job-bundle"
BUNDLE_VERSION = 1

MAX_BUNDLE_HOMEPAGE_BYTES = 5 * 1024 * 1024
"""A homepage body larger than this is left out by the CLI and refused by the server."""

_CLOCK_SKEW = timedelta(minutes=5)
"""How far in the future a crawl's finish time may be before it is refused."""

_ALLOWED_SCHEMES = frozenset({"http", "https"})

STRICT_URL_FIELDS = frozenset(
    {
        "result.base_url",
        "result.discovery.base_url",
        "result.pages.url",
        "result.pages.final_url",
        "result.pages.redirect_chain",
        "result.pages.nav_parent_url",
        "result.navigation.roots.url",
        "request.base_url",
        "request.seed_urls",
        "request.exclude_urls",
    }
)
"""Fields that must be http/https with a host. Each is a URL the crawler fetched,
was redirected to or was told to use, so anything else is not a real crawl."""

CANONICAL_URL_FIELDS = frozenset({"result.pages.canonical_url"})
"""A site's *claim* about itself, recorded verbatim. Real crawls carry malformed
values (`www.http://example.com/...` in 10 of 1,333 local results), so only a
real non-http scheme is refused: no scheme, or a dotted prefix that is a broken
host rather than a scheme, is accepted as text."""

NOT_A_LINK_URL_FIELDS = frozenset({"result.gsc.property_url", "request.gsc_property_url"})
"""URL-named fields not walked: a Search Console property is legitimately
`sc-domain:example.com`, and neither is ever rendered as a link."""

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*$")
_TAB_OR_NEWLINE = re.compile(r"[\t\n\r]")
_C0_AND_SPACE = "".join(chr(code) for code in range(0x21))
"""What the WHATWG parser strips from both ends before reading anything."""

_Check = Callable[[str], bool]


def url_scheme(value: str) -> str | None:
    r"""The scheme a browser would read from `value`, lowercased, or `None`.

    Follows the WHATWG URL parser's first steps rather than `urlsplit`, because
    the browser is the consumer that matters: it strips leading and trailing
    C0 controls and spaces and deletes every tab and newline *before* reading
    the scheme, so `" java\tscript:alert(1)"` is a `javascript:` URL to a
    browser while `urlsplit` reports no scheme at all.
    """
    cleaned = _TAB_OR_NEWLINE.sub("", value.strip(_C0_AND_SPACE))
    head, sep, _rest = cleaned.partition(":")
    if not sep or not _SCHEME.match(head):
        return None
    return head.lower()


def _strict_ok(value: str) -> bool:
    if url_scheme(value) not in _ALLOWED_SCHEMES:
        return False
    cleaned = _TAB_OR_NEWLINE.sub("", value.strip(_C0_AND_SPACE))
    try:
        return bool(urlsplit(cleaned).hostname)
    except ValueError:
        return False


def _canonical_ok(value: str) -> bool:
    scheme = url_scheme(value)
    if scheme is None or scheme in _ALLOWED_SCHEMES:
        return True
    # `www.http://host/...` parses as scheme `www.http`. No browser executes a
    # dotted scheme and none of the dangerous ones (`javascript`, `data`,
    # `vbscript`, `file`, `blob`) contains a dot, so it is a broken host, not
    # an attack, and the UI renders a non-http value as text in any case.
    return "." in scheme


class BundleSource(StrictModel):
    """Which local job this bundle is. Never names a cloud job."""

    source_instance_id: str = Field(
        pattern=INSTANCE_ID_PATTERN, description="Random id of the local `.jobs/` directory."
    )
    source_label: str | None = Field(
        default=None, pattern=SOURCE_LABEL_PATTERN, description="Optional machine name."
    )
    source_job_id: str = Field(
        pattern=SOURCE_JOB_ID_PATTERN, description="The local job id (32 hex characters)."
    )


class JobImportBundle(StrictModel):
    """One finished crawl, as uploaded. See the module docstring for what is excluded."""

    format: Literal["rankuno.job-bundle"] = Field(description="Bundle type marker.")
    version: Literal[1] = Field(description="Bundle schema version.")
    source: BundleSource = Field(description="The local job this came from.")
    status: Literal["succeeded", "partial"] = Field(
        description="Terminal outcome. A failed, queued or running job cannot be imported."
    )
    label: str = Field(default="", max_length=200, description="The local job's label.")
    error: str | None = Field(
        default=None, max_length=2000, description="Why a partial crawl stopped, if it did."
    )
    started_at: AwareDatetime = Field(description="When the crawl started.")
    finished_at: AwareDatetime = Field(description="When the crawl finished.")
    request: PageClassificationInput = Field(description="The settings the crawl ran with.")
    result: PageClassificationOutput = Field(description="The crawl's output.")
    homepage_html: str | None = Field(
        default=None, description="The homepage body, so the menu can be re-parsed."
    )

    @model_validator(mode="after")
    def _check_times_and_sizes(self) -> JobImportBundle:
        if self.finished_at < self.started_at:
            msg = "finished_at is before started_at"
            raise ValueError(msg)
        if self.finished_at > datetime.now(UTC) + _CLOCK_SKEW:
            msg = "finished_at is in the future"
            raise ValueError(msg)
        if self.homepage_html is not None and (
            len(self.homepage_html.encode("utf-8", "ignore")) > MAX_BUNDLE_HOMEPAGE_BYTES
        ):
            msg = "homepage_html is over the 5 MiB limit"
            raise ValueError(msg)
        return self


def audit_url_schemes(bundle: JobImportBundle) -> list[str]:
    """Every location whose URL fails its rule, in document order.

    Returns locations only, never values: the caller reports them to a client
    and logs them, and a value is exactly the attacker-controlled text that
    must not be echoed.

    Args:
        bundle: An already-validated bundle.

    Returns:
        Paths such as `result.pages[12].url`. Empty when every value passes.
    """
    return [location for location, value, check in _url_values(bundle) if not check(value)]


def _url_values(bundle: JobImportBundle) -> Iterator[tuple[str, str, _Check]]:
    request = bundle.request
    result = bundle.result
    yield "request.base_url", request.base_url, _strict_ok
    for i, url in enumerate(request.seed_urls):
        yield f"request.seed_urls[{i}]", url, _strict_ok
    for i, url in enumerate(request.exclude_urls):
        yield f"request.exclude_urls[{i}]", url, _strict_ok
    yield "result.base_url", result.base_url, _strict_ok
    yield "result.discovery.base_url", result.discovery.base_url, _strict_ok
    for i, page in enumerate(result.pages):
        at = f"result.pages[{i}]"
        yield f"{at}.url", page.url, _strict_ok
        yield f"{at}.canonical_url", page.canonical_url, _canonical_ok
        if page.final_url:
            yield f"{at}.final_url", page.final_url, _strict_ok
        for j, hop in enumerate(page.redirect_chain):
            yield f"{at}.redirect_chain[{j}]", hop, _strict_ok
        if page.nav_parent_url is not None:
            yield f"{at}.nav_parent_url", page.nav_parent_url, _strict_ok
    # Iterative, not recursive: depth is bounded by the JSON parser's own
    # nesting limit, but a walk that cannot overflow the stack needs no proof.
    stack: list[tuple[str, NavNode]] = [
        (f"result.navigation.roots[{i}]", node) for i, node in enumerate(result.navigation.roots)
    ]
    while stack:
        at, node = stack.pop()
        if node.url is not None:
            yield f"{at}.url", node.url, _strict_ok
        stack.extend((f"{at}.children[{i}]", child) for i, child in enumerate(node.children))
