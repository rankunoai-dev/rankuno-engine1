"""Shared contracts between the crawler and client deliverables (ADR 0011).

`page_classifier` and `deliverables` both import from here; neither imports the
other, and this package imports neither. That direction is what keeps the two
"separate but connected", and a test enforces it.
"""

from src.modules.seo.contracts.audit import (
    AuditDataset,
    AuditLink,
    AuditPage,
    AuditSource,
    Coverage,
    external_urls_note,
)
from src.modules.seo.contracts.catalogue import (
    ISSUE_CATALOGUE,
    ISSUE_SPECS,
    RAE_LABELS,
    IssueCategory,
    IssueId,
    IssueSpec,
    Priority,
    RaeLabel,
    Severity,
)
from src.modules.seo.contracts.url_normalizer import UrlNormalizer

__all__ = [
    "ISSUE_CATALOGUE",
    "ISSUE_SPECS",
    "RAE_LABELS",
    "AuditDataset",
    "AuditLink",
    "AuditPage",
    "AuditSource",
    "Coverage",
    "IssueCategory",
    "IssueId",
    "IssueSpec",
    "Priority",
    "RaeLabel",
    "Severity",
    "UrlNormalizer",
    "external_urls_note",
]
