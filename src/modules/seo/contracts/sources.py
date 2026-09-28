"""Which Screaming Frog export files feed which issue.

`catalogue.py` already records, per issue, the export filenames whose rows
populate it. Every consumer that needs "the files behind this section of a
workbook" must ask here rather than keep its own list, because the alternative
is what build-log 0116 found: thirteen masterfile services asking for
filenames derived from their own module name (`masterfile_page_titles.py` ->
`title_missing.csv`) that no Screaming Frog export has ever contained, and a
green test suite because an empty directory produces a valid empty workbook.

Deriving here means a filename can only enter a workbook by first entering the
catalogue, which is also what `upload_manifest.ALLOWED_BUNDLE_FILENAMES`
derives from - so a file a service asks for is, by construction, a file the
upload boundary will accept. `tests/.../test_masterfile_sources.py` pins that
both ways.

Order is the catalogue's own row order, and duplicates are dropped on first
appearance: a file named by two issues (the two canonical-inlinks exports) is
read once, not twice.
"""

from __future__ import annotations

from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE
from src.modules.seo.contracts.issue_ids import IssueCategory, IssueId

__all__ = ["sources_for_categories", "sources_for_issues"]


def _dedupe(names: list[str]) -> tuple[str, ...]:
    """Catalogue order, first appearance wins."""
    return tuple(dict.fromkeys(names))


def sources_for_categories(*categories: IssueCategory) -> tuple[str, ...]:
    """Every export file behind the given categories, in catalogue order.

    Args:
        *categories: The catalogue categories a workbook section covers.

    Returns:
        Deduplicated filenames. Issues with no producible export contribute
        nothing - they are `NOT_MEASURED`, not zero (ADR 0011 §5).
    """
    wanted = frozenset(categories)
    return _dedupe(
        [name for spec in ISSUE_CATALOGUE if spec.category in wanted for name in spec.sf_sources]
    )


def sources_for_issues(*issue_ids: IssueId) -> tuple[str, ...]:
    """Every export file behind the given issues, in catalogue order.

    For the three services that split one category between them: `Content
    Issues`, `Duplicate Content` and `Lorem Ipsum` all draw on
    `CONTENT_ISSUES`, and naming the issues is what keeps a row from landing
    in two workbooks.

    Args:
        *issue_ids: The catalogue issues a workbook section covers.

    Returns:
        Deduplicated filenames, in catalogue order.
    """
    wanted = frozenset(issue_ids)
    return _dedupe(
        [name for spec in ISSUE_CATALOGUE if spec.id in wanted for name in spec.sf_sources]
    )
