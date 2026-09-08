"""`AuditDataset`: the seam between the crawler and client deliverables.

ADR 0011 makes a serialisable model, not a process boundary, the connection
between `page_classifier` and `deliverables`. Both import this module; neither
imports the other. The model is deliberately plain - a page spine, issue
membership, and a mandatory coverage map - so it can later be put behind HTTP
without redesign.

The defining stance is that **not measured is a value**. RAE rendered a missing
input as "no issues"; here every `IssueId` must declare `MEASURED` or
`NOT_MEASURED`, and the latter cannot carry members. The invariants are
validators, so a dataset that violates them cannot be constructed.

This module imports only from `core` and the sibling `catalogue`. It must never
import `page_classifier` or `deliverables`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.core.schemas import StrictModel
from src.modules.seo.contracts.issue_ids import IssueCategory, IssueId, Priority, Severity

__all__ = [
    "MAX_HOSTNAME_LENGTH",
    "MAX_NOTE_LENGTH",
    "MAX_URL_LENGTH",
    "AuditDataset",
    "AuditLink",
    "AuditPage",
    "AuditSource",
    "Coverage",
    "IssueCategory",
    "IssueId",
    "Priority",
    "Severity",
    "external_urls_note",
]

MAX_HOSTNAME_LENGTH: Final[int] = 253
"""RFC 1035 ceiling for a fully qualified hostname."""

MAX_URL_LENGTH: Final[int] = 2048
"""Conventional browser/CDN limit; anything longer is not a page we report on."""

MAX_NOTE_LENGTH: Final[int] = 500
"""Notes are adapter caveats for humans, not payloads."""

_HOSTNAME_LABEL: Final[str] = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME_RE: Final[re.Pattern[str]] = re.compile(rf"^{_HOSTNAME_LABEL}(?:\.{_HOSTNAME_LABEL})+$")


class AuditSource(StrEnum):
    """Which adapter produced the dataset. Drives denominator semantics in Phase 2.

    An enum rather than a `Literal` so an adapter can name itself by member and
    a workbook can switch on it without string comparison (build-log 0073 §8.2).
    """

    ENGINE = "engine"
    SCREAMING_FROG = "screaming_frog"


class Coverage(StrEnum):
    """Whether an issue was looked for at all.

    `NOT_MEASURED` is distinct from "measured, none found" and a workbook must
    render it as such (ADR 0011 §5).
    """

    MEASURED = "MEASURED"
    NOT_MEASURED = "NOT_MEASURED"


class _AuditModel(StrictModel):
    """Contract base: strict, and whitespace-trimmed on every string field.

    Trimming lives here rather than on `StrictModel` because the catalogue's
    `RaeLabel` must preserve RAE's original spellings, trailing space included.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=False, validate_assignment=True, str_strip_whitespace=True
    )


class AuditPage(_AuditModel):
    """One URL in the spine. `url` is the normalised key every issue set refers to.

    The rulebook fields are `None` until Phase 1's `apply_rulebook` sets them;
    they live here rather than on `FullPageIntelligenceProfile` by design (S1).
    """

    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    theme_1: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    theme_2: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    language: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    business_priority: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)


class AuditLink(_AuditModel):
    """A directed edge. Only the Screaming Frog adapter fills these in Phase 0 (D4)."""

    source: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    destination: str = Field(min_length=1, max_length=MAX_URL_LENGTH)


def external_urls_note(issue: IssueId) -> str:
    """Return the note an adapter must attach when an issue may name URLs outside `pages`.

    Inlink destinations are the motivating case. The note is generated, not
    free-typed, so invariant 2 can recognise it exactly.
    """
    return f"external-urls-admitted: {issue.value}"


class AuditDataset(_AuditModel):
    """Everything a deliverable needs, and nothing the crawler must keep.

    `issues` may omit an `IssueId` (omitted means empty); `coverage` may not.
    """

    source: AuditSource
    site: str = Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    produced_at: datetime
    pages: tuple[AuditPage, ...]
    issues: Mapping[IssueId, frozenset[str]]
    coverage: Mapping[IssueId, Coverage]
    links: tuple[AuditLink, ...] = ()
    notes: tuple[str, ...] = ()

    @field_validator("site")
    @classmethod
    def _site_is_bare_hostname(cls, value: str) -> str:
        """Reject schemes, ports and paths so two adapters cannot spell one site two ways."""
        if not _HOSTNAME_RE.fullmatch(value):
            msg = f"site must be a bare lowercase hostname, got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("produced_at")
    @classmethod
    def _produced_at_is_aware(cls, value: datetime) -> datetime:
        """A naive timestamp is ambiguous once a workbook leaves the workstation."""
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            msg = "produced_at must be timezone-aware"
            raise ValueError(msg)
        return value

    @field_validator("notes")
    @classmethod
    def _notes_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Cap note length here because `Field(max_length=...)` bounds the tuple, not its items."""
        for note in value:
            if len(note) > MAX_NOTE_LENGTH:
                msg = f"note exceeds {MAX_NOTE_LENGTH} characters"
                raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _check_invariants(self) -> AuditDataset:
        """Enforce the three contract invariants from the plan (§3), plus a fourth.

        Invariant 1 stops an adapter forgetting a category. Invariant 3 keeps
        "not measured" and "measured, none found" as different values. Invariant 2
        keeps every reported URL resolvable against the spine unless the adapter
        has said, per issue, that it cannot be. Invariant 4 (P0-3) makes the spine
        a set: a page counted twice would inflate every denominator in Phase 2.
        """
        missing = [issue.value for issue in IssueId if issue not in self.coverage]
        if missing:
            msg = f"coverage must declare every IssueId; missing {missing}"
            raise ValueError(msg)

        known_urls = {page.url for page in self.pages}
        if len(known_urls) != len(self.pages):
            duplicates = len(self.pages) - len(known_urls)
            msg = f"pages[].url must be unique; {duplicates} duplicate(s) found"
            raise ValueError(msg)
        admitted = {issue for issue in IssueId if external_urls_note(issue) in self.notes}
        for issue, urls in self.issues.items():
            if self.coverage[issue] is Coverage.NOT_MEASURED and urls:
                msg = f"{issue.value} is NOT_MEASURED but has {len(urls)} member URL(s)"
                raise ValueError(msg)
            if issue in admitted:
                continue
            unknown = sorted(urls - known_urls)
            if unknown:
                msg = (
                    f"{issue.value} names {len(unknown)} URL(s) not in pages "
                    f"(first: {unknown[0]!r}); add external_urls_note() if intended"
                )
                raise ValueError(msg)
        return self
