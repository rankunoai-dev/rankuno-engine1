"""Wire contracts for the `--crawl-list` half of worker dispatch (ADR 0023).

Split out of `worker_schemas.py` on the same line `url_list_routes.py` was
split out of `worker_dashboard_routes.py`: everything here answers "which
URLs, and what was dropped on the way", and everything left there answers
"which machine, and may it run this". Two files that each hold one concern
stay inside this codebase's 400-line target and, more usefully, put every
model an approval summary renders in one place where they can be read
against each other.

The rule these models exist to keep is that **the number an operator
approves is the number that gets crawled**. `UrlListSourceOption.
candidate_url_count` and `PastedUrlPlanView.domains[].url_count` are
explicitly *before* filtering and are labelled so; `UrlListView.url_count`
is the post-filter truth and is the only count a confirmation dialog shows.
Two numbers that disagree are survivable when both say which they are; a
number in an approval that is not the number dispatched is not.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from src.core.schemas import StrictModel
from src.modules.seo.screaming_frog_control.pasted_url_list import (
    MAX_PASTE_CHARS,
    PasteCounts,
    PastedDomain,
)
from src.modules.seo.screaming_frog_control.url_list import UrlListCounts, UrlListSource

__all__ = [
    "PastedUrlPlanRequest",
    "PastedUrlPlanView",
    "UrlListRequest",
    "UrlListSourceOption",
    "UrlListSourcesView",
    "UrlListView",
]


class UrlListRequest(StrictModel):
    """Where a list-mode dispatch's URLs come from.

    Optional on a dispatch preview: omitting it is an ordinary `--crawl`
    run, which is what every caller predating ADR 0023 sends.

    `source` discriminates, and the two origins are mutually exclusive by a
    validator rather than by convention. A request carrying both would have
    an unanswerable question at its centre — which set was approved — and
    one carrying neither would preview a list-mode dispatch with no list.

    Attributes:
        source: Which origin, and for a crawl which subset. No default —
            "which URLs" is the decision being approved, and a default would
            make the large one reachable without a choice.
        source_job_id: The finished Rankuno crawl to take URLs from, for
            `ORPHANS` and `ALL`. The caller's org must own it; ownership is
            re-checked server-side against the authenticated principal,
            never inferred from this id.
        urls: The raw text an operator pasted, for `PASTED`. Sent verbatim
            and parsed server-side, so the counts an approval rests on are
            produced by the same code that produces the bytes — a browser
            that counted its own lines could show a number the dispatched
            list does not have.
    """

    source: UrlListSource
    source_job_id: str | None = Field(default=None, min_length=1, max_length=64)
    urls: str | None = Field(default=None, max_length=MAX_PASTE_CHARS)

    @model_validator(mode="after")
    def _one_origin_only(self) -> UrlListRequest:
        """Reject a request whose `source` and payload disagree."""
        if self.source is UrlListSource.PASTED:
            if self.urls is None or self.source_job_id is not None:
                raise ValueError(
                    "source 'pasted' takes 'urls' and no 'source_job_id': a pasted list "
                    "has no source crawl"
                )
        elif self.source_job_id is None or self.urls is not None:
            raise ValueError(
                f"source '{self.source.value}' takes 'source_job_id' and no 'urls': it "
                f"names a finished crawl to take URLs from"
            )
        return self


class PastedUrlPlanRequest(StrictModel):
    """What `POST /url-list/paste/plan` accepts: the pasted text, nothing else.

    No `seed_url`, deliberately. This call exists to *propose* one, and
    requiring the answer it is being asked for would make it useless.
    """

    urls: str = Field(max_length=MAX_PASTE_CHARS)


class PastedUrlPlanView(StrictModel):
    """What a paste would crawl, before anything is generated or stored.

    The paste-mode counterpart of `UrlListSourcesView`, and read the same
    way: every count here is a **candidate** count from reading the text.
    The truthful post-filter number is the preview's, and it is the only one
    an approval ever shows.

    Attributes:
        counts: The parse account — blanks, a header row, unreadable lines.
        domains: Every registrable domain the paste covers, largest first.
            More than one is the case only the operator can resolve: one
            crawl has one in-scope domain, and the rest will be excluded and
            counted.
        suggested_seed_url: The largest group's root, offered as the seed
            URL. A default the operator may overrule, never a decision.
        max_urls: The server's ceiling for one list.
        exceeds_ceiling: The largest group alone is already over it, so a
            preview would refuse. Said here so the refusal arrives before
            the operator commits.
    """

    counts: PasteCounts
    domains: list[PastedDomain] = Field(default_factory=list)
    suggested_seed_url: str = ""
    max_urls: int = Field(ge=1)
    exceeds_ceiling: bool = False


class UrlListView(StrictModel):
    """A generated, stored list as a confirmation modal should render it.

    Everything here except `sha256` exists so a human can tell *which*
    list this is. `sha256` is the only field any gate compares, and it is
    the field a caller must echo back on confirm.

    Attributes:
        source: Which subset was generated.
        source_job_id: The crawl it came from.
        source_label: That crawl's human-facing name.
        registrable_domain: The domain every kept URL sits inside — the
            rule that produced `counts.off_domain_dropped`.
        url_count: How many URLs the list holds.
        sha256: The fingerprint to echo back on confirm.
        sample: The first few URLs, verbatim.
        counts: The full per-stage filtering account, so a modal can say
            "Excluded 18 external URLs" and have it be true.
        paste: How the pasted text was read, for a `PASTED` list only.
            `None` for a crawl-sourced one, which had no text to read. Kept
            beside `counts` rather than merged into it because the two
            reconcile separately and merging would break the identity a test
            already pins on `counts`.
    """

    source: UrlListSource
    source_job_id: str = ""
    source_label: str = ""
    registrable_domain: str = ""
    url_count: int = Field(ge=1)
    sha256: str
    sample: list[str] = Field(default_factory=list)
    counts: UrlListCounts
    paste: PasteCounts | None = None


class UrlListSourceOption(StrictModel):
    """One offered (or refused) list source, with the reason either way.

    Attributes:
        source: The enum value to send back on preview.
        label: Exactly what the operator should see, including the
            "(Recommended)" marker — served rather than hard-coded in a UI
            so the recommendation has one owner.
        description: What this source is, in one sentence.
        available: Whether a preview using it would succeed.
        unavailable_reason: Why not, when `available` is false. Empty
            otherwise. Never empty when unavailable: "the option is greyed
            out and nobody knows why" is the failure this field exists to
            prevent.
        candidate_url_count: URLs available *before* filtering, or `None`
            when nothing could be counted. Not the number that will be
            dispatched — the preview reports that, after deduping and the
            off-domain filter have run.
        exceeds_ceiling: Whether counting stopped because the source is
            over `max_urls`, in which case `candidate_url_count` is a
            lower bound rather than a total.
    """

    source: UrlListSource
    label: str
    description: str = ""
    available: bool = False
    unavailable_reason: str = ""
    candidate_url_count: int | None = Field(default=None, ge=0)
    exceeds_ceiling: bool = False


class UrlListSourcesView(StrictModel):
    """Which list sources one finished crawl can offer, and the ceiling."""

    job_id: str
    label: str = ""
    base_url: str = ""
    max_urls: int = Field(ge=1)
    sources: list[UrlListSourceOption] = Field(default_factory=list)
